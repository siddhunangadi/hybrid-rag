# Hybrid RAG

Multi-tenant document Q&A: hybrid search (pgvector HNSW on Supabase Postgres + BM25 via `bm25s`) fused with Reciprocal
Rank Fusion, reranked, and answered with enforced inline citations. Everything model-related runs on OpenAI with one
key: `text-embedding-3-small` embeddings and `gpt-4o-mini` for answers, reranking, follow-up rewriting and OCR.
LangSmith for evaluation, tracing and user feedback.

## Run

```bash
cp .env.example .env                     # OPENAI_API_KEY + Supabase session-pooler URL (+ LangSmith key)
pip install -r requirements.txt
python admin.py create-key myteam        # prints an API key once; paste it into the UI
uvicorn main:app                         # http://localhost:8000; migrations apply on start
```

Docker: `docker build -t hybrid-rag . && docker run --env-file .env -p 8000:8000 hybrid-rag`.
Requires pgvector 0.8+ (Supabase default).

## Deploy to AWS

A free-plan-sized demo: one Graviton EC2 instance in the database's region behind CloudFront HTTPS, reachable only
through CloudFront, with secrets in SSM Parameter Store, logs and alarms in CloudWatch, and a cost budget
(`deploy/aws/demo-stack.yaml`). Prerequisites: an AWS account, the AWS CLI (`aws configure`) and the GitHub CLI
(`gh auth login`).

```bash
deploy/aws/deploy.sh setup you@example.com   # secrets from .env → SSM, deploy key, stack, smoke test; prints the URL
deploy/aws/deploy.sh ship                    # after code changes: push main and roll it out
deploy/aws/deploy.sh status
```

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) describes the demo, the production architecture it maps to (multi-AZ
Fargate, Aurora, SQS, WAF, CI/CD with an evaluation gate) and why each piece changes at scale.

## How it works

- **Ingestion** is a durable queue in the `documents` table: uploads are stored, then claimed by workers with
  `FOR UPDATE SKIP LOCKED`. Transient failures retry (3 attempts), bad files fail immediately, a deploy hands in-flight
  jobs back to the queue, and a crashed worker's job is reclaimed after 10 minutes. Workers run inside the API by
  default; for heavy ingestion run `python ingest.py` separately and set `RUN_WORKER=false` on the API.
- **Untrusted PDFs** are parsed and rendered in a child process that is killed after 120 s and memory-capped
  (`PDF_PARSE_MEMORY_MB`, default 1 GB; enforced on Linux, i.e. in Docker), with page (`MAX_PDF_PAGES`) and text-size
  limits.
- **Scanned PDFs** (mostly empty text layer) are rendered page by page (PDFium) and transcribed by `gpt-4o-mini` from
  high-detail images. Low-detail images and OpenAI's PDF-file input were measured to drop content, so they aren't used.
- **Chunks carry context**: each chunk is stored and embedded as `[Document title > section]` + text, so a row cut from
  the middle of a table still says which product or policy version it belongs to.
- **Query**: follow-ups are rewritten into standalone questions → embedding → dense search and BM25 keyword search in
  parallel → RRF → `gpt-4o-mini` rerank of the top 15 → confidence gate (no answer call below `MIN_SIMILARITY`) →
  `gpt-4o-mini` answer that must cite passages; answers without a valid citation are replaced by "Insufficient context".
- **BM25** runs in each server process from an in-memory index per team (up to 50 teams, least recently used evicted),
  rebuilt when that team's documents change; the check overlaps the query embedding, so it adds no latency. BM25's IDF
  weighting makes rare identifiers such as `E142` count.
- **Helper calls degrade gracefully**: rewrite and rerank time out after `AUX_TIMEOUT_S`; any failure pauses helper
  calls for 30 s and the query continues with the raw question / RRF order.
- **Embedding model changes** are safe: every chunk records the model that embedded it, dense search only compares
  vectors from the current `EMBED_MODEL`, and `python admin.py reembed` re-embeds stored text (no original files needed).
- **Languages**: answers come back in the question's language; embeddings are multilingual; BM25 uses English stemming.

## Teams, keys and spending caps

```bash
python admin.py create-key acme --label "web app"
python admin.py list-keys
python admin.py revoke-key rag_AbCd12                       # takes effect within 60 s
python admin.py set-limits acme --queries 1000 --tokens 500000 --upload-mb 500 --ocr-pages 100   (-1 = default)
python admin.py usage --days 7
python admin.py reembed                                     # after changing EMBED_MODEL
python admin.py delete-tenant acme --yes
```

Keys are stored only as SHA-256 hashes. Each team has daily limits on queries, OpenAI tokens (answer + rerank + rewrite),
upload volume and OCR pages; `GLOBAL_DAILY_TOKENS` and `GLOBAL_DAILY_OCR_PAGES` are hard daily ceilings across all teams
that protect the OpenAI balance. OCR is metered by page rather than tokens because a high-detail page image costs about
37k tokens (~$0.006), as much as ~10 queries. Over-limit requests get HTTP 429; days roll over at 00:00 UTC.

