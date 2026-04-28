"""BM25-style full-text retrieval via Postgres tsvector + ts_rank_cd."""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from anime_rag.rag.state import AnimeDoc

_SQL = """
SELECT
    mal_id,
    name,
    score,
    genres,
    synopsis,
    ts_rank_cd(tsv, plainto_tsquery('english', %s)) AS bm25_rank
FROM anime_documents
WHERE tsv @@ plainto_tsquery('english', %s)
ORDER BY bm25_rank DESC
LIMIT %s
"""


async def retrieve_bm25(
    pool: AsyncConnectionPool,
    query: str,
    top_k: int,
) -> list[AnimeDoc]:
    """Return top_k docs matched by full-text search, ordered by BM25 rank.

    Returns empty list if the query produces no ts tokens (e.g. all stopwords)
    or no rows match — RRF will then rely entirely on dense results.
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(_SQL, (query, query, top_k))
            rows = await cur.fetchall()

    return [
        AnimeDoc(
            mal_id=row[0],
            name=row[1],
            score=row[2],
            genres=row[3] or [],
            synopsis=row[4],
            similarity=float(row[5]),   # bm25_rank used as similarity placeholder
            cohere_score=None,
        )
        for row in rows
    ]
