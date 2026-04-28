"""Admin cost endpoints: kill switch toggle + daily cost summary from audit_log."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from anime_rag.core.cost_control import KillSwitch

router = APIRouter(prefix="/admin/cost", tags=["admin"])
log    = structlog.get_logger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

class KillSwitchStatus(BaseModel):
    active: bool


class KillSwitchRequest(BaseModel):
    active: bool
    reason: str = ""


class ModelCostRow(BaseModel):
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_cost_usd: float
    cache_hits: int


class CostSummary(BaseModel):
    date: str
    models: list[ModelCostRow]
    total_usd: float
    cache_hit_rate: float


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/kill-switch", response_model=KillSwitchStatus)
async def get_kill_switch(request: Request) -> KillSwitchStatus:
    ks = KillSwitch(request.app.state.redis)
    return KillSwitchStatus(active=await ks.is_active())


@router.post("/kill-switch", response_model=KillSwitchStatus)
async def set_kill_switch(request: Request, body: KillSwitchRequest) -> KillSwitchStatus:
    ks = KillSwitch(request.app.state.redis)
    await ks.set(body.active)
    log.info(
        "kill_switch_toggled",
        active=body.active,
        reason=body.reason,
    )
    return KillSwitchStatus(active=body.active)


@router.get("/summary", response_model=CostSummary)
async def cost_summary(request: Request) -> CostSummary:
    """Aggregate today's cost from audit_log, grouped by model."""
    pool = request.app.state.db_pool
    async with pool.connection() as conn:
        rows = await conn.execute(
            """
            SELECT
                model_used,
                COUNT(*)                               AS requests,
                COALESCE(SUM(input_tokens),  0)        AS input_tokens,
                COALESCE(SUM(output_tokens), 0)        AS output_tokens,
                ROUND(COALESCE(SUM(cost_usd),  0)::numeric, 6) AS cost_usd,
                ROUND(COALESCE(AVG(cost_usd),  0)::numeric, 6) AS avg_cost_usd,
                COALESCE(SUM(cached::int),   0)        AS cache_hits
            FROM audit_log
            WHERE created_at >= CURRENT_DATE
            GROUP BY model_used
            ORDER BY cost_usd DESC
            """
        )
        data = await rows.fetchall()

    model_rows = [
        ModelCostRow(
            model=r[0] or "unknown",
            requests=r[1],
            input_tokens=r[2],
            output_tokens=r[3],
            cost_usd=float(r[4] or 0),
            avg_cost_usd=float(r[5] or 0),
            cache_hits=r[6],
        )
        for r in data
    ]

    total_usd       = sum(m.cost_usd   for m in model_rows)
    total_requests  = sum(m.requests   for m in model_rows)
    total_hits      = sum(m.cache_hits for m in model_rows)
    cache_hit_rate  = (total_hits / total_requests) if total_requests > 0 else 0.0

    return CostSummary(
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        models=model_rows,
        total_usd=total_usd,
        cache_hit_rate=round(cache_hit_rate, 4),
    )
