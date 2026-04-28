"""Query rewrite node — reformulates the user query for better retrieval."""

from __future__ import annotations

import structlog
import litellm

from anime_rag.core.settings import Settings
from anime_rag.rag.state import RAGState

log = structlog.get_logger(__name__)

_SYSTEM = (
    "You are a search query optimizer for an anime database. "
    "Rewrite the user's query to maximise retrieval of relevant anime synopses. "
    "Output ONLY the rewritten query — no explanation, no quotes."
)


def make_rewriter(settings: Settings):
    """Return a LangGraph node function that rewrites the query."""

    async def rewrite(state: RAGState) -> dict:
        query = state["query"]
        try:
            resp = await litellm.acompletion(
                model=settings.cheap_model,    # use cheap model for rewrite
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": query},
                ],
                max_tokens=128,
                temperature=0.0,
            )
            rewritten = resp.choices[0].message.content.strip()
            log.debug("query_rewritten", original=query, rewritten=rewritten)
        except Exception as exc:
            # Fall back to original query — don't crash the pipeline
            log.warning("query_rewrite_failed", error=str(exc))
            rewritten = query

        return {"rewritten_query": rewritten}

    return rewrite
