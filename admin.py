"""Manage tenants, API keys, limits and usage. Changes apply within 60 s, no restart.

    python admin.py create-key acme --label "web app"
    python admin.py list-keys
    python admin.py revoke-key rag_AbCd12
    python admin.py set-limits acme --queries 1000 --tokens 500000 --upload-mb 500 --ocr-pages 1000   (-1 = default)
    python admin.py usage --days 7
    python admin.py delete-tenant acme --yes      (deletes all its documents, keys and usage)
    python admin.py reembed                       (re-embed chunks made with another EMBED_MODEL)
"""
import argparse
import asyncio
import hashlib
import secrets

import asyncpg
from openai import AsyncOpenAI

import db
import ingest
from config import settings


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def reembed(pool: asyncpg.Pool, llm: AsyncOpenAI, batch: int = 500) -> int:
    """Re-embed stored chunk text made with another model; no original files needed."""
    done = 0
    while rows := await pool.fetch(
        "SELECT id, content FROM chunks WHERE embed_model <> $1 ORDER BY id LIMIT $2", settings.embed_model, batch
    ):
        vectors = await ingest.embed(llm, [r["content"] for r in rows])
        await pool.executemany(
            "UPDATE chunks SET embedding = $2::text::vector, embed_model = $3, updated_at = now() WHERE id = $1",
            [(r["id"], db.to_vector(v), settings.embed_model) for r, v in zip(rows, vectors)],
        )
        done += len(rows)
        print(f"re-embedded {done} chunks")
    return done


async def create_key(pool: asyncpg.Pool, tenant: str, label: str = "") -> str:
    key = "rag_" + secrets.token_urlsafe(32)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO tenants (name) VALUES ($1) ON CONFLICT DO NOTHING", tenant)
        await conn.execute(
            "INSERT INTO api_keys (key_hash, key_prefix, tenant, label) VALUES ($1, $2, $3, $4)",
            hash_key(key), key[:10], tenant, label,
        )
    return key


async def main(args: argparse.Namespace) -> None:
    pool = await db.create_pool()
    try:
        if args.cmd == "create-key":
            key = await create_key(pool, args.tenant, args.label)
            print(f"API key for '{args.tenant}' (shown once, store it now):\n{key}")
        elif args.cmd == "list-keys":
            rows = await pool.fetch("SELECT key_prefix, tenant, label, created_at, revoked_at FROM api_keys ORDER BY created_at")
            for r in rows:
                state = f"revoked {r['revoked_at']:%Y-%m-%d}" if r["revoked_at"] else "active"
                print(f"{r['key_prefix']}…  {r['tenant']:<20} {state:<18} {r['created_at']:%Y-%m-%d}  {r['label']}")
        elif args.cmd == "revoke-key":
            status = await pool.execute(
                "UPDATE api_keys SET revoked_at = now() WHERE key_prefix = $1 AND revoked_at IS NULL", args.prefix[:10]
            )
            print("revoked" if status != "UPDATE 0" else "no active key with that prefix")
        elif args.cmd == "set-limits":
            given = (args.queries, args.tokens, args.upload_mb, args.ocr_pages)
            params = [x for v in given for x in (v is not None, None if v == -1 else v)]
            status = await pool.execute(
                "UPDATE tenants SET daily_queries = CASE WHEN $2 THEN $3 ELSE daily_queries END, "
                "daily_tokens = CASE WHEN $4 THEN $5 ELSE daily_tokens END, "
                "daily_upload_mb = CASE WHEN $6 THEN $7 ELSE daily_upload_mb END, "
                "daily_ocr_pages = CASE WHEN $8 THEN $9 ELSE daily_ocr_pages END WHERE name = $1",
                args.tenant, *params,
            )
            print("updated" if status != "UPDATE 0" else "unknown tenant")
        elif args.cmd == "usage":
            rows = await pool.fetch(
                "SELECT day, tenant, queries, tokens, upload_bytes, ocr_pages FROM usage_daily "
                "WHERE day > current_date - $1::int ORDER BY day DESC, tokens DESC", args.days,
            )
            print(f"{'day':<12}{'tenant':<20}{'queries':>8}{'tokens':>10}{'upload MB':>11}{'OCR pages':>11}")
            for r in rows:
                print(f"{r['day']!s:<12}{r['tenant']:<20}{r['queries']:>8}{r['tokens']:>10}"
                      f"{r['upload_bytes'] / 2**20:>11.1f}{r['ocr_pages']:>11}")
        elif args.cmd == "reembed":
            llm = ingest.background_llm()
            try:
                print(f"done: {await reembed(pool, llm)} chunks now use {settings.embed_model}")
            finally:
                await llm.close()
        elif args.cmd == "delete-tenant":
            if not args.yes:
                raise SystemExit("refusing without --yes: this deletes every document, key and usage row for the tenant")
            status = await pool.execute("DELETE FROM tenants WHERE name = $1", args.tenant)
            print("deleted" if status != "DELETE 0" else "unknown tenant")
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-key")
    p.add_argument("tenant")
    p.add_argument("--label", default="")
    sub.add_parser("list-keys")
    sub.add_parser("revoke-key").add_argument("prefix")
    p = sub.add_parser("set-limits")
    p.add_argument("tenant")
    for flag in ("--queries", "--tokens", "--upload-mb", "--ocr-pages"):
        p.add_argument(flag, type=int)
    sub.add_parser("usage").add_argument("--days", type=int, default=7)
    sub.add_parser("reembed")
    p = sub.add_parser("delete-tenant")
    p.add_argument("tenant")
    p.add_argument("--yes", action="store_true")
    asyncio.run(main(parser.parse_args()))
