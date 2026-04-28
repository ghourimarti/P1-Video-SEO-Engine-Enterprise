"""Hybrid retrieval node: dense + BM25 → RRF merge → Cohere rerank.

M4: reuses query_embedding from state when the rewriter did not change the query.
M5: records retrieval duration + doc count to Prometheus.
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
import structlog
from langchain_openai import OpenAIEmbeddings
from psycopg_pool import AsyncConnectionPool

from anime_rag.core.metrics import rag_retrieval_duration_seconds, rag_retrieved_docs_count
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
    async def retrieve(state: RAGState) -> dict:
        query = state.get("rewritten_query") or state["query"]
        top_k = settings.retrieval_top_k
        t_start = time.perf_counter()

        # ── 1. Embed (reuse pre-computed if query unchanged) ──────────────────
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

        log.debug("retrieval_raw", dense_n=len(dense_docs), bm25_n=len(bm25_docs))

        # ── 3. RRF merge ──────────────────────────────────────────────────────
        rrf_scores = reciprocal_rank_fusion(
            [[d["mal_id"] for d in dense_docs], [d["mal_id"] for d in bm25_docs]],
            k=settings.rrf_k,
        )
        merged = merge_results([dense_docs, bm25_docs], rrf_scores)

        # ── 4. Cohere rerank ──────────────────────────────────────────────────
        reranked = await cohere_rerank(query, merged[:top_k], settings)

        elapsed = time.perf_counter() - t_start
        rag_retrieval_duration_seconds.observe(elapsed)
        rag_retrieved_docs_count.observe(len(reranked))

        log.info(
            "retrieval_complete",
            reranked_n=len(reranked),
            duration_s=round(elapsed, 3),
            top_score=reranked[0]["similarity"] if reranked else 0,
        )

        return {"documents": reranked}

    return retrieve
