import asyncpg

from config import settings

# Append-only: never edit, reorder or squash a released migration; add a new one.
# Version N is MIGRATIONS[N-1], and databases record which versions they have
# applied, so renumbering would make them silently skip new migrations.
# Migration 1 uses IF NOT EXISTS because databases created before the migration
# table existed already have those objects.
MIGRATIONS = [
    f"""
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE IF NOT EXISTS documents (
        tenant     TEXT NOT NULL,
        source     TEXT NOT NULL,
        status     TEXT NOT NULL CHECK (status IN ('processing', 'ready', 'failed')),
        chunks     INT  NOT NULL DEFAULT 0,
        error      TEXT,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant, source)
    );
    -- tsv (and its GIN index) served keyword search until BM25 replaced it; migration 4 drops them.
    CREATE TABLE IF NOT EXISTS chunks (
        id          TEXT PRIMARY KEY,
        tenant      TEXT NOT NULL,
        source      TEXT NOT NULL,
        chunk_index INT  NOT NULL,
        page        INT,
        content     TEXT NOT NULL,
        embedding   vector({settings.embed_dim}) NOT NULL,
        tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        FOREIGN KEY (tenant, source) REFERENCES documents (tenant, source) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
    CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);
    CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks (tenant, source, chunk_index);
    """,
    """
    CREATE TABLE tenants (
        name            TEXT PRIMARY KEY,
        daily_queries   INT,   -- NULL = server default from settings
        daily_tokens    INT,
        daily_upload_mb INT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    INSERT INTO tenants (name) SELECT DISTINCT tenant FROM documents;
    ALTER TABLE documents ADD FOREIGN KEY (tenant) REFERENCES tenants ON DELETE CASCADE;

    CREATE TABLE api_keys (
        key_hash   TEXT PRIMARY KEY,   -- sha256 of the key; the key itself is never stored
        key_prefix TEXT NOT NULL,
        tenant     TEXT NOT NULL REFERENCES tenants ON DELETE CASCADE,
        label      TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        revoked_at TIMESTAMPTZ
    );

    CREATE TABLE usage_daily (
        tenant       TEXT NOT NULL REFERENCES tenants ON DELETE CASCADE,
        day          DATE NOT NULL DEFAULT current_date,
        queries      INT NOT NULL DEFAULT 0,
        tokens       INT NOT NULL DEFAULT 0,
        upload_bytes BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant, day)
    );

    -- documents doubles as a durable ingestion queue: the upload is stored in
    -- `file` until a worker finishes it; job_id changes on every re-upload so a
    -- superseded job cannot overwrite the newer one's status.
    ALTER TABLE documents
        ADD COLUMN file BYTEA,
        ADD COLUMN job_id UUID,
        ADD COLUMN attempts INT NOT NULL DEFAULT 0,
        ADD COLUMN locked_at TIMESTAMPTZ,
        DROP CONSTRAINT documents_status_check,
        ADD CONSTRAINT documents_status_check CHECK (status IN ('queued', 'processing', 'ready', 'failed'));
    CREATE INDEX documents_queue_idx ON documents (updated_at) WHERE status IN ('queued', 'processing');
    """,
    """
    -- OCR pages count against a per-tenant daily limit like answer tokens do.
    ALTER TABLE usage_daily ADD COLUMN ocr_pages INT NOT NULL DEFAULT 0;
    ALTER TABLE tenants ADD COLUMN daily_ocr_pages INT;  -- NULL = server default

    -- Which tenant issued each traced query, so feedback can only be left on your own answers.
    CREATE TABLE query_traces (
        trace_id   UUID PRIMARY KEY,
        tenant     TEXT NOT NULL REFERENCES tenants ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX query_traces_created_idx ON query_traces (created_at);
    """,
    """
    -- Keyword search moved to an in-process BM25 index (retrieve.py); the tsvector
    -- column and its GIN index (dropped with it) are no longer read.
    ALTER TABLE chunks DROP COLUMN tsv;
    """,
    """
    -- Which embedding model produced each vector. Vectors from different models are not
    -- comparable, so dense search only uses rows from the current EMBED_MODEL; existing rows
    -- came from Gemini and are brought over with `python admin.py reembed`.
    ALTER TABLE chunks ADD COLUMN embed_model TEXT NOT NULL DEFAULT 'gemini-embedding-001';
    ALTER TABLE chunks ALTER COLUMN embed_model DROP DEFAULT;
    """,
]


async def create_pool() -> asyncpg.Pool:
    async def use_schema(conn: asyncpg.Connection) -> None:
        await conn.execute(f"SET search_path TO {settings.db_schema}, public, extensions")

    # statement_cache_size=0: Supabase's transaction-mode pooler cannot route
    # named prepared statements back to the backend that prepared them.
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        statement_cache_size=0,
        command_timeout=60,
        # `setup` runs on every acquire: the pool's RESET ALL on release would undo a one-off SET.
        setup=use_schema if settings.db_schema != "public" else None,
    )
    try:
        async with pool.acquire() as conn, conn.transaction():
            # Serialise migrations so several processes booting at once don't race.
            await conn.execute("SELECT pg_advisory_xact_lock(727274)")
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {settings.db_schema}")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
            for version, sql in enumerate(MIGRATIONS, 1):
                if version not in applied:
                    await conn.execute(sql)
                    await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
            vector_version = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            # For pgvector, atttypmod holds the declared dimension.
            dim = await conn.fetchval(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
            )
            # A database whose recorded history doesn't match the code would silently skip migrations.
            unknown = applied - set(range(1, len(MIGRATIONS) + 1))
        if unknown:
            raise RuntimeError(f"database has migrations {sorted(unknown)} that this code doesn't know about")
        if tuple(map(int, vector_version.split(".")[:2])) < (0, 8):
            raise RuntimeError(f"pgvector {vector_version} found; 0.8+ needed (run: ALTER EXTENSION vector UPDATE)")
        if dim != settings.embed_dim:
            raise RuntimeError(f"chunks.embedding is vector({dim}) but EMBED_DIM={settings.embed_dim}")
    except BaseException:
        await pool.close()
        raise
    return pool


def to_vector(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.7g}" for v in values) + "]"
