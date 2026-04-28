"""Recommendation router — wired to the live RAGPipeline."""

import json
import uuid

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from anime_rag.rag.pipeline import RAGPipeline
from anime_rag.schemas.recommend import RecommendRequest, RecommendResponse, Source

router = APIRouter()
log = structlog.get_logger(__name__)


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(request: Request, body: RecommendRequest):
    pipeline: RAGPipeline = request.app.state.pipeline
    trace_id = str(uuid.uuid4())

    log.info("recommend_request", query=body.query[:80], top_n=body.top_n, trace_id=trace_id)

    result = await pipeline.run(query=body.query, top_n=body.top_n)

    if result.get("error"):
        log.error("pipeline_error", error=result["error"], trace_id=trace_id)

    sources = [Source(**s) for s in result.get("sources", [])]

    return RecommendResponse(
        answer=result.get("answer", ""),
        sources=sources,
        model_used=result.get("model_used", ""),
        input_tokens=result.get("input_tokens", 0),
        output_tokens=result.get("output_tokens", 0),
        cost_usd=result.get("cost_usd", 0.0),
        cached=result.get("cached", False),
        trace_id=trace_id,
    )


@router.post("/recommend/stream")
async def recommend_stream(request: Request, body: RecommendRequest):
    """SSE endpoint — streams node updates from LangGraph.

    Full token-level streaming implemented in M6.
    Currently streams one event per graph node completion.
    """
    pipeline: RAGPipeline = request.app.state.pipeline
    trace_id = str(uuid.uuid4())

    async def event_stream():
        async for chunk in pipeline.run_stream(query=body.query, top_n=body.top_n):
            # Each chunk is {node_name: state_update}
            for node_name, update in chunk.items():
                payload = {"node": node_name, "data": update, "trace_id": trace_id}
                yield f"data: {json.dumps(payload, default=str)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
