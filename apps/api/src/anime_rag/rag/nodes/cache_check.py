"""cache_check node — tier-1 exact then tier-2 semantic lookup.

If either cache tier hits, the full response is written into state and
`cached: True` is set. The pipeline then routes directly to END,
skipping rewrite → retrieve → grade → generate entirely.

If both tiers miss, the query embedding computed here is stored in
`state["query_embedding"]` so the retriever can reuse it without a
second API call.
"""

from __future__ import annotations

import numpy as np
import structlog
from langchain_openai import OpenAIEmbeddings

from anime_rag.cache.service import CacheService
from anime_rag.rag.state import RAGState

log = structlog.get_logger(__name__)


def make_cache_check(cache: CacheService, embedder: OpenAIEmbeddings):
    """Return a LangGraph node that checks both cache tiers."""

    async def cache_check(state: RAGState) -> dict:
        query = state["query"]

        # ── Tier 1: exact match (cheapest — no embedding needed) ──────────────
        exact_hit = await cache.get_exact(query)
        if exact_hit:
            return {
                **exact_hit,
                "cached": True,
                "query_embedding": None,
            }

        # ── Embed query (stored for retriever to reuse on cache miss) ─────────
        try:
            vec = await embedder.aembed_query(query)
            query_vec = np.array(vec, dtype=np.float32)
        except Exception as exc:
            log.warning("cache_check_embed_failed", error=str(exc))
            return {"cached": False, "query_embedding": None}

        # ── Tier 2: semantic match ────────────────────────────────────────────
        sem_hit = await cache.get_semantic(query_vec)
        if sem_hit:
            return {
                **sem_hit,
                "cached": True,
                "query_embedding": query_vec.tolist(),
            }

        # ── Cache miss — pass embedding downstream ────────────────────────────
        log.debug("cache_miss", query=query[:60])
        return {"cached": False, "query_embedding": query_vec.tolist()}

    return cache_check
