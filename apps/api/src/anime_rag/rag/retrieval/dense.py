"""Dense vector retrieval via pgvector cosine similarity."""

from __future__ import annotations

import numpy as np
from psycopg_pool import AsyncConnectionPool

from anime_rag.rag.state import AnimeDoc

_SQL = """
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


async def retrieve_dense(
    pool: AsyncConnectionPool,
    query_vec: np.ndarray,
    top_k: int,
) -> list[AnimeDoc]:
    """Return top_k docs ordered by cosine similarity to query_vec."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(_SQL, (query_vec, query_vec, top_k))
            rows = await cur.fetchall()

    return [
        AnimeDoc(
            mal_id=row[0],
            name=row[1],
            score=row[2],
            genres=row[3] or [],
            synopsis=row[4],
            similarity=float(row[5]),
            cohere_score=None,
        )
        for row in rows
    ]
