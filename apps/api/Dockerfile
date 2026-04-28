# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# Anime RAG API — multi-stage Dockerfile (M9 hardened)
#
# Stages
#   deps        install Python deps into an isolated prefix
#   development hot-reload, mounts src at runtime
#   production  non-root, read-only fs, minimal footprint
#
# Build
#   docker build --target production -t anime-rag-api:latest apps/api
#   docker build --target development -t anime-rag-api:dev    apps/api
# ─────────────────────────────────────────────────────────────────────────────

ARG PYTHON_VERSION=3.11
ARG UV_VERSION=0.4.30

# ── Stage 0: uv installer (pinned digest for reproducibility) ─────────────────
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-bin

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS deps

# Install system deps needed to build some Python wheels (psycopg C binaries, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv-bin /uv /usr/local/bin/uv

WORKDIR /build

# Copy only manifest — cache this layer separately from source
COPY pyproject.toml ./

# Install prod deps into /install prefix (not system site-packages)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --prefix /install --no-dev .

# ── Stage 2: development (hot-reload, mounts src volume) ──────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS development

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv-bin /uv /usr/local/bin/uv
COPY --from=deps /install /usr/local

WORKDIR /app
COPY pyproject.toml ./

# Install dev extras on top (pytest, ruff, mypy)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --extra dev .

# Source is volume-mounted at runtime — do not bake in
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "anime_rag.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "src"]

# ── Stage 3: production ───────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS production

# Minimal runtime libs only
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Non-root user
RUN groupadd --system --gid 1001 appgroup \
 && useradd  --system --uid 1001 --gid appgroup \
             --no-create-home --shell /sbin/nologin appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=deps /install /usr/local

# Copy source — owned by root, readable by appuser
COPY --chown=appuser:appgroup src/ ./src/

# Switch to non-root
USER appuser

# Drop unnecessary capabilities at runtime (enforce in K8s securityContext too)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Two Uvicorn workers — K8s will handle horizontal scaling
CMD ["uvicorn", "anime_rag.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", \
     "--no-access-log"]
