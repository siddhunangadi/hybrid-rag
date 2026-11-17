from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Export .env into os.environ (not just Settings) so SDKs that read env vars
# directly, such as LangSmith tracing, see the same configuration.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    openai_api_key: str
    database_url: str
    db_schema: str = Field("public", pattern=r"^[a-z_][a-z0-9_]*$")

    embed_model: str = "text-embedding-3-small"
    embed_dim: int = Field(768, ge=128, le=2000)  # pgvector HNSW indexes cap at 2000 dims
    # Everything runs on OpenAI: embeddings (embed_model, shortened to embed_dim), answers (chat_model), query-time helpers
    # (aux_model: follow-up rewrite and rerank, abandoned after aux_timeout_s) and background
    # work (ocr_model: scanned-PDF transcription, eval drafts). Query tokens count toward the token
    # caps; OCR is metered by page instead (one scanned page costs about as much as 25 answers).
    chat_model: str = "gpt-4o-mini"
    aux_model: str = "gpt-4o-mini"
    aux_timeout_s: float = 5.0
    ocr_model: str = "gpt-4o-mini"

    chunk_size: int = Field(1000, ge=200, le=6000)
    chunk_overlap: int = Field(150, ge=0)
    candidates_k: int = 20
    final_k: int = 5
    # Calibrated for text-embedding-3-small on the benchmark: filters off-topic questions only;
    # on-topic questions the documents cannot answer are refused by the model itself.
    min_similarity: float = Field(0.30, ge=0, le=1)
    rerank: bool = True  # measured +2-3 pts on the benchmark; costs ~4k extra tokens per query
    pdf_ocr: Literal["auto", "always", "never"] = "auto"

    max_upload_mb: int = 20
    max_pdf_pages: int = 1000
    daily_queries: int = 500
    daily_tokens: int = 300_000
    daily_upload_mb: int = 200
    daily_ocr_pages: int = 50  # scanned pages: ~$0.006 each with gpt-4o-mini at high detail
    # Hard stop across all tenants, to protect the OpenAI balance.
    global_daily_tokens: int = 1_000_000
    global_daily_ocr_pages: int = 100

    run_worker: bool = True
    worker_concurrency: int = 2
    db_pool_min: int = 1
    # Keep (processes x DB_POOL_MAX) under the pooler's client limit: Supabase's
    # session pooler allows 15 on small plans. The transaction pooler allows far more.
    db_pool_max: int = 5


settings = Settings()
