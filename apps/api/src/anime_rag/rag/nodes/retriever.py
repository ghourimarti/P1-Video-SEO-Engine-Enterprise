"""Hybrid retrieval node: dense + BM25 → RRF merge → Cohere rerank.

M4: reuses query_embedding from state when the rewriter did not change
the query, avoiding a redundant OpenAI embedding API call.
"""

from __future__ import annotations

import asyncio

import numpy as np
import structlog
from langchain_openai import OpenAIEmbeddings
from psycopg_pool import AsyncConnectionPool

from anime_rag.core.settings import Settings
from anime_rag.rag.state import RAGState
from anime_rag.rag.retrieval.dense import retrieve_dense
from anime_rag.rag.retrieval.bm25 import retrieve_bm25
from anime_rag.rag.retrieval.rrf import reciprocal_rank_fusion, merge_results
from anime_rag.rag.retrieval.reranker import cohere_rerank

log = structlog.get_logger(__name__)


def make_retriever(
    pool: AsyncConnectionPool,
    embedder: OpenAIEmbeddings,
    settings: Settings,
):
    """Return a LangGraph node that performs hybrid retrieval."""

    async def retrieve(state: RAGState) -> dict:
        query = state.get("rewritten_query") or state["query"]
        top_k = settings.retrieval_top_k

        # ── 1. Embed query (reuse pre-computed embedding when query unchanged) ──
        original_query = state["query"]
        precomputed = state.get("query_embedding")

        if query == original_query and precomputed:
            vec_arr = np.array(precomputed, dtype=np.float32)
        else:
            try:
                vec = await embedder.aembed_query(query)
                vec_arr = np.array(vec, dtype=np.float32)
            except Exception as exc:
                log.error("embed_query_failed", error=str(exc))
                return {"documents": [], "grader_passed": False, "error": str(exc)}

        # ── 2. Dense + BM25 concurrently ─────────────────────────────────────
        dense_docs, bm25_docs = await asyncio.gather(
            retrieve_dense(pool, vec_arr, top_k),
            retrieve_bm25(pool, query, top_k),
        )

        log.debug(
            "retrieval_raw",
            dense_n=len(dense_docs),
            bm25_n=len(bm25_docs),
            query=query[:60],
        )

        # ── 3. RRF merge ──────────────────────────────────────────────────────
        dense_ids = [d["mal_id"] for d in dense_docs]
        bm25_ids  = [d["mal_id"] for d in bm25_docs]
        rrf_scores = reciprocal_rank_fusion([dense_ids, bm25_ids], k=settings.rrf_k)
        merged = merge_results([dense_docs, bm25_docs], rrf_scores)

        log.debug("rrf_merged", merged_n=len(merged))

        # ── 4. Cohere rerank ─────────────────────────────────────────────────
        candidates = merged[:top_k]
        reranked = await cohere_rerank(query, candidates, settings)

        log.info(
            "retrieval_complete",
            reranked_n=len(reranked),
            top_score=reranked[0]["similarity"] if reranked else 0,
        )

        return {"documents": reranked}

    return retrieve
