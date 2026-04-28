# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.11

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-dev .

# ── Stage 2: development (hot-reload, dev deps) ───────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS development

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

COPY src/ ./src/

EXPOSE 8000
CMD ["uvicorn", "anime_rag.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── Stage 3: production (non-root, minimal) ───────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS production

# Non-root user — M9 hardens this further
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ ./src/

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "anime_rag.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
