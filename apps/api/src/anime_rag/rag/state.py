"""LangGraph state definition for the RAG pipeline."""

from __future__ import annotations

from typing import Any, Optional, TypedDict


class AnimeDoc(TypedDict):
    mal_id: int
    name: str
    score: Optional[float]
    genres: list[str]
    synopsis: str
    similarity: float        # RRF score → Cohere relevance score after rerank
    cohere_score: Optional[float]


class RAGState(TypedDict):
    # ── Input ─────────────────────────────────────────────────────────────────
    query: str
    top_n: int

    # ── Embedding (computed once in cache_check, reused in retriever) ─────────
    query_embedding: Optional[list[float]]

    # ── Intermediate ──────────────────────────────────────────────────────────
    rewritten_query: str
    documents: list[AnimeDoc]
    grader_passed: bool

    # ── Output ───────────────────────────────────────────────────────────────
    answer: str
    sources: list[dict[str, Any]]
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cached: bool
    error: Optional[str]
