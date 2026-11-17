import asyncio
import json
import logging
import time
from collections import OrderedDict, defaultdict
from contextvars import ContextVar

import asyncpg
import bm25s
import Stemmer
from langsmith import traceable
from openai import AsyncOpenAI

from config import settings
from db import to_vector
from ingest import embed

log = logging.getLogger("rag.retrieve")

RRF_K = 60
RERANK_POOL = 15
AUX_COOLDOWN_S = 30
aux_paused_until = 0.0
# Tokens spent by helper calls during the current request, so they count against spending caps.
aux_tokens: ContextVar[list[int] | None] = ContextVar("aux_tokens", default=None)

DENSE_SQL = """
SELECT id, source, page, chunk_index, content, 1 - (embedding <=> $1::text::vector) AS similarity
FROM chunks
WHERE tenant = $3 AND embed_model = $4  -- vectors from another model aren't comparable
ORDER BY embedding <=> $1::text::vector
LIMIT $2
"""

# Keyword search is BM25 (bm25s) over an in-memory index per tenant. Unlike Postgres
# ts_rank it weights terms by rarity (IDF), so an identifier such as "E142" outranks
# common words like "Kestrel". Each process rebuilds a tenant's index when that
# tenant's corpus version (chunk count + newest update) changes.
VERSION_SQL = "SELECT count(*) AS n, max(updated_at) AS latest FROM chunks WHERE tenant = $1"
CORPUS_SQL = "SELECT id, source, page, chunk_index, content FROM chunks WHERE tenant = $1 ORDER BY id"
MAX_CACHED_TENANTS = 50
STEMMER = Stemmer.Stemmer("english")
bm25_cache: OrderedDict[str, tuple[tuple, bm25s.BM25 | None, list[dict]]] = OrderedDict()
bm25_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def bm25_tokens(texts: list[str], as_ids: bool = True):
    return bm25s.tokenize(texts, stopwords="en", stemmer=STEMMER, show_progress=False, return_ids=as_ids)


def build_bm25(rows: list[dict]) -> bm25s.BM25 | None:
    if not rows:
        return None
    index = bm25s.BM25()
    index.index(bm25_tokens([r["content"] for r in rows]), show_progress=False)
    return index


async def bm25_index(pool: asyncpg.Pool, tenant: str) -> tuple[bm25s.BM25 | None, list[dict]]:
    version = tuple(await pool.fetchrow(VERSION_SQL, tenant))
    async with bm25_locks[tenant]:  # one rebuild per tenant at a time; others wait and reuse it
        cached = bm25_cache.get(tenant)
        if not cached or cached[0] != version:
            rows = [dict(r) for r in await pool.fetch(CORPUS_SQL, tenant)]
            cached = (version, await asyncio.to_thread(build_bm25, rows), rows)
            bm25_cache[tenant] = cached
        bm25_cache.move_to_end(tenant)
        while len(bm25_cache) > MAX_CACHED_TENANTS:
            bm25_cache.popitem(last=False)
    return cached[1], cached[2]


async def keyword_search(pool: asyncpg.Pool, tenant: str, question: str) -> list[dict]:
    index, rows = await bm25_index(pool, tenant)
    if index is None:
        return []
    docs, scores = index.retrieve(
        bm25_tokens([question], as_ids=False), k=min(settings.candidates_k, len(rows)), show_progress=False
    )
    return [{**rows[i], "lexical": float(score)} for i, score in zip(docs[0], scores[0]) if score > 0]


REWRITE_PROMPT = (
    "Rewrite the user's latest question as a single standalone question, resolving pronouns and references "
    "from the conversation. Keep the user's language. Return only the question."
)

RERANK_PROMPT = (
    'Rank the passages by how directly they help answer the question. Reply with JSON {"ranking": [passage '
    "numbers, most useful first]}, listing only passages that are relevant."
)


