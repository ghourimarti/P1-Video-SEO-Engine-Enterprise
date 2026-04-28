"""Shared test fixtures.

Unit tests mock the DB pool and pipeline so they run without infrastructure.
Integration tests (tests/integration/) require a running Postgres + Redis stack.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from anime_rag.core.settings import Settings


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return Settings()


# ── Unit-test client (no real DB/Redis) ───────────────────────────────────────

@pytest.fixture
def client():
    """TestClient with DB pool and pipeline mocked out."""
    # Patch create_pool so lifespan doesn't try to open a real connection
    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=AsyncMock(
            execute=AsyncMock(),
            fetchall=AsyncMock(return_value=[]),
        )),
        __aexit__=AsyncMock(return_value=False),
    ))
    mock_pool.close = AsyncMock()
    mock_pool.open = AsyncMock()

    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value={
        "answer": "Test answer",
        "sources": [],
        "model_used": "mock",
        "input_tokens": 10,
        "output_tokens": 20,
        "cost_usd": 0.0,
        "cached": False,
        "error": None,
    })

    with (
        patch("anime_rag.db.pool.AsyncConnectionPool") as mock_pool_cls,
        patch("anime_rag.main.create_pool", return_value=mock_pool),
        patch("anime_rag.main.RAGPipeline", return_value=mock_pipeline),
        patch("anime_rag.main.OpenAIEmbeddings", return_value=MagicMock()),
    ):
        from anime_rag.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ── Async client for integration tests ───────────────────────────────────────

@pytest.fixture
async def async_client():
    """Async client — used in integration tests that need a real stack."""
    from anime_rag.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
