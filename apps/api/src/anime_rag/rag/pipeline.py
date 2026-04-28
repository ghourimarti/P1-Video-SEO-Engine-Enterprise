"""RAGPipeline — LangGraph graph with cache, hybrid retrieval, grader, and observability.

Graph topology:
    cache_check ──hit──► END
        │ miss
        ▼
     rewrite → retrieve → grade → generate → cache_write → END

stream_response() bypasses the LangGraph astream node iterator and instead runs
each phase directly so we can yield token-level SSE events from the generator.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Any, Optional

import litellm
import numpy as np
import structlog
from langchain_openai import OpenAIEmbeddings
from langgraph.graph import StateGraph, END
from psycopg_pool import AsyncConnectionPool
from tenacity import retry, stop_after_attempt, wait_exponential

from anime_rag.cache.service import CacheService
from anime_rag.core.metrics import rag_tokens_total, rag_cost_usd_total
from anime_rag.core.settings import Settings
from anime_rag.rag.state import RAGState
from anime_rag.rag.nodes.cache_check import make_cache_check
from anime_rag.rag.nodes.cache_write import make_cache_write
from anime_rag.rag.nodes.rewriter import make_rewriter
from anime_rag.rag.nodes.retriever import make_retriever
from anime_rag.rag.nodes.grader import make_grader
from anime_rag.rag.nodes.generator import make_generator, _SYSTEM, _HUMAN
from anime_rag.rag.utils import docs_to_context, extract_citations, estimate_cost, build_sources

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
        self._settings  = settings
        self._pool      = pool
        self._embedder  = embedder
        self._cache     = cache
        self._graph     = self._build(pool, embedder, cache, settings)
        # Pre-build node callables for direct use in stream_response
        self._cache_check_fn = make_cache_check(cache, embedder)
        self._rewriter_fn    = make_rewriter(settings)
        self._retriever_fn   = make_retriever(pool, embedder, settings)
        self._grader_fn      = make_grader(settings)
        self._cache_write_fn = make_cache_write(cache)

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
        """Yield fine-grained SSE events: step, token, sources, done."""
        state: RAGState = self._initial(query, top_n, trace_id)

        # ── 1. Cache check ────────────────────────────────────────────────────
        yield {"type": "step", "step": "cache_check"}
        patch = await self._cache_check_fn(state)
        state = {**state, **patch}

        if state.get("cached"):
            # Stream cached answer word-by-word (simulated token cadence)
            cached_answer: str = state.get("answer", "")
            yield {"type": "step", "step": "cache_hit"}
            for word in cached_answer.split(" "):
                yield {"type": "token", "content": word + " "}
                await asyncio.sleep(0.01)
            yield {
                "type":    "done",
                "sources": state.get("sources", []),
                "model_used": state.get("model_used", "cache"),
                "input_tokens":  0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "cached": True,
            }
            return

        # ── 2. Rewrite ────────────────────────────────────────────────────────
        yield {"type": "step", "step": "rewriting"}
        patch = await self._rewriter_fn(state)
        state = {**state, **patch}

        # ── 3. Retrieve ───────────────────────────────────────────────────────
        yield {"type": "step", "step": "retrieving"}
        patch = await self._retriever_fn(state)
        state = {**state, **patch}

        # ── 4. Grade ──────────────────────────────────────────────────────────
        yield {"type": "step", "step": "grading"}
        patch = await self._grader_fn(state)
        state = {**state, **patch}

        docs = state.get("documents", [])

        if not state.get("grader_passed", True) or not docs:
            fallback = (
                "I couldn't find anime that closely match your query. "
                "Try rephrasing or broadening your preferences."
                if not state.get("grader_passed", True)
                else "No relevant anime found for your query. Try rephrasing."
            )
            for word in fallback.split(" "):
                yield {"type": "token", "content": word + " "}
            yield {
                "type": "done", "sources": [], "model_used": "none",
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "cached": False,
            }
            return

        # ── 5. Generate (streaming) ───────────────────────────────────────────
        yield {"type": "step", "step": "generating"}
        query_text = state.get("rewritten_query") or state["query"]
        messages = [
            {"role": "system", "content": _SYSTEM.format(top_n=top_n)},
            {"role": "user",   "content": _HUMAN.format(
                context=docs_to_context(docs), query=query_text, top_n=top_n
            )},
        ]
        lf_metadata = {
            "generation_name": "anime-recommend-stream",
            "prompt_version":  "v1",
            "trace_id":        trace_id,
        }

        model       = self._settings.default_model
        full_answer = ""
        input_tok   = 0
        output_tok  = 0

        try:
            stream = await litellm.acompletion(
                model=model,
                messages=messages,
                max_tokens=self._settings.max_output_tokens,
                temperature=0.3,
                stream=True,
                metadata=lf_metadata,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None) or ""
                if content:
                    full_answer += content
                    yield {"type": "token", "content": content}
                # Accumulate usage if provider sends it in the last chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    input_tok  = chunk.usage.prompt_tokens     or 0
                    output_tok = chunk.usage.completion_tokens or 0
        except Exception:
            log.warning("stream_primary_failed", model=model, fallback=self._settings.fallback_model)
            model = self._settings.fallback_model
            stream = await litellm.acompletion(
                model=model,
                messages=messages,
                max_tokens=self._settings.max_output_tokens,
                temperature=0.3,
                stream=True,
                metadata=lf_metadata,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None) or ""
                if content:
                    full_answer += content
                    yield {"type": "token", "content": content}
                if hasattr(chunk, "usage") and chunk.usage:
                    input_tok  = chunk.usage.prompt_tokens     or 0
                    output_tok = chunk.usage.completion_tokens or 0

        cost = estimate_cost(model, input_tok, output_tok)
        rag_tokens_total.labels(model=model, token_type="input").inc(input_tok)
        rag_tokens_total.labels(model=model, token_type="output").inc(output_tok)
        rag_cost_usd_total.labels(model=model).inc(cost)

        cited_ids = extract_citations(full_answer, docs)
        sources   = build_sources(docs, cited_ids)

        # ── 6. Cache write ────────────────────────────────────────────────────
        stream_result_patch = {
            "answer":        full_answer,
            "sources":       sources,
            "model_used":    model,
            "input_tokens":  input_tok,
            "output_tokens": output_tok,
            "cost_usd":      cost,
            "cached":        False,
        }
        state = {**state, **stream_result_patch}
        await self._cache_write_fn(state)

        yield {
            "type":          "done",
            "sources":       sources,
            "model_used":    model,
            "input_tokens":  input_tok,
            "output_tokens": output_tok,
            "cost_usd":      cost,
            "cached":        False,
        }