## API

All endpoints except `/health` and `/ready` need `Authorization: Bearer <key>`. When `ORIGIN_SECRET` is set (behind
CloudFront), every request except `/health` must also carry a matching `X-Origin-Secret` header.

| Method | Path | Purpose |
|---|---|---|
| POST | `/ingest` | Upload `.pdf`/`.txt`/`.md` files; 202, processed by the queue |
| GET | `/documents` | Documents with `queued` / `processing` / `ready` / `failed` status |
| DELETE | `/documents/{source}` | Delete a document and its chunks |
| POST | `/query` | `{"question", "history": [{"role", "content"}]}` → answer, cited chunks with pages, latency, tokens |
| POST | `/feedback` | `{"trace_id", "score": 0 or 1}` → LangSmith feedback on your own team's answers (needs tracing) |
| GET | `/health` | Liveness: the process is up (no dependency checks) |
| GET | `/ready` | Readiness: the database is reachable |

## Evaluation (LangSmith)

```bash
python evaluate.py draft --tenant acme -n 40        # gpt-4o-mini drafts Q&A from random chunks of your real docs
# review eval.draft.jsonl: fix/delete bad items, add real user questions and some the docs can't answer
python evaluate.py upload eval.draft.jsonl
python evaluate.py run --tenant acme --min-score 0.8  # metrics + suggested MIN_SIMILARITY, exit 1 on regression
```

The best test cases come from real traffic: with `LANGSMITH_TRACING=true` every query is traced and the UI's 👍/👎
buttons attach `user_rating` feedback (only to answers your own team received). Filter for `user_rating = 0` in
LangSmith and add those runs to your dataset. Aim for 50-200 examples before trusting scores or the threshold.

## Benchmark

`benchmark/` holds a fixed test corpus (10 documents of a fictional company: HR handbook, 2025 *and* 2026 travel
policies, two products with overlapping error codes, SLA tables, a scanned PDF, a Spanish policy and a document
containing a prompt-injection attack) and 76 reviewed questions (lookalikes, versions, tables, OCR, multilingual,
multi-hop, injection probes, 7 unanswerable). Load `benchmark/docs/*` into a team, then:

```bash
python evaluate.py upload benchmark/questions.jsonl --dataset hybrid-rag-benchmark
python evaluate.py run --tenant evalcorp --dataset hybrid-rag-benchmark --min-score 0.9
```

Current stack (OpenAI embeddings + BM25 + gpt-4o-mini rerank and answers):

| hit@5 | reciprocal rank | expected source cited | answer correct | grounded | answer-or-refuse | injection resisted |
|---|---|---|---|---|---|---|
| 0.986 | 0.957 | 0.986 | 0.971 | 1.000 | 1.000 | 2/2 |

How it got there (earlier Gemini-embedding runs): chunk context headers lifted the answer-or-refuse decision from
0.92 to 0.96; identifier-aware keyword ranking and a "don't mix products/versions" prompt rule to 0.97; reranking to
~1.0. BM25 replaced Postgres `tsvector` with equal quality and no identifier-boost workaround.

`MIN_SIMILARITY=0.30` is calibrated for `text-embedding-3-small`: off-topic questions score ~0.2, the weakest
answerable question 0.375. On-topic questions the documents can't answer ("PTO in the UK?") score 0.55-0.76, so no
similarity threshold can catch them; the answer model's refusal does (7/7 on the benchmark).

Known misses: gpt-4o-mini reads "5 days (US and India), 10 days (Germany)" as 10 for India (a stronger `CHAT_MODEL`
would help); an undated question may cite a superseded policy version (delete superseded documents). A full benchmark
run costs ~325k tokens (~$0.05).

## Performance and cost (Supabase free tier in ap-southeast-1, client ~130 ms away)

| | |
|---|---|
| Query, 8 concurrent, end to end | 40/40 OK, p50 3.4 s, p95 4.2 s, ~2 queries/s per process |
| Query cost | ~4k tokens (~2.7k of them rerank), ~$0.0006; `RERANK=false` saves ~70% at some quality cost |
| Scanned page OCR | ~37k tokens (~$0.006) and ~5-7 s per page |
| DB execution, hybrid search over 10k chunks | ~2 ms; latency is network round trips, not the database |
| Storage | ~16 KB per chunk incl. indexes: the 500 MB free tier holds ~30k chunks |

Deploy the app in the database's region (round trips drop from ~130 ms to ~1 ms). Keep (server processes ×
`DB_POOL_MAX`) under the Supabase session pooler's 15-client limit, or use the transaction pooler.

## Schema migrations

Schema changes go in `db.MIGRATIONS`, append-only (never edit, reorder or squash: databases record which versions they
applied); they run automatically under an advisory lock at startup.

## Operational notes

- Put TLS and per-IP rate limiting in front (reverse proxy / gateway); per-team cost caps are built in.
- Changing `EMBED_DIM` after documents exist requires a schema change; changing `EMBED_MODEL` needs `admin.py reembed`.
- Not handled: images inside documents, `.docx`/`.html`, streaming answers.
