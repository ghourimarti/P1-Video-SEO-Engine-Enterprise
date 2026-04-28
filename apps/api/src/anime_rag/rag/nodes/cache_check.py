"""cache_check node — tier-1 exact then tier-2 semantic cache lookup."""

from __future__ import annotations

import numpy as np
import structlog
from langchain_openai import OpenAIEmbeddings

from anime_rag.cache.service import CacheService
from anime_rag.core.metrics import rag_cache_hits_total
from anime_rag.rag.state import RAGState

log = structlog.get_logger(__name__)


def make_cache_check(cache: CacheService, embedder: OpenAIEmbeddings):

    async def cache_check(state: RAGState) -> dict:
        query = state["query"]

        # ── Tier 1: exact (no embed cost) ─────────────────────────────────────
        exact_hit = await cache.get_exact(query)
        if exact_hit:
            rag_cache_hits_total.labels(tier="exact").inc()
            return {**exact_hit, "cached": True, "cache_tier": "exact", "query_embedding": None}

        # ── Embed query ───────────────────────────────────────────────────────
        try:
            vec = await embedder.aembed_query(query)
            query_vec = np.array(vec, dtype=np.float32)
        except Exception as exc:
            log.warning("cache_check_embed_failed", error=str(exc))
            return {"cached": False, "cache_tier": None, "query_embedding": None}

        # ── Tier 2: semantic ──────────────────────────────────────────────────
        sem_hit = await cache.get_semantic(query_vec)
        if sem_hit:
            rag_cache_hits_total.labels(tier="semantic").inc()
            return {
                **sem_hit,
                "cached": True,
                "cache_tier": "semantic",
                "query_embedding": query_vec.tolist(),
            }

        log.debug("cache_miss", query=query[:60])
        return {"cached": False, "cache_tier": None, "query_embedding": query_vec.tolist()}

    return cache_check
