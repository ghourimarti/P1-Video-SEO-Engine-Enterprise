"""RAGPipeline — LangGraph graph with cache, hybrid retrieval, grader, and observability.

Graph topology (M5):
    cache_check ──hit──► END
        │ miss
        ▼
     rewrite → retrieve → grade → generate → cache_write → END
"""

from __future__ import annotations

from typing import AsyncIterator, Any, Optional

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
    return END if state.get("cached") else "rewrite"


class RAGPipeline:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        embedder: OpenAIEmbeddings,
        cache: CacheService,
        settings: Settings,
    ) -> None:
        self._settings = settings
        self._graph = self._build(pool, embedder, cache, settings)

    def _build(self, pool, embedder, cache, settings):
        g = StateGraph(RAGState)
        g.add_node("cache_check",  make_cache_check(cache, embedder))
        g.add_node("rewrite",      make_rewriter(settings))
        g.add_node("retrieve",     make_retriever(pool, embedder, settings))
        g.add_node("grade",        make_grader(settings))
        g.add_node("generate",     make_generator(settings))
        g.add_node("cache_write",  make_cache_write(cache))
        g.set_entry_point("cache_check")
        g.add_conditional_edges("cache_check", _route_cache)
        g.add_edge("rewrite",     "retrieve")
        g.add_edge("retrieve",    "grade")
        g.add_edge("grade",       "generate")
        g.add_edge("generate",    "cache_write")
        g.add_edge("cache_write", END)
        return g.compile()

    def _initial(self, query: str, top_n: int, trace_id: Optional[str]) -> RAGState:
        return RAGState(
            query=query, top_n=top_n, trace_id=trace_id,
            query_embedding=None, rewritten_query="", documents=[],
            grader_passed=True, cache_tier=None, answer="", sources=[],
            model_used="", input_tokens=0, output_tokens=0,
            cost_usd=0.0, cached=False, error=None,
        )

    async def run(
        self, query: str, top_n: int = 5, trace_id: Optional[str] = None
    ) -> dict[str, Any]:
        return await self._graph.ainvoke(self._initial(query, top_n, trace_id))

    async def run_stream(
        self, query: str, top_n: int = 5, trace_id: Optional[str] = None
    ) -> AsyncIterator[dict[str, Any]]:
        async for chunk in self._graph.astream(self._initial(query, top_n, trace_id)):
            yield chunk