async def ask_aux(llm: AsyncOpenAI, system: str, contents: str, json_mode: bool = False) -> str | None:
    """Query-time helper call (OpenAI); None means "fall back". After any failure (timeout, rate limit,
    outage) helper calls are skipped for AUX_COOLDOWN_S, so a struggling provider doesn't slow every query."""
    global aux_paused_until
    if time.monotonic() < aux_paused_until:
        return None
    try:
        resp = await asyncio.wait_for(llm.chat.completions.create(
            model=settings.aux_model,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": contents}],
            **({"response_format": {"type": "json_object"}} if json_mode else {}),
        ), settings.aux_timeout_s)
    except Exception as e:  # helpers are enhancements; never fail the query over them
        aux_paused_until = time.monotonic() + AUX_COOLDOWN_S
        log.warning("helper model failed (%s); skipping helper calls for %d s", type(e).__name__, AUX_COOLDOWN_S)
        return None
    if (spent := aux_tokens.get()) is not None:
        spent.append(resp.usage.total_tokens)
    return resp.choices[0].message.content


@traceable(run_type="llm", process_inputs=lambda i: {"history": i["history"], "question": i["question"]})
async def condense(llm: AsyncOpenAI, history: list[dict], question: str) -> str:
    convo = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history[-6:])
    text = await ask_aux(llm, REWRITE_PROMPT, f"Conversation:\n{convo}\n\nLatest question: {question}")
    return (text or "").strip() or question


async def dense_search(pool: asyncpg.Pool, vector: str, tenant: str) -> list:
    async with pool.acquire() as conn, conn.transaction():
        # HNSW filters by tenant *after* the graph walk; without iterative scans
        # (pgvector 0.8+) a small tenant in a large table can get too few rows.
        await conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
        return await conn.fetch(DENSE_SQL, vector, settings.candidates_k, tenant, settings.embed_model)


def fuse(dense: list, sparse: list, top_n: int) -> list[dict]:
    # Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (k + rank(d)).
    # Rank-based, so cosine similarity and BM25 scores never need calibrating against each other.
    fused: dict[str, dict] = {}
    for name, results in (("dense", dense), ("sparse", sparse)):
        for rank, row in enumerate(results, 1):
            hit = fused.setdefault(row["id"], {**dict(row), "score": 0.0, "dense_rank": None, "sparse_rank": None})
            hit["score"] += 1 / (RRF_K + rank)
            hit[f"{name}_rank"] = rank
    return sorted(fused.values(), key=lambda h: h["score"], reverse=True)[:top_n]


async def rerank(llm: AsyncOpenAI, question: str, candidates: list[dict]) -> list[dict]:
    listing = "\n\n".join(f"[{n}] {c['content'][:1200]}" for n, c in enumerate(candidates, 1))
    text = await ask_aux(llm, RERANK_PROMPT, f"Question: {question}\n\nPassages:\n{listing}", json_mode=True)
    try:
        ranking = json.loads(text)["ranking"] if text else []
    except (ValueError, KeyError, TypeError):
        log.warning("reranker returned malformed JSON; keeping RRF order")
        ranking = []
    picked = [candidates[n - 1] for n in dict.fromkeys(ranking) if isinstance(n, int) and 1 <= n <= len(candidates)]
    return picked + [c for c in candidates if c not in picked]


# Traced to LangSmith only when LANGSMITH_TRACING=true; inputs are trimmed so
# connection objects (and the keys inside them) are never serialised.
@traceable(run_type="retriever", process_inputs=lambda i: {"tenant": i["tenant"], "question": i["question"]})
async def search(pool: asyncpg.Pool, llm: AsyncOpenAI, tenant: str, question: str) -> tuple[list[dict], float]:
    async def semantic() -> list:
        [query_vec] = await embed(llm, [question])
        return await dense_search(pool, to_vector(query_vec), tenant)

    # BM25 needs no embedding, so it (and its corpus-version check) overlaps the embedding call.
    dense, sparse = await asyncio.gather(semantic(), keyword_search(pool, tenant, question))
    # Dense rank 1 is the tenant's closest chunk, so its cosine is the upper
    # bound on relevance and drives the confidence gate.
    top_similarity = dense[0]["similarity"] if dense else 0.0
    hits = fuse(dense, sparse, RERANK_POOL if settings.rerank else settings.final_k)
    if settings.rerank and len(hits) > 1:
        hits = await rerank(llm, question, hits)
    return hits[: settings.final_k], top_similarity
