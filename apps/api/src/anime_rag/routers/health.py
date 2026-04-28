"""Health and readiness endpoints."""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
import redis.asyncio as aioredis

from anime_rag.core.settings import get_settings

router = APIRouter()
settings = get_settings()


class HealthResponse(BaseModel):
    status: str
    version: str
    checks: dict[str, str] = {}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok", version="0.2.0")


@router.get("/ready", response_model=HealthResponse)
async def readiness_check(request: Request):
    checks: dict[str, str] = {}

    # DB ping
    try:
        pool = request.app.state.db_pool
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"

    # Redis ping
    try:
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    failed = [k for k, v in checks.items() if v != "ok"]
    if failed:
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "checks": checks},
        )

    return HealthResponse(status="ok", version="0.2.0", checks=checks)
