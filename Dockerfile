FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
# Wheels only: every dependency ships prebuilt wheels for amd64 and arm64 (Graviton), so a
# dependency that would need a compiler fails the build loudly instead of slowly.
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt && useradd --system --no-create-home app

COPY *.py ./
COPY static ./static

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
# One process per container by default: each process keeps its own BM25 cache and DB pool, so scale
# with more containers/tasks rather than more workers. Behind a proxy (CloudFront/ALB) only the proxy can
# reach the container, so forwarded headers are trusted. Ingestion workers run in-process unless
# RUN_WORKER=false; to scale them separately run: docker run --env-file .env hybrid-rag python ingest.py
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-1} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 30"]
