"""FastAPI application entry point."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_openai import OpenAIEmbeddings
from prometheus_client import make_asgi_app
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from anime_rag.core.settings import get_settings
from anime_rag.db.pool import create_pool, close_pool
from anime_rag.rag.pipeline import RAGPipeline
from anime_rag.routers import health, recommend

log = structlog.get_logger(__name__)
settings = get_settings()

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", environment=settings.environment)

    # ── DB pool ───────────────────────────────────────────────────────────────
    app.state.db_pool = await create_pool(settings)

    # ── Embedder (shared across requests — thread-safe) ───────────────────────
    app.state.embedder = OpenAIEmbeddings(
        model=settings.embedding_model,
        openai_api_key=settings.openai_api_key or None,
    )

    # ── RAG pipeline (compiled LangGraph graph) ───────────────────────────────
    app.state.pipeline = RAGPipeline(
        pool=app.state.db_pool,
        embedder=app.state.embedder,
        settings=settings,
    )

    log.info("startup_complete")
    yield

    # ── Cleanup ───────────────────────────────────────────────────────────────
    await close_pool(app.state.db_pool)
    log.info("shutdown_complete")


app = FastAPI(
    title="Anime RAG API",
    description="Production-grade RAG for anime recommendations.",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Prometheus /metrics ───────────────────────────────────────────────────────
app.mount("/metrics", make_asgi_app())

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router, tags=["ops"])
app.include_router(recommend.router, prefix=settings.api_v1_prefix, tags=["recommend"])
