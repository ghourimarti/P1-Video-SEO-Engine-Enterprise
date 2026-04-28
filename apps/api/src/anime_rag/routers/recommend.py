"""Recommendation router — JWT auth, PII scrub, guardrails, audit, OTel, Prometheus."""

import asyncio
import json
import time
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from opentelemetry import trace

from anime_rag.core.cost_control import BudgetExceededError, BudgetGuard, KillSwitch, ModelRouter
from anime_rag.core.guardrails import check as guard_check
from anime_rag.core.metrics import (
    rag_errors_total,
    rag_request_duration_seconds,
    rag_requests_total,
)
from anime_rag.core.pii import scrub as pii_scrub
from anime_rag.core.security import ClerkUser
from anime_rag.db.audit import write_audit
from anime_rag.rag.pipeline import RAGPipeline
from anime_rag.schemas.recommend import RecommendRequest, RecommendResponse, Source

router = APIRouter()
log    = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


def _user_id(claims: dict) -> str:
    return claims.get("sub", "anonymous")


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(
    request: Request,
    body: RecommendRequest,
    claims: ClerkUser,
):
    pipeline: RAGPipeline = request.app.state.pipeline
    pool                  = request.app.state.db_pool
    trace_id = str(uuid.uuid4())
    t_start  = time.perf_counter()
    user_id  = _user_id(claims)

    structlog.contextvars.bind_contextvars(trace_id=trace_id, user_id=user_id)
    log.info("recommend_start", query=body.query[:80], top_n=body.top_n)

    # ── Guardrails ────────────────────────────────────────────────────────────
    guard = guard_check(body.query)
    if guard.blocked:
        log.warning("recommend_blocked", reason=guard.reason)
        asyncio.create_task(
            write_audit(
                pool, user_id=user_id, query=body.query[:512], model_used="none",
                input_tokens=0, output_tokens=0, cost_usd=0.0, cached=False,
                pii_redacted=0, guard_blocked=True, trace_id=trace_id,
                extra={"block_reason": guard.reason},
            )
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Query rejected: {guard.reason}",
        )

    # ── PII scrub ─────────────────────────────────────────────────────────────
    clean_query, pii_count = pii_scrub(body.query)
    if pii_count:
        log.info("pii_removed_from_query", n=pii_count)

    # ── Cost controls ─────────────────────────────────────────────────────────
    redis = request.app.state.redis
    settings = request.app.state.pipeline._settings
    budget  = BudgetGuard(redis, settings)
    try:
        await budget.check(user_id)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))

    with tracer.start_as_current_span("rag.pipeline") as span:
        span.set_attribute("rag.query_length", len(clean_query))
        span.set_attribute("rag.top_n", body.top_n)
        span.set_attribute("rag.trace_id", trace_id)
        span.set_attribute("rag.pii_redacted", pii_count)
        span.set_attribute("rag.user_id", user_id)

        try:
            result = await pipeline.run(
                query=clean_query, top_n=body.top_n, trace_id=trace_id
            )
        except Exception as exc:
            rag_errors_total.labels(error_type=type(exc).__name__).inc()
            log.error("recommend_error", error=str(exc))
            raise

        elapsed = time.perf_counter() - t_start
        model   = result.get("model_used", "none")
        cached  = str(result.get("cached", False)).lower()

        span.set_attribute("rag.model_used", model)
        span.set_attribute("rag.cached", result.get("cached", False))
        span.set_attribute("rag.input_tokens", result.get("input_tokens", 0))
        span.set_attribute("rag.output_tokens", result.get("output_tokens", 0))

        rag_requests_total.labels(model=model, cached=cached).inc()
        rag_request_duration_seconds.observe(elapsed)

        log.info(
            "recommend_complete",
            model=model,
            cached=cached,
            duration_s=round(elapsed, 3),
            cost_usd=round(result.get("cost_usd", 0.0), 6),
        )

    # ── Record spend + audit ──────────────────────────────────────────────────
    cost = result.get("cost_usd", 0.0)
    asyncio.create_task(budget.record(user_id, cost))
    asyncio.create_task(
        write_audit(
            pool,
            user_id=user_id,
            query=clean_query[:512],
            model_used=model,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            cost_usd=cost,
            cached=result.get("cached", False),
            pii_redacted=pii_count,
            guard_blocked=False,
            trace_id=trace_id,
        )
    )

    sources = [Source(**s) for s in result.get("sources", [])]
    return RecommendResponse(
        answer=result.get("answer", ""),
        sources=sources,
        model_used=model,
        input_tokens=result.get("input_tokens", 0),
        output_tokens=result.get("output_tokens", 0),
        cost_usd=result.get("cost_usd", 0.0),
        cached=result.get("cached", False),
        trace_id=trace_id,
    )


