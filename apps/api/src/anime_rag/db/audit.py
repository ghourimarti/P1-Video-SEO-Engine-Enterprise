"""Async audit log writer.

Inserts one row into `audit_log` per recommend request.
Failures are logged and silently swallowed — a broken audit path must never
surface as a 500 to the end user.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from psycopg_pool import AsyncConnectionPool

log = structlog.get_logger(__name__)


async def write_audit(
    pool: AsyncConnectionPool,
    *,
    user_id: str,
    query: str,
    model_used: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    cached: bool,
    pii_redacted: int,
    guard_blocked: bool,
    trace_id: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget audit row. Exceptions are caught internally."""
    try:
        async with pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (
                    user_id, query, model_used,
                    input_tokens, output_tokens, cost_usd,
                    cached, pii_redacted, guard_blocked,
                    trace_id, extra
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                """,
                (
                    user_id, query, model_used,
                    input_tokens, output_tokens, cost_usd,
                    cached, pii_redacted, guard_blocked,
                    trace_id, json.dumps(extra or {}),
                ),
            )
    except Exception as exc:
        log.error("audit_write_failed", error=str(exc))
