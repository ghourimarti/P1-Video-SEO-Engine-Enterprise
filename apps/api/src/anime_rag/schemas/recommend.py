from pydantic import BaseModel, Field


class Source(BaseModel):
    mal_id: int
    name: str
    score: float | None = None
    genres: list[str] = []
    relevance_score: float | None = None
    cited: bool = False        # True if the title appears verbatim in the answer


class RecommendRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=512)
    top_n: int = Field(default=5, ge=1, le=10)
    stream: bool = False


class RecommendResponse(BaseModel):
    answer: str
    sources: list[Source]
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cached: bool
    trace_id: str | None = None