@router.post("/recommend/stream")
async def recommend_stream(
    request: Request,
    body: RecommendRequest,
    claims: ClerkUser,
):
    """
    SSE stream — event types in `data:` JSON:
      {"type": "step",  "step": "retrieving"|...}
      {"type": "token", "content": "..."}
      {"type": "done",  "sources": [...], "model_used": "...", "cost_usd": 0.002,
                        "input_tokens": 123, "output_tokens": 456, "cached": false}
      {"type": "error", "message": "..."}
      data: [DONE]
    """
    pipeline: RAGPipeline = request.app.state.pipeline
    pool                  = request.app.state.db_pool
    trace_id = str(uuid.uuid4())
    user_id  = _user_id(claims)

    structlog.contextvars.bind_contextvars(trace_id=trace_id, user_id=user_id)

    # ── Guardrails ────────────────────────────────────────────────────────────
    guard = guard_check(body.query)
    if guard.blocked:
        log.warning("stream_blocked", reason=guard.reason)
        asyncio.create_task(
            write_audit(
                pool, user_id=user_id, query=body.query[:512], model_used="none",
                input_tokens=0, output_tokens=0, cost_usd=0.0, cached=False,
                pii_redacted=0, guard_blocked=True, trace_id=trace_id,
                extra={"block_reason": guard.reason},
            )
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Query rejected: {guard.reason}",
        )

    clean_query, pii_count = pii_scrub(body.query)
    log.info("stream_start", query=clean_query[:80], top_n=body.top_n)

    # ── Cost controls ─────────────────────────────────────────────────────────
    redis    = request.app.state.redis
    settings = pipeline._settings
    budget   = BudgetGuard(redis, settings)
    try:
        await budget.check(user_id)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))

    ks             = KillSwitch(redis)
    kill_active    = await ks.is_active()
    router_m       = ModelRouter(settings)
    model_override = router_m.select(clean_query, kill_active)
    log.info("model_selected", model=model_override, kill_switch=kill_active)

    # Collect done-event data for audit after streaming completes
    done_data: dict = {}

    async def event_stream():
        nonlocal done_data
        try:
            async for event in pipeline.run_stream(
                query=clean_query, top_n=body.top_n, trace_id=trace_id,
                model_override=model_override,
            ):
                if event.get("type") == "done":
                    done_data = event
                payload = {**event, "trace_id": trace_id}
                yield f"data: {json.dumps(payload, default=str)}\n\n"
        except Exception as exc:
            rag_errors_total.labels(error_type=type(exc).__name__).inc()
            log.error("stream_error", error=str(exc))
            error_payload = {"type": "error", "message": str(exc), "trace_id": trace_id}
            yield f"data: {json.dumps(error_payload)}\n\n"
        finally:
            yield "data: [DONE]\n\n"
            stream_cost = done_data.get("cost_usd", 0.0)
            asyncio.create_task(budget.record(user_id, stream_cost))
            asyncio.create_task(
                write_audit(
                    pool,
                    user_id=user_id,
                    query=clean_query[:512],
                    model_used=done_data.get("model_used", "none"),
                    input_tokens=done_data.get("input_tokens", 0),
                    output_tokens=done_data.get("output_tokens", 0),
                    cost_usd=stream_cost,
                    cached=done_data.get("cached", False),
                    pii_redacted=pii_count,
                    guard_blocked=False,
                    trace_id=trace_id,
                )
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
