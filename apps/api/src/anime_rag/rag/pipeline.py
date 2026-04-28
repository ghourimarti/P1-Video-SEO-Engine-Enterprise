"""RAGPipeline — assembles the LangGraph graph and exposes run() / run_stream()."""

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
from anime_rag.rag.nodes.generator import make_generator

log = structlog.get_logger(__name__)


class RAGPipeline:
    """Compiled LangGraph RAG graph.

    Lifecycle:
        - Created once at app startup in main.py lifespan.
        - Stored on app.state.pipeline.
        - Shared across all requests (stateless per invocation).
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

        graph.add_node("rewrite", make_rewriter(settings))
        graph.add_node("retrieve", make_retriever(pool, embedder, settings))
        graph.add_node("generate", make_generator(settings))

        graph.set_entry_point("rewrite")
        graph.add_edge("rewrite", "retrieve")
        graph.add_edge("retrieve", "generate")
        graph.add_edge("generate", END)

        return graph.compile()

    async def run(self, query: str, top_n: int = 5) -> dict[str, Any]:
        """Run the full pipeline and return the final state."""
        initial: RAGState = {
            "query": query,
            "top_n": top_n,
            "rewritten_query": "",
            "documents": [],
            "answer": "",
            "sources": [],
            "model_used": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "cached": False,
            "error": None,
        }
        result = await self._graph.ainvoke(initial)
        return result

    async def run_stream(self, query: str, top_n: int = 5) -> AsyncIterator[dict[str, Any]]:
        """Stream node-by-node state updates.

        M6 upgrades this to token-level SSE streaming via the Vercel AI SDK.
        """
        initial: RAGState = {
            "query": query,
            "top_n": top_n,
            "rewritten_query": "",
            "documents": [],
            "answer": "",
            "sources": [],
            "model_used": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "cached": False,
            "error": None,
        }
        async for chunk in self._graph.astream(initial):
            yield chunk
