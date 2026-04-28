"""Dense retrieval node using pgvector cosine similarity.

M3 upgrades this to hybrid BM25 + dense + RRF + Cohere reranker.
"""

from __future__ import annotations

import numpy as np
import structlog
from langchain_openai import OpenAIEmbeddings
from psycopg_pool import AsyncConnectionPool

from anime_rag.core.settings import Settings
from anime_rag.rag.state import AnimeDoc, RAGState

log = structlog.get_logger(__name__)

_DENSE_SQL = """
SELECT
    mal_id,
    name,
    score,
    genres,
    synopsis,
    1 - (embedding <=> %s::vector) AS similarity
FROM anime_documents
ORDER BY embedding <=> %s::vector
LIMIT %s
"""


def make_retriever(
    pool: AsyncConnectionPool,
    embedder: OpenAIEmbeddings,
    settings: Settings,
):
    """Return a LangGraph node function that retrieves documents."""

    async def retrieve(state: RAGState) -> dict:
        query = state.get("rewritten_query") or state["query"]
        top_k = settings.retrieval_top_k

        # Embed query
        try:
            vec = await embedder.aembed_query(query)
        except Exception as exc:
            log.error("embed_query_failed", error=str(exc))
            return {"documents": [], "error": f"Embedding failed: {exc}"}

        vec_arr = np.array(vec, dtype=np.float32)

        # Query pgvector
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_DENSE_SQL, (vec_arr, vec_arr, top_k))
                rows = await cur.fetchall()

        docs: list[AnimeDoc] = []
        for mal_id, name, score, genres, synopsis, similarity in rows:
            docs.append(
                AnimeDoc(
                    mal_id=mal_id,
                    name=name,
                    score=score,
                    genres=genres or [],
                    synopsis=synopsis,
                    similarity=float(similarity),
                )
            )

        log.debug("retrieved", n=len(docs), query=query[:60])
        return {"documents": docs}

    return retrieve
