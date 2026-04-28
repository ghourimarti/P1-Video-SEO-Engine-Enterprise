"""cache_write node — persists the generated response to Redis.

Runs after generate. Skips write if:
- The response contains an error.
- The answer is empty (pipeline produced nothing useful).
- The query embedding is missing (can't do semantic lookup later).
"""

from __future__ import annotations

import numpy as np
import structlog

from anime_rag.cache.service import CacheService
from anime_rag.rag.state import RAGState

log = structlog.get_logger(__name__)


def make_cache_write(cache: CacheService):
    """Return a LangGraph node that writes the response to the cache."""

    async def cache_write(state: RAGState) -> dict:
        if state.get("error") or not state.get("answer") or state.get("cached"):
            return {}

        query_embedding = state.get("query_embedding")
        if not query_embedding:
            log.debug("cache_write_skipped", reason="no embedding in state")
            return {}

        response = {
            "answer":        state["answer"],
            "sources":       state["sources"],
            "model_used":    state["model_used"],
            "input_tokens":  state["input_tokens"],
            "output_tokens": state["output_tokens"],
            "cost_usd":      state["cost_usd"],
        }

        await cache.set_response(
            query=state["query"],
            query_vec=np.array(query_embedding, dtype=np.float32),
            response=response,
        )
        return {}

    return cache_write
