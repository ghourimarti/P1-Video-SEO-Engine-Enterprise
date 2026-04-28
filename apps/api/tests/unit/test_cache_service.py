"""Unit tests for CacheService — all Redis calls are mocked."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from anime_rag.cache.service import CacheService, _hash, _cosine
from anime_rag.core.settings import Settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _settings(**overrides) -> Settings:
    defaults = dict(
        cache_ttl_seconds=3600,
        semantic_cache_threshold=0.92,
    )
    return Settings(**{**defaults, **overrides})


def _make_redis(**methods) -> AsyncMock:
    r = AsyncMock()
    for name, val in methods.items():
        setattr(r, name, AsyncMock(return_value=val))
    return r


def _vec(dim: int = 8, val: float = 1.0) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[0] = val
    return v / np.linalg.norm(v)


SAMPLE_RESPONSE = {
    "answer":        "Great show!",
    "sources":       [],
    "model_used":    "claude-sonnet-4-6",
    "input_tokens":  100,
    "output_tokens": 50,
    "cost_usd":      0.002,
}

# ── _hash ─────────────────────────────────────────────────────────────────────

def test_hash_normalises_case():
    assert _hash("Fullmetal") == _hash("fullmetal")


def test_hash_normalises_whitespace():
    assert _hash("  hello  ") == _hash("hello")


def test_hash_length():
    assert len(_hash("anything")) == 16


# ── _cosine ───────────────────────────────────────────────────────────────────

def test_cosine_identical_vecs():
    v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert abs(_cosine(v, v) - 1.0) < 1e-6


def test_cosine_orthogonal_vecs():
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert abs(_cosine(a, b)) < 1e-6


def test_cosine_zero_vec():
    z = np.zeros(3, dtype=np.float32)
    v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert _cosine(z, v) == 0.0


# ── get_exact ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_exact_hit():
    redis = _make_redis(get=json.dumps(SAMPLE_RESPONSE))
    svc = CacheService(redis, _settings())
    result = await svc.get_exact("attack on titan")
    assert result["answer"] == SAMPLE_RESPONSE["answer"]


@pytest.mark.asyncio
async def test_get_exact_miss():
    redis = _make_redis(get=None)
    svc = CacheService(redis, _settings())
    assert await svc.get_exact("naruto") is None


@pytest.mark.asyncio
async def test_get_exact_redis_error_returns_none():
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
    svc = CacheService(redis, _settings())
    assert await svc.get_exact("bleach") is None


# ── get_semantic ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_semantic_hit_above_threshold():
    stored_vec = _vec(8, 1.0)
    query_vec  = _vec(8, 1.0)   # identical → cosine = 1.0 >> 0.92

    h = _hash("some query")
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={h: json.dumps(stored_vec.tolist())})
    redis.hget = AsyncMock(return_value=json.dumps(SAMPLE_RESPONSE))

    svc = CacheService(redis, _settings(semantic_cache_threshold=0.92))
    result = await svc.get_semantic(query_vec)
    assert result is not None
    assert result["answer"] == SAMPLE_RESPONSE["answer"]


@pytest.mark.asyncio
async def test_get_semantic_miss_below_threshold():
    # Orthogonal vectors → cosine = 0.0
    stored_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    query_vec  = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    h = _hash("x")
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={h: json.dumps(stored_vec.tolist())})

    svc = CacheService(redis, _settings(semantic_cache_threshold=0.92))
    assert await svc.get_semantic(query_vec) is None


@pytest.mark.asyncio
async def test_get_semantic_empty_cache():
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    svc = CacheService(redis, _settings())
    assert await svc.get_semantic(_vec()) is None


# ── set_response ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_response_writes_pipeline():
    pipe = AsyncMock()
    pipe.setex = AsyncMock()
    pipe.hset = AsyncMock()
    pipe.execute = AsyncMock(return_value=[True, True, True])

    redis = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipe)

    svc = CacheService(redis, _settings())
    await svc.set_response("my query", _vec(), SAMPLE_RESPONSE)

    pipe.setex.assert_called_once()   # exact tier
    assert pipe.hset.call_count == 2  # embeddings + responses hashes
    pipe.execute.assert_called_once()
