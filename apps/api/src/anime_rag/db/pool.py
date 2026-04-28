"""Async psycopg3 connection pool with pgvector type registration."""

from __future__ import annotations

import structlog
from psycopg_pool import AsyncConnectionPool
from pgvector.psycopg import register_vector_async

from anime_rag.core.settings import Settings

log = structlog.get_logger(__name__)


async def create_pool(settings: Settings) -> AsyncConnectionPool:
    conninfo = (
        f"host={settings.postgres_host} "
        f"port={settings.postgres_port} "
        f"dbname={settings.postgres_db} "
        f"user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )

    async def configure(conn):
        await register_vector_async(conn)

    pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=2,
        max_size=10,
        configure=configure,
        open=False,
    )
    await pool.open(wait=True, timeout=10.0)
    log.info("db_pool_opened", host=settings.postgres_host, db=settings.postgres_db)
    return pool


async def close_pool(pool: AsyncConnectionPool) -> None:
    await pool.close()
    log.info("db_pool_closed")
