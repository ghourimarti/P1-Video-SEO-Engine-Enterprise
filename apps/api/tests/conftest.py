import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from anime_rag.main import app
from anime_rag.core.settings import get_settings, Settings


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return get_settings()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def async_client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
