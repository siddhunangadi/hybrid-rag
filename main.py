import asyncio
import hmac
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import asyncpg
import openai
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from langsmith import Client as LangSmith
from langsmith import traceable
from langsmith.utils import tracing_is_enabled
from pydantic import BaseModel, Field

import db
import generate
import ingest
import retrieve
from admin import hash_key
from config import settings

log = logging.getLogger("rag")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

KEY_CACHE_SECONDS = 60
key_cache: dict[str, tuple[str, float]] = {}

# One upsert both records the attempt and returns today's totals plus the
# tenant's limits; the caller raises inside the transaction to roll it back.
CHARGE_SQL = """
WITH used AS (
    INSERT INTO usage_daily (tenant, queries, upload_bytes) VALUES ($1, $2, $3)
    ON CONFLICT (tenant, day) DO UPDATE SET
        queries = usage_daily.queries + EXCLUDED.queries,
        upload_bytes = usage_daily.upload_bytes + EXCLUDED.upload_bytes
    RETURNING queries, tokens, upload_bytes
)
SELECT used.*, t.daily_queries, t.daily_tokens, t.daily_upload_mb,
       (SELECT coalesce(sum(tokens), 0) FROM usage_daily WHERE day = current_date) AS global_tokens
FROM used JOIN tenants t ON t.name = $1
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await db.create_pool()
    # Interactive client: (timeout x attempts) must fit inside the edge proxy's 60 s origin read timeout
    # (CloudFront), or users see a 504 while we are still retrying. Background work uses its own patient client.
    app.state.openai = openai.AsyncOpenAI(
        api_key=settings.openai_api_key, timeout=settings.openai_timeout_s, max_retries=settings.openai_max_retries
    )
    stale = await app.state.pool.fetchval("SELECT count(*) FROM chunks WHERE embed_model <> $1", settings.embed_model)
    if stale:
        log.warning("%d chunks were embedded with another model and are skipped by dense search; "
                    "run `python admin.py reembed`", stale)
    stop, background_llm = asyncio.Event(), ingest.background_llm()
    workers = [
        asyncio.create_task(ingest.worker(app.state.pool, background_llm, stop))
        for _ in range(settings.worker_concurrency if settings.run_worker else 0)
    ]
    try:
        yield
    finally:
        stop.set()
        _, busy = await asyncio.wait(workers, timeout=20) if workers else (set(), set())
        for task in busy:  # cancelled jobs are re-queued immediately by ingest.process
            task.cancel()
        await asyncio.gather(*busy, return_exceptions=True)
        try:
            await app.state.openai.close()
            await background_llm.close()
        finally:
            await app.state.pool.close()


app = FastAPI(title="Hybrid RAG", lifespan=lifespan)


async def upstream_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Upstream failure on %s", request.url.path, exc_info=exc)
    return JSONResponse(status_code=502, content={"detail": f"Upstream service error: {type(exc).__name__}"})


for exc_type in (openai.APIError, asyncpg.PostgresError, asyncpg.InterfaceError, OSError):
    app.add_exception_handler(exc_type, upstream_error)


@app.middleware("http")
async def require_origin_secret(request: Request, call_next):
    # Behind CloudFront, only requests carrying the distribution's secret header are served, so the
    # origin can't be reached directly or through someone else's CloudFront distribution.
    # /health stays open for the container's own liveness probe.
    expected = settings.origin_secret
    if expected and request.url.path != "/health":
        if not hmac.compare_digest(request.headers.get("x-origin-secret", "").encode(), expected.encode()):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    return await call_next(request)


async def current_tenant(request: Request, authorization: Annotated[str, Header()] = "") -> str:
    key = authorization.removeprefix("Bearer ").strip()
    if not key:
        raise HTTPException(401, "Missing API key", headers={"WWW-Authenticate": "Bearer"})
    digest = hash_key(key)
    cached = key_cache.get(digest)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    tenant = await request.app.state.pool.fetchval(
        "SELECT tenant FROM api_keys WHERE key_hash = $1 AND revoked_at IS NULL", digest
    )
    if tenant is None:
        raise HTTPException(401, "Invalid or revoked API key", headers={"WWW-Authenticate": "Bearer"})
    key_cache[digest] = (tenant, time.monotonic() + KEY_CACHE_SECONDS)
    return tenant


Tenant = Annotated[str, Depends(current_tenant)]


async def charge(pool: asyncpg.Pool, tenant: str, queries: int = 0, upload_bytes: int = 0) -> None:
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(CHARGE_SQL, tenant, queries, upload_bytes)
        limit = {k: row[f"daily_{k}"] if row[f"daily_{k}"] is not None else getattr(settings, f"daily_{k}")
                 for k in ("queries", "tokens", "upload_mb")}
        if queries and row["queries"] > limit["queries"]:
            raise HTTPException(429, "Daily query limit reached for this API key's team")
        if queries and row["tokens"] >= limit["tokens"]:
            raise HTTPException(429, "Daily token budget reached for this API key's team")
        if queries and row["global_tokens"] >= settings.global_daily_tokens:
            raise HTTPException(429, "Service-wide daily token budget reached; try again tomorrow")
        if upload_bytes and row["upload_bytes"] > limit["upload_mb"] * 2**20:
            raise HTTPException(429, "Daily upload limit reached for this API key's team")


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class Query(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default_factory=list, max_length=12)


class Feedback(BaseModel):
    trace_id: uuid.UUID
    score: Literal[0, 1]
    comment: str = Field("", max_length=2000)


def ms(start: float, end: float) -> float:
    return round((end - start) * 1000, 1)


@traceable(name="rag_query", process_inputs=lambda i: {k: i[k] for k in ("tenant", "question", "history")})
async def pipeline(state, tenant: str, question: str, history: list[dict]) -> dict:
    retrieve.aux_tokens.set(helper_tokens := [])
    t0 = time.perf_counter()
    standalone = await retrieve.condense(state.openai, history, question) if history else question
    chunks, top_similarity = await retrieve.search(state.pool, state.openai, tenant, standalone)
    t1 = time.perf_counter()
    result = await generate.answer(state.openai, standalone, chunks, top_similarity)
    t2 = time.perf_counter()
    if helper_tokens:  # rewrite and rerank calls are billed too, so they count toward the caps
        result["usage"] = {**(result["usage"] or {"prompt_tokens": 0, "completion_tokens": 0}),
                           "helper_tokens": sum(helper_tokens)}
    latency = {"retrieval": ms(t0, t1), "generation": ms(t1, t2), "total": ms(t0, t2)}
    return {**result, "question": standalone, "top_similarity": round(top_similarity, 4), "latency_ms": latency}


@app.get("/health")
async def health():
    # Liveness only: a database blip must not get a healthy process restarted or pulled from rotation.
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request):
    await request.app.state.pool.fetchval("SELECT 1")
    return {"status": "ready"}


@app.post("/ingest", status_code=202)
async def ingest_files(request: Request, tenant: Tenant, files: list[UploadFile] = File(...)):
    pool, limit = request.app.state.pool, settings.max_upload_mb * 2**20
    results = []
    for upload in files:
        name = Path(upload.filename or "").name
        data = await upload.read(limit + 1)
        try:
            if not name.lower().endswith(ingest.SUPPORTED):
                raise HTTPException(415, f"Unsupported file type (use {', '.join(ingest.SUPPORTED)})")
            if len(data) > limit:
                raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")
            await charge(pool, tenant, upload_bytes=len(data))
            await pool.execute(ingest.ENQUEUE_SQL, tenant, name, data)
            results.append({"source": name, "status": "queued"})
        except HTTPException as e:
            results.append({"source": name, "error": e.detail})
    return {"documents": results}


@app.get("/documents")
async def list_documents(request: Request, tenant: Tenant):
    rows = await request.app.state.pool.fetch(
        "SELECT source, status, chunks, error, attempts, updated_at FROM documents WHERE tenant = $1 "
        "ORDER BY updated_at DESC",
        tenant,
    )
    return {"documents": [dict(r) for r in rows]}


@app.delete("/documents/{source}", status_code=204)
async def delete_document(source: str, request: Request, tenant: Tenant):
    status = await request.app.state.pool.execute(
        "DELETE FROM documents WHERE tenant = $1 AND source = $2", tenant, source
    )
    if status == "DELETE 0":
        raise HTTPException(404, "Document not found")


@app.post("/query")
async def query(body: Query, request: Request, tenant: Tenant):
    state = request.app.state
    await charge(state.pool, tenant, queries=1)
    run_id = uuid.uuid4()
    history = [turn.model_dump() for turn in body.history]
    result = await pipeline(state, tenant, body.question, history, langsmith_extra={"run_id": run_id})
    traced = tracing_is_enabled()
    writes = []
    if result["usage"]:
        writes.append(state.pool.execute(
            "UPDATE usage_daily SET tokens = tokens + $2 WHERE tenant = $1 AND day = current_date",
            tenant, sum(result["usage"].values()),
        ))
    if traced:  # remember who owns this trace so only they can leave feedback on it
        writes.append(state.pool.execute("INSERT INTO query_traces (trace_id, tenant) VALUES ($1, $2)", run_id, tenant))
    await asyncio.gather(*writes)
    log.info(json.dumps({"event": "query", "tenant": tenant, "top_similarity": result["top_similarity"],
                         "gated": result["gated"], "cited": len(result["citations"]), "rewritten": bool(history),
                         "usage": result["usage"], "latency_ms": result["latency_ms"]}))
    return {**result, "trace_id": str(run_id) if traced else None}


@app.post("/feedback", status_code=204)
async def feedback(body: Feedback, request: Request, tenant: Tenant):
    if not tracing_is_enabled():
        raise HTTPException(409, "Feedback needs LANGSMITH_TRACING=true")
    owned = await request.app.state.pool.fetchval(
        "SELECT 1 FROM query_traces WHERE trace_id = $1 AND tenant = $2 AND created_at > now() - interval '7 days'",
        body.trace_id, tenant,
    )
    if not owned:  # unknown, expired, or another team's answer: don't reveal which
        raise HTTPException(404, "Unknown trace")
    await asyncio.to_thread(
        LangSmith().create_feedback, body.trace_id, key="user_rating", score=body.score,
        comment=body.comment or None, extra={"tenant": tenant},
    )


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
