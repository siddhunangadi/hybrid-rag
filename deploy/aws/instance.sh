#!/bin/bash
# Runs on the EC2 host as root.
#   install   first boot (called from user-data): swap, Docker, then redeploy
#   redeploy  pull the latest main, rebuild the image, restart the container, check health
set -euo pipefail

APP_DIR=/opt/hybrid-rag
IMAGE=hybrid-rag
# shellcheck disable=SC1091
source /etc/hybrid-rag.conf   # REGION, LOG_GROUP (written by user-data)
export GIT_SSH_COMMAND="ssh -i /root/.ssh/hybrid-rag-deploy -o IdentitiesOnly=yes"

add_swap() {
  # 2 GB swap: headroom for PDF parsing and image builds on a 2 GB instance.
  if ! swapon --show | grep -q /swapfile; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -w vm.swappiness=10
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
  fi
}

install_docker() {
  dnf install -y docker
  systemctl enable --now docker
}

render_env() {
  # Non-secret settings from the repo + secrets from Parameter Store -> root-only .env
  umask 077
  {
    cat "$APP_DIR/deploy/aws/app.env"
    aws ssm get-parameters-by-path --region "$REGION" --path /hybrid-rag/env/ --with-decryption \
      --query 'Parameters[].[Name,Value]' --output text |
      while IFS=$'\t' read -r name value; do printf '%s=%s\n' "${name##*/}" "$value"; done
  } > "$APP_DIR/.env.new"
  mv "$APP_DIR/.env.new" "$APP_DIR/.env"
}

wait_healthy() {
  for _ in $(seq 1 60); do
    if curl -fsS http://localhost/health >/dev/null 2>&1; then
      secret=$(grep '^ORIGIN_SECRET=' "$APP_DIR/.env" | cut -d= -f2-)
      if curl -fsS -H "X-Origin-Secret: $secret" http://localhost/ready >/dev/null; then
        echo "healthy and connected to the database"
        return 0
      fi
    fi
    sleep 2
  done
  echo "app did not become ready; recent logs:" >&2
  docker logs --tail 50 "$IMAGE" >&2 || true
  return 1
}

redeploy() {
  cd "$APP_DIR"
  git fetch --depth 1 origin main
  git reset --hard origin/main
  render_env
  version=$(git rev-parse --short HEAD)
  docker build --pull -t "$IMAGE:$version" -t "$IMAGE:latest" .
  # Brief restart (seconds). Production uses rolling/blue-green deploys behind a load balancer instead.
  docker rm -f "$IMAGE" >/dev/null 2>&1 || true
  docker run -d --name "$IMAGE" --restart unless-stopped \
    -p 80:8000 --env-file "$APP_DIR/.env" --stop-timeout 30 \
    --log-driver awslogs --log-opt awslogs-region="$REGION" \
    --log-opt awslogs-group="$LOG_GROUP" --log-opt awslogs-stream=app \
    "$IMAGE:$version"
  wait_healthy
  docker image prune -f >/dev/null
  echo "deployed $version"
}

main() {
  case "${1:-}" in
    install) add_swap; install_docker; redeploy ;;
    redeploy) redeploy ;;
    *) echo "usage: $0 install|redeploy" >&2; exit 2 ;;
  esac
}

main "$@"
