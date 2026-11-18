#!/usr/bin/env bash
# Deploy the demo to AWS (run from your laptop; needs the AWS CLI and the GitHub CLI, both signed in).
#
#   deploy/aws/deploy.sh setup you@example.com   first deployment: secrets, deploy key, stack, smoke test
#   deploy/aws/deploy.sh ship                    push main and roll it out to the instance
#   deploy/aws/deploy.sh status                  URL and health
#
# Secrets are read from your local .env and stored in SSM Parameter Store; they are never printed.
set -euo pipefail

REGION=${AWS_REGION:-ap-southeast-1}   # same region as the Supabase database
STACK=${STACK_NAME:-hybrid-rag-demo}
REPO=${REPO:-siddhunangadi/hybrid-rag}
ROOT=$(git rev-parse --show-toplevel)

need() { command -v "$1" >/dev/null || { echo "missing $1: $2" >&2; exit 1; }; }
env_value() { grep -E "^$1=" "$ROOT/.env" | tail -1 | cut -d= -f2-; }
put_secret() { aws ssm put-parameter --region "$REGION" --name "$1" --type SecureString --overwrite --value "$2" >/dev/null; }
get_secret() { aws ssm get-parameter --region "$REGION" --name "$1" --with-decryption --query Parameter.Value --output text 2>/dev/null; }
output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

smoke_test() {
  local url=$1
  echo "waiting for $url (CloudFront takes a few minutes the first time)..."
  for _ in $(seq 1 90); do
    curl -fsS "$url/health" >/dev/null 2>&1 && break
    sleep 10
  done
  curl -fsS "$url/health" >/dev/null || { echo "health check failed" >&2; return 1; }
  # A deliberately invalid key must reach the app: "Invalid or revoked" proves CloudFront forwards the
  # Authorization header; "Missing API key" would mean it is being stripped.
  local detail
  detail=$(curl -sS "$url/documents" -H "Authorization: Bearer rag_smoke_test_invalid" || true)
  case "$detail" in
    *"Invalid or revoked"*) echo "smoke test passed: HTTPS, origin secret and Authorization forwarding OK" ;;
    *) echo "unexpected response to an authenticated request: $detail" >&2; return 1 ;;
  esac
}

setup() {
  local email=${1:?usage: deploy.sh setup you@example.com}
  need aws "brew install awscli, then aws configure"
  need gh "brew install gh, then gh auth login"
  need openssl "comes with macOS"
  aws sts get-caller-identity --query Account --output text >/dev/null

  echo "1/4 storing secrets in SSM Parameter Store (SecureString)"
  for key in OPENAI_API_KEY DATABASE_URL LANGSMITH_API_KEY; do
    value=$(env_value "$key")
    [ -n "$value" ] || { echo "$key is missing from .env" >&2; exit 1; }
    put_secret "/hybrid-rag/env/$key" "$value"
  done
  # Reuse an existing origin secret so re-running setup doesn't break the CloudFront/app pairing.
  origin_secret=$(get_secret /hybrid-rag/env/ORIGIN_SECRET || true)
  [ -n "$origin_secret" ] || origin_secret=$(openssl rand -hex 32)
  put_secret /hybrid-rag/env/ORIGIN_SECRET "$origin_secret"

  echo "2/4 read-only deploy key for the private repository"
  if [ -z "$(get_secret /hybrid-rag/deploy-key || true)" ]; then
    tmp=$(mktemp -d)
    ssh-keygen -q -t ed25519 -N "" -C "hybrid-rag-ec2" -f "$tmp/key"
    gh repo deploy-key add "$tmp/key.pub" --repo "$REPO" --title "hybrid-rag EC2 (read-only)"
    put_secret /hybrid-rag/deploy-key "$(cat "$tmp/key")"
    rm -rf "$tmp"
  fi

  echo "3/4 checking the CloudFront prefix list fits the security group"
  read -r prefix_list weight < <(aws ec2 describe-managed-prefix-lists --region "$REGION" \
    --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
    --query 'PrefixLists[0].[PrefixListId,MaxEntries]' --output text)
  rule_limit=$(aws service-quotas get-service-quota --region "$REGION" --service-code vpc \
    --quota-code L-0EA8095F --query Quota.Value --output text 2>/dev/null || echo 60)
  if (( weight > ${rule_limit%.*} )); then
    echo "the CloudFront prefix list counts as $weight rules but security groups allow ${rule_limit%.*};" \
         "request a higher 'Inbound or outbound rules per security group' quota" >&2
    exit 1
  fi

  echo "4/4 creating the stack (about 5 minutes, plus a few for the first image build)"
  aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
    --template-file "$ROOT/deploy/aws/demo-stack.yaml" --capabilities CAPABILITY_IAM \
    --no-fail-on-empty-changeset \
    --parameter-overrides AlertEmail="$email" OriginSecret="$origin_secret" \
      CloudFrontPrefixListId="$prefix_list" RepoSshUrl="git@github.com:$REPO.git"

  url=$(output Url)
  smoke_test "$url"
  echo
  echo "Live at: $url"
  echo "Confirm the AWS Notifications subscription email sent to $email to receive alerts."
}

ship() {
  need aws "brew install awscli"
  git -C "$ROOT" push origin main
  instance=$(output InstanceId)
  command_id=$(aws ssm send-command --region "$REGION" --instance-ids "$instance" \
    --document-name AWS-RunShellScript --timeout-seconds 900 \
    --comment "hybrid-rag redeploy $(git -C "$ROOT" rev-parse --short HEAD)" \
    --parameters 'commands=["/opt/hybrid-rag/deploy/aws/instance.sh redeploy"]' \
    --query Command.CommandId --output text)
  echo "redeploying on $instance..."
  while true; do
    status=$(aws ssm get-command-invocation --region "$REGION" --command-id "$command_id" \
      --instance-id "$instance" --query Status --output text 2>/dev/null || echo Pending)
    case "$status" in Pending|InProgress|Delayed) sleep 5 ;; *) break ;; esac
  done
  aws ssm get-command-invocation --region "$REGION" --command-id "$command_id" --instance-id "$instance" \
    --query StandardOutputContent --output text | tail -5
  [ "$status" = Success ] || { echo "redeploy $status" >&2; exit 1; }
  smoke_test "$(output Url)"
}

status() {
  url=$(output Url)
  echo "URL: $url"
  curl -fsS "$url/health" && echo
}

case "${1:-}" in
  setup) shift; setup "$@" ;;
  ship) ship ;;
  status) status ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
