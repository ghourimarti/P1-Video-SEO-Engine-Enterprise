"""CacheService — two-tier Redis cache for RAG responses.

Tier 1 — Exact cache:
    Key:   rag:exact:{sha256(normalised_query)[:16]}
    Value: JSON response string
    TTL:   settings.cache_ttl_seconds (default 1 h)

Tier 2 — Semantic cache:
    Embeddings hash:  rag:sem:embeddings  {query_hash → vec_json}
    Responses hash:   rag:sem:responses   {query_hash → response_json}
    Lookup:  compute cosine(new_vec, stored_vec) for all entries;
             return cached response if max_similarity >= threshold (0.92).

    Production note: this O(N_cache) scan is fine for portfolios and small
    deployments (<10 k cached entries). At scale, replace with RedisVL or
    pgvector-backed similarity search on the cache table.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import numpy as np
import redis.asyncio as aioredis
import structlog

from anime_rag.core.settings import Settings

log = structlog.get_logger(__name__)

_EXACT_PREFIX = "rag:exact:"
_SEM_EMB_KEY  = "rag:sem:embeddings"   # Redis Hash
_SEM_RESP_KEY = "rag:sem:responses"    # Redis Hash


def _hash(text: str) -> str:
    """Normalise and SHA-256 hash a query string (first 16 hex chars)."""
    normalised = text.lower().strip()
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 1e-10 else 0.0


class CacheService:
    def __init__(self, redis: aioredis.Redis, settings: Settings) -> None:
        self._r = redis
        self._settings = settings

    # ── Exact cache ──────────────────────────────────────────────────────────

    async def get_exact(self, query: str) -> Optional[dict[str, Any]]:
        key = f"{_EXACT_PREFIX}{_hash(query)}"
        try:
            val = await self._r.get(key)
            if val:
                log.debug("cache_exact_hit", query=query[:60])
                return json.loads(val)
        except Exception as exc:
            log.warning("cache_get_exact_error", error=str(exc))
        return None

    # ── Semantic cache ────────────────────────────────────────────────────────

    async def get_semantic(
        self, query_vec: np.ndarray
    ) -> Optional[dict[str, Any]]:
        try:
            raw_embeddings: dict = await self._r.hgetall(_SEM_EMB_KEY)
            if not raw_embeddings:
                return None

            best_sim = 0.0
            best_hash: Optional[bytes] = None

            for h, vec_bytes in raw_embeddings.items():
                stored = np.array(json.loads(vec_bytes), dtype=np.float32)
                sim = _cosine(query_vec, stored)
                if sim > best_sim:
                    best_sim = sim
                    best_hash = h

            threshold = self._settings.semantic_cache_threshold
            if best_sim >= threshold and best_hash is not None:
                resp_bytes = await self._r.hget(_SEM_RESP_KEY, best_hash)
                if resp_bytes:
                    log.info(
                        "cache_semantic_hit",
                        similarity=round(best_sim, 4),
                        threshold=threshold,
                    )
                    return json.loads(resp_bytes)

        except Exception as exc:
            log.warning("cache_get_semantic_error", error=str(exc))
        return None

    # ── Write ─────────────────────────────────────────────────────────────────

    async def set_response(
        self,
        query: str,
        query_vec: np.ndarray,
        response: dict[str, Any],
    ) -> None:
        """Store response in both exact and semantic tiers."""
        h = _hash(query)
        ttl = self._settings.cache_ttl_seconds
        response_json = json.dumps(response, default=str)
        vec_json = json.dumps(query_vec.tolist())

        try:
            pipe = self._r.pipeline()
            # Exact tier (with TTL)
            pipe.setex(f"{_EXACT_PREFIX}{h}", ttl, response_json)
            # Semantic tier (no per-field TTL in Redis Hash — entries age out
            # on server restart or manual flush; acceptable for portfolio)
            pipe.hset(_SEM_EMB_KEY, h, vec_json)
            pipe.hset(_SEM_RESP_KEY, h, response_json)
            await pipe.execute()
            log.debug("cache_written", query_hash=h)
        except Exception as exc:
            log.warning("cache_write_error", error=str(exc))

    # ── Utility ───────────────────────────────────────────────────────────────

    async def flush(self) -> None:
        """Clear all cache entries (useful in tests)."""
        keys = await self._r.keys("rag:*")
        if keys:
            await self._r.delete(*keys)
