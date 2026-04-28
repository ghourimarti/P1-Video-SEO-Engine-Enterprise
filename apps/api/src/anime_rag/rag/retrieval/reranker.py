"""Cohere cross-encoder reranker.

Takes the merged RRF candidates and reranks them with Cohere Rerank v3.
Falls back gracefully to RRF ordering when COHERE_API_KEY is not set.
"""

from __future__ import annotations

import structlog
import cohere

from anime_rag.core.settings import Settings
from anime_rag.rag.state import AnimeDoc

log = structlog.get_logger(__name__)

_RERANK_MODEL = "rerank-english-v3.0"
_MIN_RELEVANCE = 0.01   # docs below this score are dropped entirely


async def cohere_rerank(
    query: str,
    candidates: list[AnimeDoc],
    settings: Settings,
) -> list[AnimeDoc]:
    """Rerank candidates with Cohere and return top rerank_top_n docs.

    Falls back to first rerank_top_n candidates (RRF order) if Cohere
    is unavailable or the key is not configured.
    """
    if not candidates:
        return []

    if not settings.cohere_api_key:
        log.debug("cohere_reranker_skipped", reason="no api key")
        return candidates[: settings.rerank_top_n]

    try:
        co = cohere.AsyncClientV2(api_key=settings.cohere_api_key)

        # Build document strings: title + synopsis gives richer signal than synopsis alone
        doc_strings = [
            f"{d['name']}. {d['synopsis']}" for d in candidates
        ]

        response = await co.rerank(
            model=_RERANK_MODEL,
            query=query,
            documents=doc_strings,
            top_n=settings.rerank_top_n,
        )

        reranked: list[AnimeDoc] = []
        for result in response.results:
            doc = candidates[result.index].copy()
            doc["cohere_score"] = result.relevance_score
            doc["similarity"] = result.relevance_score  # expose as unified relevance
            if result.relevance_score >= _MIN_RELEVANCE:
                reranked.append(doc)

        log.debug(
            "cohere_reranked",
            input_n=len(candidates),
            output_n=len(reranked),
        )
        return reranked

    except Exception as exc:
        log.warning("cohere_reranker_failed", error=str(exc))
        # Degrade gracefully to RRF ordering
        return candidates[: settings.rerank_top_n]
