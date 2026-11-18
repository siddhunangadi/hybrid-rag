"""Ingestion pipeline and durable queue worker. Run standalone with `python ingest.py`."""
import asyncio
import hashlib
import io
import json
import logging
import re
import signal
import sys
import time

import asyncpg
from openai import AsyncOpenAI

from config import settings
from db import create_pool, to_vector

log = logging.getLogger("rag.ingest")

SUPPORTED = (".pdf", ".txt", ".md")
SEPARATORS = ("\n\n", "\n", ". ", " ", "")
HEADING = re.compile(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.M)
EMBED_BATCH = 100
EMBED_CONCURRENCY = 4
OCR_PAGES_PER_CALL = 10   # pages rendered per sandboxed child process
OCR_CONCURRENCY = 4
OCR_WIDTH_PX = 1024       # high-detail page images; low detail misses small print
MAX_ATTEMPTS = 3
PDF_PARSE_TIMEOUT_S = 120
MAX_TEXT_CHARS = 5_000_000
HOUSEKEEPING_S = 3600     # prune expired feedback-ownership rows
QUEUE_REPORT_S = 60       # log queue depth for alerting / worker autoscaling
last_housekeeping = 0.0
last_queue_report = 0.0

QUEUE_DEPTH_SQL = """
SELECT count(*) AS queued,
       coalesce(extract(epoch FROM now() - min(updated_at)), 0)::int AS oldest_age_s
FROM documents WHERE status IN ('queued', 'processing')
"""

# PDFs are untrusted: a crafted file (decompression bomb, deeply nested objects) can
# exhaust memory or CPU inside pypdf. They are parsed in a child process with a
# memory cap (enforced on Linux, i.e. in Docker) and killed after a timeout, so the
# worst case is one failed document rather than a dead worker. A thread would not
# do: it cannot be killed, so a stuck parse would keep eating the worker's memory.
PDF_CHILD = """
import io, json, resource, sys
max_pages, max_chars, mem = (int(a) for a in sys.argv[1:4])
try:
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
except (ValueError, OSError):
    pass  # not enforceable on every OS (e.g. macOS); the timeout still applies
from pypdf import PdfReader
reader = PdfReader(io.BytesIO(sys.stdin.buffer.read()))
if len(reader.pages) > max_pages:
    print(json.dumps({"error": f"PDF has {len(reader.pages)} pages; the limit is {max_pages}"}))
    sys.exit()
pages, total = [], 0
for n, page in enumerate(reader.pages, 1):
    text = page.extract_text() or ""
    total += len(text)
    if total > max_chars:
        print(json.dumps({"error": "PDF contains too much text"}))
        sys.exit()
    pages.append([n, text])
print(json.dumps({"pages": pages}))
"""

OCR_CHARGE_SQL = """
WITH used AS (
    INSERT INTO usage_daily (tenant, ocr_pages) VALUES ($1, $2)
    ON CONFLICT (tenant, day) DO UPDATE SET ocr_pages = usage_daily.ocr_pages + EXCLUDED.ocr_pages
    RETURNING ocr_pages
)
SELECT used.ocr_pages, t.daily_ocr_pages,
       (SELECT coalesce(sum(ocr_pages), 0) FROM usage_daily WHERE day = current_date) + $2 AS global_pages
FROM used JOIN tenants t ON t.name = $1
"""

# Renders a slice of pages to grayscale PNGs (PDFium), inside the same sandbox as parsing.
RENDER_CHILD = """
import base64, io, json, resource, sys
first, count, width, mem = (int(a) for a in sys.argv[1:5])
try:
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
except (ValueError, OSError):
    pass
import pypdfium2 as pdfium
doc = pdfium.PdfDocument(sys.stdin.buffer.read())
images = []
for i in range(first, min(first + count, len(doc))):
    page = doc[i]
    buf = io.BytesIO()
    page.render(scale=width / page.get_width()).to_pil().convert("L").save(buf, "PNG", optimize=True)
    images.append(base64.b64encode(buf.getvalue()).decode())
print(json.dumps({"pages": images}))
"""

OCR_PROMPT = (
    "You are an OCR engine. Transcribe this scanned page verbatim into Markdown: every heading, sentence, list item, "
    "number and table cell, in reading order, with tables as Markdown tables. Do not summarize, shorten, paraphrase, "
    "skip or add anything. Output only the transcription."
)

