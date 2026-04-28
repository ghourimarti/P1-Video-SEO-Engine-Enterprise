"""RAGPipeline — LangGraph graph with cache, hybrid retrieval, and grader.

Graph topology (M4):

    cache_check ──hit──► END
        │
       miss
        ▼
     rewrite → retrieve → grade → generate → cache_write → END

cache_check:  tier-1 exact + tier-2 semantic lookup; embeds query once
rewrite:      LLM query reformulation (cheap model, silent fallback)
retrieve:     dense (pgvector) + BM25 concurrent → RRF → Cohere rerank
grade:        drops docs below Cohere relevance threshold
generate:     LiteLLM with model cascade + citation extraction
cache_write:  persists response to Redis exact + semantic tiers
"""

from __future__ import annotations

from typing import AsyncIterator, Any

import structlog
from langchain_openai import OpenAIEmbeddings
from langgraph.graph import StateGraph, END
from psycopg_pool import AsyncConnectionPool

from anime_rag.cache.service import CacheService
from anime_rag.core.settings import Settings
from anime_rag.rag.state import RAGState
from anime_rag.rag.nodes.cache_check import make_cache_check
from anime_rag.rag.nodes.cache_write import make_cache_write
from anime_rag.rag.nodes.rewriter import make_rewriter
from anime_rag.rag.nodes.retriever import make_retriever
from anime_rag.rag.nodes.grader import make_grader
from anime_rag.rag.nodes.generator import make_generator

log = structlog.get_logger(__name__)


def _route_cache(state: RAGState) -> str:
    """Route to END on cache hit, otherwise run the full pipeline."""
    return END if state.get("cached") else "rewrite"


class RAGPipeline:
    """Compiled LangGraph graph — instantiated once at startup."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        embedder: OpenAIEmbeddings,
        cache: CacheService,
        settings: Settings,
    ) -> None:
        self._settings = settings
        self._graph = self._build(pool, embedder, cache, settings)

    def _build(
        self,
        pool: AsyncConnectionPool,
        embedder: OpenAIEmbeddings,
        cache: CacheService,
        settings: Settings,
    ):
        graph = StateGraph(RAGState)

        graph.add_node("cache_check",  make_cache_check(cache, embedder))
        graph.add_node("rewrite",      make_rewriter(settings))
        graph.add_node("retrieve",     make_retriever(pool, embedder, settings))
        graph.add_node("grade",        make_grader(settings))
        graph.add_node("generate",     make_generator(settings))
        graph.add_node("cache_write",  make_cache_write(cache))

        graph.set_entry_point("cache_check")
        graph.add_conditional_edges("cache_check", _route_cache)
        graph.add_edge("rewrite",     "retrieve")
        graph.add_edge("retrieve",    "grade")
        graph.add_edge("grade",       "generate")
        graph.add_edge("generate",    "cache_write")
        graph.add_edge("cache_write", END)

        return graph.compile()

    def _initial_state(self, query: str, top_n: int) -> RAGState:
        return RAGState(
            query=query,
            top_n=top_n,
            query_embedding=None,
            rewritten_query="",
            documents=[],
            grader_passed=True,
            answer="",
            sources=[],
            model_used="",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            cached=False,
            error=None,
        )

    async def run(self, query: str, top_n: int = 5) -> dict[str, Any]:
        return await self._graph.ainvoke(self._initial_state(query, top_n))

    async def run_stream(self, query: str, top_n: int = 5) -> AsyncIterator[dict[str, Any]]:
        """Stream node-by-node state deltas. M6 upgrades to token-level SSE."""
        async for chunk in self._graph.astream(self._initial_state(query, top_n)):
            yield chunk
