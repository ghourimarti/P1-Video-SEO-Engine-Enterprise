from functools import lru_cache
from typing import Literal

from pydantic import Field, RedisDsn, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_v1_prefix: str = "/api/v1"

    # ── LLM / Routing ────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    cohere_api_key: str = ""

    default_model: str = "claude-sonnet-4-6"
    cheap_model: str = "claude-haiku-4-5-20251001"
    fallback_model: str = "groq/llama-3.1-8b-instant"
    embedding_model: str = "text-embedding-3-large"

    # Token budget (per request)
    max_input_tokens: int = 4096
    max_output_tokens: int = 1024

    # ── Cost controls ─────────────────────────────────────────────────────────
    # Daily USD spend limits (tracked per-user and globally in Redis)
    user_daily_budget_usd: float = 1.00
    global_daily_budget_usd: float = 50.00
    # Word count threshold above which the smarter (default_model) is chosen
    cost_complex_query_words: int = 30

    # ── Database ─────────────────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "anime_rag"
    postgres_user: str = "anime_rag"
    postgres_password: str = "dev_password"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600
    semantic_cache_threshold: float = 0.92

    # ── Auth (Clerk) ──────────────────────────────────────────────────────────
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""
    # JWKS endpoint for JWT verification — set to Clerk's standard URL once you
    # have an account. Leave empty in dev to skip verification.
    clerk_jwks_url: str = ""

    # ── Security ──────────────────────────────────────────────────────────────
    # Presidio PII scrubbing (applies to query + answer)
    pii_scrubbing_enabled: bool = True
    # Guardrail prompt-injection blocking
    guardrails_enabled: bool = True

    # ── Observability ─────────────────────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3001"

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "anime-rag-api"

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_per_minute: int = 30
    rate_limit_burst: int = 10

    # ── Retrieval ─────────────────────────────────────────────────────────────
    retrieval_top_k: int = 20      # candidates before reranking
    rerank_top_n: int = 5          # after Cohere reranker
    rrf_k: int = 60                # RRF constant


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
