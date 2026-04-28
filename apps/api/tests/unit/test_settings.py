"""Unit tests for pydantic settings — no network, no DB."""

import os
import pytest
from anime_rag.core.settings import Settings


def test_defaults_without_env(monkeypatch):
    # Clear all relevant env vars to test defaults
    for key in ["POSTGRES_HOST", "API_PORT", "ENVIRONMENT", "LOG_LEVEL"]:
        monkeypatch.delenv(key, raising=False)

    s = Settings()
    assert s.environment == "development"
    assert s.api_port == 8000
    assert s.postgres_host == "localhost"
    assert s.retrieval_top_k == 20
    assert s.rerank_top_n == 5


def test_database_url_format():
    s = Settings(
        postgres_host="db",
        postgres_port=5432,
        postgres_db="mydb",
        postgres_user="user",
        postgres_password="pass",
    )
    assert s.database_url == "postgresql+psycopg://user:pass@db:5432/mydb"


def test_env_override(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_PORT", "9000")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "60")

    s = Settings()
    assert s.environment == "production"
    assert s.api_port == 9000
    assert s.rate_limit_per_minute == 60


def test_model_fields_present():
    s = Settings()
    assert hasattr(s, "default_model")
    assert hasattr(s, "cheap_model")
    assert hasattr(s, "fallback_model")
    assert hasattr(s, "embedding_model")
