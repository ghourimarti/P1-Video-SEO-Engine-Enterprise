"""Recommendation router — OTel span + Prometheus request metrics."""

import json
import time
import uuid

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from opentelemetry import trace

from anime_rag.core.metrics import (
    rag_requests_total,
    rag_request_duration_seconds,
    rag_errors_total,
)
from anime_rag.rag.pipeline import RAGPipeline
from anime_rag.schemas.recommend import RecommendRequest, RecommendResponse, Source

router = APIRouter()
log = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(request: Request, body: RecommendRequest):
    pipeline: RAGPipeline = request.app.state.pipeline
    trace_id = str(uuid.uuid4())
    t_start = time.perf_counter()

    structlog.contextvars.bind_contextvars(trace_id=trace_id)
    log.info("recommend_start", query=body.query[:80], top_n=body.top_n)

    with tracer.start_as_current_span("rag.pipeline") as span:
        span.set_attribute("rag.query_length", len(body.query))
        span.set_attribute("rag.top_n", body.top_n)
        span.set_attribute("rag.trace_id", trace_id)

        try:
            result = await pipeline.run(
                query=body.query, top_n=body.top_n, trace_id=trace_id
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
async def recommend_stream(request: Request, body: RecommendRequest):
    pipeline: RAGPipeline = request.app.state.pipeline
    trace_id = str(uuid.uuid4())

    async def event_stream():
        async for chunk in pipeline.run_stream(
            query=body.query, top_n=body.top_n, trace_id=trace_id
        ):
            for node_name, update in chunk.items():
                payload = {"node": node_name, "data": update, "trace_id": trace_id}
                yield f"data: {json.dumps(payload, default=str)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
