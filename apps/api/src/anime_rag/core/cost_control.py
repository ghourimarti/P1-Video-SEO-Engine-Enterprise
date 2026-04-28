"""Cost controls: kill switch, complexity-based model routing, per-user daily budget."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import redis.asyncio as aioredis

from anime_rag.core.settings import Settings

log = logging.getLogger(__name__)

# Redis keys
_KILL_SWITCH_KEY  = "cost:kill_switch"
_USER_BUDGET_KEY  = "cost:budget:user:{user_id}:{date}"
_GLOBAL_BUDGET_KEY = "cost:budget:global:{date}"

# Keywords that warrant the full default_model (complex reasoning)
_COMPLEX_KEYWORDS = frozenset({
    "compare", "versus", "vs.", "difference", "between", "similarities",
    "explain", "analysis", "analyse", "analyze", "why", "elaborate",
    "in depth", "detailed", "contrast", "relationship", "thematic",
})


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ttl_until_midnight() -> int:
    """Seconds from now until 00:00 UTC — used as Redis key TTL."""
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((midnight - now).total_seconds()))


# ── Model routing ─────────────────────────────────────────────────────────────

class ModelRouter:
    """Pick the cheapest model sufficient for the query complexity."""

    def __init__(self, settings: Settings) -> None:
        self._default   = settings.default_model
        self._cheap     = settings.cheap_model
        self._threshold = settings.cost_complex_query_words

    def select(self, query: str, kill_switch_active: bool) -> str:
        """Return model name. Kill switch overrides everything → cheap model."""
        if kill_switch_active:
            return self._cheap

        q_lower = query.lower()
        word_count = len(query.split())

        is_complex = (
            word_count > self._threshold
            or any(kw in q_lower for kw in _COMPLEX_KEYWORDS)
        )
        return self._default if is_complex else self._cheap


# ── Kill switch ────────────────────────────────────────────────────────────────

class KillSwitch:
    """Redis-backed flag — when active all LLM calls use the cheap model."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def is_active(self) -> bool:
        try:
            return await self._redis.get(_KILL_SWITCH_KEY) == "1"
        except Exception as exc:
            log.warning("kill_switch_read_failed: %s", exc)
            return False  # fail open

    async def set(self, active: bool) -> None:
        if active:
            await self._redis.set(_KILL_SWITCH_KEY, "1")
        else:
            await self._redis.delete(_KILL_SWITCH_KEY)


# ── Budget enforcement ────────────────────────────────────────────────────────

class BudgetExceededError(Exception):
    """Raised when a user or the global daily budget is exhausted."""


class BudgetGuard:
    """Track and enforce per-user and global daily USD spend limits in Redis."""

    def __init__(self, redis: aioredis.Redis, settings: Settings) -> None:
        self._redis        = redis
        self._user_limit   = settings.user_daily_budget_usd
        self._global_limit = settings.global_daily_budget_usd

    def _user_key(self, user_id: str) -> str:
        return _USER_BUDGET_KEY.format(user_id=user_id, date=_today_utc())

    def _global_key(self) -> str:
        return _GLOBAL_BUDGET_KEY.format(date=_today_utc())

    async def check(self, user_id: str) -> None:
        """Raise BudgetExceededError if limits are exceeded. Fail open on Redis error."""
        try:
            pipe = self._redis.pipeline()
            pipe.get(self._user_key(user_id))
            pipe.get(self._global_key())
            user_raw, global_raw = await pipe.execute()

            user_spend   = float(user_raw   or 0)
            global_spend = float(global_raw or 0)

            if user_spend >= self._user_limit:
                raise BudgetExceededError(
                    f"Daily budget of ${self._user_limit:.2f} reached. "
                    "Resets at midnight UTC."
                )
            if global_spend >= self._global_limit:
                raise BudgetExceededError(
                    "Service daily capacity reached. Please try again tomorrow."
                )
        except BudgetExceededError:
            raise
        except Exception as exc:
            log.warning("budget_check_failed: %s", exc)  # fail open

    async def record(self, user_id: str, cost_usd: float) -> None:
        """Increment per-user and global counters; set TTL = seconds until midnight."""
        if cost_usd <= 0:
            return
        try:
            ttl       = _ttl_until_midnight()
            user_key  = self._user_key(user_id)
            global_key = self._global_key()
            pipe = self._redis.pipeline()
            pipe.incrbyfloat(user_key,   cost_usd)
            pipe.expire(user_key,  ttl)
            pipe.incrbyfloat(global_key, cost_usd)
            pipe.expire(global_key, ttl)
            await pipe.execute()
        except Exception as exc:
            log.warning("budget_record_failed: %s", exc)
