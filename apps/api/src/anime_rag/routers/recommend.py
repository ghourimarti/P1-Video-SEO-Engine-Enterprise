"""Recommendation router — stub wired to a placeholder; replaced in M2."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from anime_rag.schemas.recommend import RecommendRequest, RecommendResponse

router = APIRouter()


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(request: Request, body: RecommendRequest):
    # M2: replace with LangGraph pipeline + streaming
    return RecommendResponse(
        answer="Pipeline not yet implemented — coming in M2.",
        sources=[],
        model_used="none",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        cached=False,
    )


@router.post("/recommend/stream")
async def recommend_stream(request: Request, body: RecommendRequest):
    # M2: replace with SSE streaming from LangGraph
    async def _placeholder():
        yield "data: Pipeline not yet implemented — coming in M2.\n\n"

    return StreamingResponse(_placeholder(), media_type="text/event-stream")