ENQUEUE_SQL = """
INSERT INTO documents (tenant, source, status, file, job_id, attempts, error, updated_at)
VALUES ($1, $2, 'queued', $3, gen_random_uuid(), 0, NULL, now())
ON CONFLICT (tenant, source) DO UPDATE SET
    status = 'queued', file = EXCLUDED.file, job_id = EXCLUDED.job_id, attempts = 0, error = NULL, updated_at = now()
"""

CLAIM_SQL = """
UPDATE documents d SET status = 'processing', locked_at = now(), attempts = d.attempts + 1
FROM (
    SELECT tenant, source FROM documents
    WHERE status = 'queued' OR (status = 'processing' AND locked_at < now() - interval '10 minutes')
    ORDER BY updated_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
) next
WHERE d.tenant = next.tenant AND d.source = next.source
RETURNING d.tenant, d.source, d.file, d.job_id, d.attempts
"""

FINISH_SQL = """
UPDATE documents SET status = $4, chunks = COALESCE($5, chunks), error = $6, locked_at = NULL, updated_at = now(),
    file = CASE WHEN $4 = 'queued' THEN file END
WHERE tenant = $1 AND source = $2 AND job_id = $3
"""

UPSERT = """
INSERT INTO chunks (id, tenant, source, chunk_index, page, content, embedding, embed_model)
VALUES ($1, $2, $3, $4, $5, $6, $7::text::vector, $8)
ON CONFLICT (id) DO UPDATE SET
    page = EXCLUDED.page,
    content = EXCLUDED.content,
    embedding = EXCLUDED.embedding,
    embed_model = EXCLUDED.embed_model,
    updated_at = now()
"""


def background_llm() -> AsyncOpenAI:
    # Background work (embedding uploads, OCR) can afford long timeouts and patient retries.
    return AsyncOpenAI(api_key=settings.openai_api_key, timeout=300, max_retries=5)


async def parse(filename: str, data: bytes) -> list[tuple[int | None, str]]:
    """Return (page_number, text) pairs; page is None for plain-text formats."""
    if filename.lower().endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="replace")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError("File contains too much text")
        return [(None, text)]
    if not filename.lower().endswith(".pdf"):
        raise ValueError(f"Unsupported file type (use {', '.join(SUPPORTED)})")
    result = await sandboxed(PDF_CHILD, data, settings.max_pdf_pages, MAX_TEXT_CHARS)
    return [(n, text) for n, text in result["pages"]]


