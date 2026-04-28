"""Unit tests for cost_control: ModelRouter, KillSwitch, BudgetGuard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from anime_rag.core.cost_control import (
    BudgetExceededError,
    BudgetGuard,
    KillSwitch,
    ModelRouter,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _settings(
    default="claude-sonnet-4-6",
    cheap="claude-haiku-4-5-20251001",
    threshold=30,
    user_budget=1.00,
    global_budget=50.00,
):
    s = MagicMock()
    s.default_model            = default
    s.cheap_model              = cheap
    s.cost_complex_query_words = threshold
    s.user_daily_budget_usd    = user_budget
    s.global_daily_budget_usd  = global_budget
    return s


# ── ModelRouter ───────────────────────────────────────────────────────────────

class TestModelRouter:
    def test_short_simple_query_uses_cheap(self):
        router = ModelRouter(_settings())
        model = router.select("What are good mecha anime?", kill_switch_active=False)
        assert model == "claude-haiku-4-5-20251001"

    def test_long_query_uses_default(self):
        long_query = " ".join(["word"] * 35)  # 35 words > threshold 30
        router = ModelRouter(_settings())
        model = router.select(long_query, kill_switch_active=False)
        assert model == "claude-sonnet-4-6"

    def test_complex_keyword_uses_default(self):
        router = ModelRouter(_settings())
        model = router.select(
            "Compare the thematic elements of Evangelion vs Gurren Lagann",
            kill_switch_active=False,
        )
        assert model == "claude-sonnet-4-6"

    def test_kill_switch_always_returns_cheap(self):
        router = ModelRouter(_settings())
        # Even a very long complex query must use cheap when kill switch is on
        long_complex = "Compare and analyse " + " ".join(["word"] * 40)
        model = router.select(long_complex, kill_switch_active=True)
        assert model == "claude-haiku-4-5-20251001"

    def test_kill_switch_overrides_short_simple(self):
        router = ModelRouter(_settings())
        model = router.select("Best anime?", kill_switch_active=True)
        assert model == "claude-haiku-4-5-20251001"

    def test_threshold_boundary_below(self):
        router = ModelRouter(_settings(threshold=5))
        model = router.select("a b c d", kill_switch_active=False)  # 4 words < 5
        assert model == "claude-haiku-4-5-20251001"

    def test_threshold_boundary_above(self):
        router = ModelRouter(_settings(threshold=5))
        model = router.select("a b c d e f", kill_switch_active=False)  # 6 words > 5
        assert model == "claude-sonnet-4-6"


# ── KillSwitch ────────────────────────────────────────────────────────────────

class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_is_active_returns_true_when_set(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value="1")
        ks = KillSwitch(redis)
        assert await ks.is_active() is True

    @pytest.mark.asyncio
    async def test_is_active_returns_false_when_unset(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        ks = KillSwitch(redis)
        assert await ks.is_active() is False

    @pytest.mark.asyncio
    async def test_is_active_fails_open_on_redis_error(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=Exception("redis down"))
        ks = KillSwitch(redis)
        assert await ks.is_active() is False  # fail open

    @pytest.mark.asyncio
    async def test_set_active_writes_flag(self):
        redis = AsyncMock()
        ks = KillSwitch(redis)
        await ks.set(True)
        redis.set.assert_awaited_once_with("cost:kill_switch", "1")

    @pytest.mark.asyncio
    async def test_set_inactive_deletes_flag(self):
        redis = AsyncMock()
        ks = KillSwitch(redis)
        await ks.set(False)
        redis.delete.assert_awaited_once_with("cost:kill_switch")


# ── BudgetGuard ───────────────────────────────────────────────────────────────

class TestBudgetGuard:
    def _make_redis(self, user_spend: float, global_spend: float) -> AsyncMock:
        pipeline = AsyncMock()
        pipeline.execute = AsyncMock(return_value=[str(user_spend), str(global_spend)])
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__  = AsyncMock(return_value=None)
        redis = AsyncMock()
        redis.pipeline = MagicMock(return_value=pipeline)
        return redis

    @pytest.mark.asyncio
    async def test_check_passes_when_under_budget(self):
        redis = self._make_redis(user_spend=0.50, global_spend=10.0)
        guard = BudgetGuard(redis, _settings(user_budget=1.00, global_budget=50.0))
        await guard.check("user_123")  # should not raise

    @pytest.mark.asyncio
    async def test_check_raises_when_user_over_budget(self):
        redis = self._make_redis(user_spend=1.01, global_spend=5.0)
        guard = BudgetGuard(redis, _settings(user_budget=1.00, global_budget=50.0))
        with pytest.raises(BudgetExceededError, match="Daily budget"):
            await guard.check("user_123")

    @pytest.mark.asyncio
    async def test_check_raises_when_global_over_budget(self):
        redis = self._make_redis(user_spend=0.50, global_spend=51.0)
        guard = BudgetGuard(redis, _settings(user_budget=1.00, global_budget=50.0))
        with pytest.raises(BudgetExceededError, match="Service daily"):
            await guard.check("user_123")

    @pytest.mark.asyncio
    async def test_check_fails_open_on_redis_error(self):
        redis = AsyncMock()
        redis.pipeline = MagicMock(side_effect=Exception("redis down"))
        guard = BudgetGuard(redis, _settings())
        await guard.check("user_123")  # should not raise

    @pytest.mark.asyncio
    async def test_record_skips_zero_cost(self):
        redis = AsyncMock()
        pipeline = AsyncMock()
        redis.pipeline = MagicMock(return_value=pipeline)
        guard = BudgetGuard(redis, _settings())
        await guard.record("user_123", 0.0)
        redis.pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_increments_both_keys(self):
        pipeline = AsyncMock()
        pipeline.execute = AsyncMock(return_value=[None, None, None, None])
        redis = AsyncMock()
        redis.pipeline = MagicMock(return_value=pipeline)
        guard = BudgetGuard(redis, _settings())
        await guard.record("user_abc", 0.0042)
        # incrbyfloat called twice: once for user key, once for global key
        calls = [c for c in pipeline.method_calls if c[0] == "incrbyfloat"]
        assert len(calls) == 2
