"""Grader node — filters retrieved docs by minimum relevance score.

Uses the Cohere relevance score when available, otherwise falls through.
If zero docs survive the threshold the generator returns a "no results" answer.
"""

from __future__ import annotations

import structlog

from anime_rag.core.settings import Settings
from anime_rag.rag.state import AnimeDoc, RAGState

log = structlog.get_logger(__name__)

# If Cohere scored a doc below this, it's not worth including in the prompt
_COHERE_THRESHOLD = 0.05
# If using RRF score only (no Cohere), keep everything — reranker already cut to top_n
_RRF_THRESHOLD = 0.0


def make_grader(settings: Settings):
    """Return a LangGraph node that filters docs by relevance."""

    async def grade(state: RAGState) -> dict:
        docs: list[AnimeDoc] = state.get("documents", [])

        if not docs:
            log.info("grader_no_docs")
            return {"grader_passed": False, "documents": []}

        use_cohere = settings.cohere_api_key and any(
            d.get("cohere_score") is not None for d in docs
        )

        if use_cohere:
            threshold = _COHERE_THRESHOLD
            filtered = [
                d for d in docs
                if (d.get("cohere_score") or 0.0) >= threshold
            ]
        else:
            # No Cohere — trust RRF ordering; just pass through
            filtered = docs

        passed = len(filtered) > 0
        log.info(
            "grader_result",
            input_n=len(docs),
            output_n=len(filtered),
            passed=passed,
            cohere=use_cohere,
        )

        return {"grader_passed": passed, "documents": filtered}

    return grade
