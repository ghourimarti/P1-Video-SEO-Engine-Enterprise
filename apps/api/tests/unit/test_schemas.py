"""Unit tests for Pydantic v2 request/response schemas."""

import pytest
from pydantic import ValidationError

from anime_rag.schemas.recommend import RecommendRequest, RecommendResponse, Source


class TestRecommendRequest:
    def test_valid(self):
        r = RecommendRequest(query="action anime with great animation", top_n=5)
        assert r.query == "action anime with great animation"
        assert r.top_n == 5

    def test_defaults(self):
        r = RecommendRequest(query="mecha series")
        assert r.top_n == 5
        assert r.stream is False

    def test_query_too_short(self):
        with pytest.raises(ValidationError):
            RecommendRequest(query="ab")  # min_length=3

    def test_query_too_long(self):
        with pytest.raises(ValidationError):
            RecommendRequest(query="x" * 513)  # max_length=512

    def test_top_n_bounds(self):
        with pytest.raises(ValidationError):
            RecommendRequest(query="valid query", top_n=0)  # ge=1
        with pytest.raises(ValidationError):
            RecommendRequest(query="valid query", top_n=11)  # le=10


class TestRecommendResponse:
    def test_valid_full(self):
        r = RecommendResponse(
            answer="Here are your recommendations...",
            sources=[
                Source(
                    mal_id=5114,
                    name="Fullmetal Alchemist: Brotherhood",
                    score=9.1,
                    genres=["Action", "Adventure"],
                    relevance_score=0.95,
                )
            ],
            model_used="claude-sonnet-4-6",
            input_tokens=512,
            output_tokens=256,
            cost_usd=0.000384,
            cached=False,
            trace_id="abc-123",
        )
        assert r.answer.startswith("Here")
        assert len(r.sources) == 1
        assert r.sources[0].mal_id == 5114

    def test_empty_sources(self):
        r = RecommendResponse(
            answer="No results found.",
            sources=[],
            model_used="none",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            cached=False,
        )
        assert r.sources == []
        assert r.trace_id is None
