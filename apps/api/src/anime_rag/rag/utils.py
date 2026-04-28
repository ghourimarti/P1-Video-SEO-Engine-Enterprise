"""Shared helpers reused across RAG nodes."""

from __future__ import annotations

from anime_rag.rag.state import AnimeDoc


def docs_to_context(docs: list[AnimeDoc]) -> str:
    parts = []
    for d in docs:
        genres    = ", ".join(d["genres"]) if d["genres"] else "N/A"
        score_str = f"{d['score']:.1f}" if d.get("score") else "N/A"
        parts.append(
            f"Title: {d['name']}\n"
            f"Score: {score_str}  Genres: {genres}\n"
            f"Synopsis: {d['synopsis']}"
        )
    return "\n\n---\n\n".join(parts)


def extract_citations(answer: str, docs: list[AnimeDoc]) -> set[int]:
    lower = answer.lower()
    return {d["mal_id"] for d in docs if d["name"].lower() in lower}


_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.25,  "output": 1.25},
    "groq/llama-3.1-8b-instant": {"input": 0.05,  "output": 0.08},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = _PRICING.get(model, {"input": 1.0, "output": 1.0})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def build_sources(docs: list[AnimeDoc], cited_ids: set[int]) -> list[dict]:
    return [
        {
            "mal_id":          d["mal_id"],
            "name":            d["name"],
            "score":           d.get("score"),
            "genres":          d.get("genres", []),
            "relevance_score": d.get("similarity"),
            "cited":           d["mal_id"] in cited_ids,
        }
        for d in docs
    ]