async def sandboxed(script: str, data: bytes, *args: int) -> dict:
    """Run a PDF-handling script in a memory-capped child process, killed after PDF_PARSE_TIMEOUT_S."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-c", script, *map(str, args), str(settings.pdf_parse_memory_mb * 2**20),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(data), PDF_PARSE_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise ValueError(f"PDF took longer than {PDF_PARSE_TIMEOUT_S} s to parse") from None
    if proc.returncode != 0:
        reason = (err.decode(errors="replace").strip().splitlines() or ["parser crashed"])[-1]
        raise ValueError(f"Unreadable PDF: {reason[:200]}")
    result = json.loads(out)
    if "error" in result:
        raise ValueError(result["error"])
    return result


async def charge_ocr(pool: asyncpg.Pool, tenant: str, pages: int) -> None:
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(OCR_CHARGE_SQL, tenant, pages)
        limit = row["daily_ocr_pages"] if row["daily_ocr_pages"] is not None else settings.daily_ocr_pages
        if row["ocr_pages"] > limit:  # raising here rolls the charge back
            raise ValueError(f"Daily OCR limit of {limit} pages reached for this team; try again tomorrow")
        if row["global_pages"] > settings.global_daily_ocr_pages:
            raise ValueError("Service-wide daily OCR limit reached; try again tomorrow")


def needs_ocr(pages: list[tuple[int | None, str]]) -> bool:
    if settings.pdf_ocr != "auto":
        return settings.pdf_ocr == "always"
    return sum(len(text.strip()) < 50 for _, text in pages) > len(pages) / 2


async def ocr_pdf(llm: AsyncOpenAI, data: bytes, page_count: int) -> tuple[list[tuple[int, str]], int]:
    """Transcribe a scanned PDF page by page from high-detail images; returns (pages, tokens spent).
    gpt-4o-mini bills a high-detail page image at roughly 37k tokens (~$0.006), hence the page caps."""
    sem = asyncio.Semaphore(OCR_CONCURRENCY)

    async def transcribe(number: int, png: str) -> tuple[tuple[int, str], int]:
        async with sem:
            resp = await llm.chat.completions.create(
                model=settings.ocr_model,
                temperature=0,
                messages=[
                    {"role": "system", "content": OCR_PROMPT},
                    {"role": "user", "content": [{"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{png}", "detail": "high"}}]},
                ],
            )
        return (number, (resp.choices[0].message.content or "").strip()), resp.usage.total_tokens

    results = []
    for first in range(0, page_count, OCR_PAGES_PER_CALL):  # render in slices to bound memory
        images = (await sandboxed(RENDER_CHILD, data, first, OCR_PAGES_PER_CALL, OCR_WIDTH_PX))["pages"]
        results += await asyncio.gather(*(transcribe(first + i + 1, png) for i, png in enumerate(images)))
    return [page for page, _ in results], sum(tokens for _, tokens in results)


def split_text(text: str, size: int, overlap: int) -> list[str]:
    def atoms(s: str, seps: tuple[str, ...]) -> list[str]:
        if len(s) <= size:
            return [s]
        sep, rest = seps[0], seps[1:]
        if not sep:
            return [s[i : i + size] for i in range(0, len(s), size)]
        parts = s.split(sep)
        return [
            a
            for i, p in enumerate(parts)
            for a in atoms(p + sep if i < len(parts) - 1 else p, rest)
        ]

    chunks, window, cur_len = [], [], 0
    for atom in atoms(text, SEPARATORS):
        if window and cur_len + len(atom) > size:
            chunks.append("".join(window).strip())
            while window and (cur_len > overlap or cur_len + len(atom) > size):
                cur_len -= len(window.pop(0))
        window.append(atom)
        cur_len += len(atom)
    if window:
        chunks.append("".join(window).strip())
    return [c for c in chunks if c]


def document_title(filename: str, pages: list[tuple[int | None, str]]) -> str:
    text = next((t for _, t in pages if t.strip()), "")
    heading = HEADING.search(text)
    first_line = next((line.strip(" #*") for line in text.splitlines() if line.strip(" #*")), "")
    return (heading.group(1) if heading else first_line)[:120] or filename


def with_context(title: str, text: str, chunks: list[str]) -> list[str]:
    headings = [(m.start(), m.group(1).strip(" *")) for m in HEADING.finditer(text)]
    out, pos = [], 0
    for chunk in chunks:
        found = text.find(chunk[:80], pos)
        pos = found if found >= 0 else pos
        section = next((h for start, h in reversed(headings) if start <= pos), None)
        out.append(f"[{title}{f' > {section}' if section and section != title else ''}]\n{chunk}")
    return out


async def embed(llm: AsyncOpenAI, texts: list[str]) -> list[list[float]]:
    """OpenAI embeddings, shortened to EMBED_DIM (text-embedding-3 models support this natively)."""
    sem = asyncio.Semaphore(EMBED_CONCURRENCY)

    async def run(batch: list[str]) -> list[list[float]]:
        async with sem:
            resp = await llm.embeddings.create(model=settings.embed_model, input=batch, dimensions=settings.embed_dim)
            return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]

    batches = [texts[i : i + EMBED_BATCH] for i in range(0, len(texts), EMBED_BATCH)]
    results = await asyncio.gather(*(run(b) for b in batches))
    return [vec for batch in results for vec in batch]


async def ingest_file(pool: asyncpg.Pool, llm: AsyncOpenAI, tenant: str, filename: str, data: bytes) -> int:
    pages = await parse(filename, data)
    if filename.lower().endswith(".pdf") and needs_ocr(pages):
        # OCR is metered by page (team and service-wide caps) rather than against the query
        # token budget: one scanned page costs about as many tokens as ~25 answers.
        await charge_ocr(pool, tenant, len(pages))
        pages, tokens = await ocr_pdf(llm, data, len(pages))
        log.info("ocr tenant=%s source=%s pages=%d tokens=%d", tenant, filename, len(pages), tokens)
    title = document_title(filename, pages)
    pieces = [
        (page, c)
        for page, text in pages
        for c in with_context(title, text, split_text(text, settings.chunk_size, settings.chunk_overlap))
    ]
    if not pieces:
        raise ValueError("No extractable text")

    ids = [hashlib.sha256(f"{tenant}\0{filename}\0{i}".encode()).hexdigest() for i in range(len(pieces))]
    rows = await pool.fetch(
        "SELECT id, content, embed_model FROM chunks WHERE tenant = $1 AND source = $2", tenant, filename
    )
    # Unchanged text embedded with the current model is reused; anything else is (re)embedded.
    current = {r["id"] for r in rows if r["embed_model"] == settings.embed_model}
    existing = {r["id"]: r["content"] for r in rows}
    changed = [i for i, (_, c) in enumerate(pieces) if existing.get(ids[i]) != c or ids[i] not in current]
    vectors = await embed(llm, [pieces[i][1] for i in changed])

    async with pool.acquire() as conn, conn.transaction():
        await conn.executemany(
            UPSERT,
            [
                (ids[i], tenant, filename, i, pieces[i][0], pieces[i][1], to_vector(v), settings.embed_model)
                for i, v in zip(changed, vectors)
            ],
        )
        await conn.execute(
            "DELETE FROM chunks WHERE tenant = $1 AND source = $2 AND chunk_index >= $3", tenant, filename, len(pieces)
        )
    log.info("ingested tenant=%s source=%s chunks=%d embedded=%d", tenant, filename, len(pieces), len(changed))
    return len(pieces)


async def process(pool: asyncpg.Pool, llm: AsyncOpenAI, job: asyncpg.Record) -> None:
    key = (job["tenant"], job["source"], job["job_id"])
    try:
        if job["attempts"] > MAX_ATTEMPTS:
            raise ValueError(f"Gave up after {MAX_ATTEMPTS} attempts")
        result = ("ready", await ingest_file(pool, llm, job["tenant"], job["source"], job["file"]), None)
    except asyncio.CancelledError:
        await asyncio.shield(pool.execute(FINISH_SQL, *key, "queued", None, None))
        raise
    except ValueError as e:
        result = ("failed", None, str(e)[:500])
    except Exception as e:
        log.exception("ingest failed tenant=%s source=%s attempt=%d", job["tenant"], job["source"], job["attempts"])
        result = ("queued" if job["attempts"] < MAX_ATTEMPTS else "failed", None, f"{type(e).__name__}: {e}"[:500])
    await pool.execute(FINISH_SQL, *key, *result)


async def housekeeping(pool: asyncpg.Pool) -> None:
    # Two independent timers: a cheap queue-depth report every minute, and the hourly prune.
    global last_housekeeping, last_queue_report
    now = time.monotonic()
    if now - last_queue_report > QUEUE_REPORT_S:
        last_queue_report = now
        row = await pool.fetchrow(QUEUE_DEPTH_SQL)
        # One raw JSON line a minute on stdout (no log prefix), so a CloudWatch JSON metric filter can parse it.
        print(json.dumps({"event": "queue", "queued": row["queued"], "oldest_age_s": row["oldest_age_s"]}), flush=True)
    if now - last_housekeeping > HOUSEKEEPING_S:
        last_housekeeping = now
        # Feedback is only accepted for a week, so older trace ownership rows can go.
        await pool.execute("DELETE FROM query_traces WHERE created_at < now() - interval '7 days'")


async def worker(pool: asyncpg.Pool, llm: AsyncOpenAI, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await housekeeping(pool)  # time-gated; runs between jobs too, so a backlog keeps being reported
            job = await pool.fetchrow(CLAIM_SQL)
            if job:
                await process(pool, llm, job)
                continue
        except Exception:
            log.exception("worker loop error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            pass


async def run_workers() -> None:
    pool, llm, stop = await create_pool(), background_llm(), asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    log.info("worker started (concurrency=%d)", settings.worker_concurrency)
    try:
        await asyncio.gather(*(worker(pool, llm, stop) for _ in range(settings.worker_concurrency)))
    finally:
        await llm.close()
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run_workers())
