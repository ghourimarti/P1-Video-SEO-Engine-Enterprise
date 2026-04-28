"""FastAPI application entry point — observability wired at startup."""

import os
from contextlib import asynccontextmanager
from typing import Callable

import litellm
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from langchain_openai import OpenAIEmbeddings
from prometheus_client import make_asgi_app
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from anime_rag.cache.service import CacheService
from anime_rag.core.logging import RequestContextMiddleware, setup_logging
from anime_rag.core.settings import get_settings
from anime_rag.core.telemetry import setup_telemetry
from anime_rag.db.pool import create_pool, close_pool
from anime_rag.rag.pipeline import RAGPipeline
from anime_rag.routers import health, recommend
from anime_rag.routers.cost import router as cost_router

settings = get_settings()

# ── Logging must be configured before first log call ─────────────────────────
setup_logging(log_level=settings.log_level, environment=settings.environment)
log = structlog.get_logger(__name__)

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
)


def _setup_langfuse(settings) -> None:
    """Configure LiteLLM → Langfuse callback for automatic LLM tracing."""
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        log.info("langfuse_skipped", reason="keys not configured")
        return
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_HOST"]       = settings.langfuse_host
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]
    log.info("langfuse_configured", host=settings.langfuse_host)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", environment=settings.environment, version="0.5.0")

    # ── OpenTelemetry ─────────────────────────────────────────────────────────
    setup_telemetry(
        app=app,
        service_name=settings.otel_service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
    )

    # ── Langfuse LLM tracing ──────────────────────────────────────────────────
    _setup_langfuse(settings)

    # ── DB pool ───────────────────────────────────────────────────────────────
    app.state.db_pool = await create_pool(settings)

    # ── Redis ─────────────────────────────────────────────────────────────────
    app.state.redis = aioredis.from_url(
        settings.redis_url, encoding="utf-8", decode_responses=True
    )
    try:
        await app.state.redis.ping()
        log.info("redis_connected")
    except Exception as exc:
        log.warning("redis_unavailable", error=str(exc))

    # ── Cache + Embedder + Pipeline ───────────────────────────────────────────
    app.state.cache = CacheService(app.state.redis, settings)
    app.state.embedder = OpenAIEmbeddings(
        model=settings.embedding_model,
        openai_api_key=settings.openai_api_key or None,
    )
    app.state.pipeline = RAGPipeline(
        pool=app.state.db_pool,
        embedder=app.state.embedder,
        cache=app.state.cache,
        settings=settings,
    )

    log.info("startup_complete")
    yield

    await close_pool(app.state.db_pool)
    await app.state.redis.aclose()
    log.info("shutdown_complete")


app = FastAPI(
    title="Anime RAG API",
    version="0.5.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Security headers middleware ────────────────────────────────────────────────
# Applied to every response. Values are safe defaults; tighten CSP in prod.
_SECURITY_HEADERS = {
    "X-Content-Type-Options":  "nosniff",
    "X-Frame-Options":          "DENY",
    "X-XSS-Protection":         "1; mode=block",
    "Referrer-Policy":          "strict-origin-when-cross-origin",
    "Permissions-Policy":       "geolocation=(), microphone=(), camera=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",  # HTTPS only
}


@app.middleware("http")
async def add_security_headers(request: Request, call_next: Callable) -> Response:
    response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        response.headers[header] = value
    return response


# ── Middleware (order matters: outermost first) ───────────────────────────────
app.add_middleware(RequestContextMiddleware)   # structlog request_id binding
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Prometheus /metrics ───────────────────────────────────────────────────────
app.mount("/metrics", make_asgi_app())

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router, tags=["ops"])
app.include_router(recommend.router, prefix=settings.api_v1_prefix, tags=["recommend"])
app.include_router(cost_router, prefix=settings.api_v1_prefix)
