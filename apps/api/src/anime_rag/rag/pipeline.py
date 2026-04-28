"""RAGPipeline — LangGraph graph with hybrid retrieval + grader."""

from __future__ import annotations

from typing import AsyncIterator, Any

import structlog
from langchain_openai import OpenAIEmbeddings
from langgraph.graph import StateGraph, END
from psycopg_pool import AsyncConnectionPool

from anime_rag.core.settings import Settings
from anime_rag.rag.state import RAGState
from anime_rag.rag.nodes.rewriter import make_rewriter
from anime_rag.rag.nodes.retriever import make_retriever
from anime_rag.rag.nodes.grader import make_grader
from anime_rag.rag.nodes.generator import make_generator

log = structlog.get_logger(__name__)


class RAGPipeline:
    """Compiled LangGraph graph.

    Graph topology (M3):
        rewrite → retrieve → grade → generate → END

    M3 retrieval: dense (pgvector) + BM25 (tsvector) → RRF → Cohere rerank
    M4 will add Redis semantic cache before rewrite.
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        embedder: OpenAIEmbeddings,
        settings: Settings,
    ) -> None:
        self._settings = settings
        self._graph = self._build(pool, embedder, settings)

    def _build(
        self,
        pool: AsyncConnectionPool,
        embedder: OpenAIEmbeddings,
        settings: Settings,
    ):
        graph = StateGraph(RAGState)

        graph.add_node("rewrite",  make_rewriter(settings))
        graph.add_node("retrieve", make_retriever(pool, embedder, settings))
        graph.add_node("grade",    make_grader(settings))
        graph.add_node("generate", make_generator(settings))

        graph.set_entry_point("rewrite")
        graph.add_edge("rewrite",  "retrieve")
        graph.add_edge("retrieve", "grade")
        graph.add_edge("grade",    "generate")
        graph.add_edge("generate", END)

        return graph.compile()

    async def run(self, query: str, top_n: int = 5) -> dict[str, Any]:
        initial: RAGState = {
            "query":          query,
            "top_n":          top_n,
            "rewritten_query": "",
            "documents":      [],
            "grader_passed":  True,
            "answer":         "",
            "sources":        [],
            "model_used":     "",
            "input_tokens":   0,
            "output_tokens":  0,
            "cost_usd":       0.0,
            "cached":         False,
            "error":          None,
        }
        return await self._graph.ainvoke(initial)

    async def run_stream(self, query: str, top_n: int = 5) -> AsyncIterator[dict[str, Any]]:
        """Stream node-by-node state deltas.

        M6 upgrades to token-level SSE via Vercel AI SDK.
        """
        initial: RAGState = {
            "query":          query,
            "top_n":          top_n,
            "rewritten_query": "",
            "documents":      [],
            "grader_passed":  True,
            "answer":         "",
            "sources":        [],
            "model_used":     "",
            "input_tokens":   0,
            "output_tokens":  0,
            "cost_usd":       0.0,
            "cached":         False,
            "error":          None,
        }
        async for chunk in self._graph.astream(initial):
            yield chunk
