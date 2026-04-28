"""Response generation node with citation extraction."""

from __future__ import annotations

import structlog
import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

from anime_rag.core.settings import Settings
from anime_rag.rag.state import AnimeDoc, RAGState

log = structlog.get_logger(__name__)

_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6":           {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5-20251001":   {"input": 0.25,  "output": 1.25},
    "groq/llama-3.1-8b-instant":   {"input": 0.05,  "output": 0.08},
}

_SYSTEM = """\
You are an expert anime recommendation assistant. Using ONLY the anime listed
in the context below, recommend exactly {top_n} anime that best match the user's
preferences. For each recommendation provide:
1. **Title** — exact title from the context (must match exactly).
2. **Synopsis** — one sentence distilled from the synopsis.
3. **Why this fits** — one sentence tied directly to the user's query.

Do NOT invent titles not present in the context. Format as a numbered markdown list."""

_HUMAN = """\
Context:
{context}

My preferences: {query}

Give me your top {top_n} recommendations."""


def _docs_to_context(docs: list[AnimeDoc]) -> str:
    parts = []
    for d in docs:
        genres = ", ".join(d["genres"]) if d["genres"] else "N/A"
        score_str = f"{d['score']:.1f}" if d.get("score") else "N/A"
        parts.append(
            f"Title: {d['name']}\n"
            f"Score: {score_str}  Genres: {genres}\n"
            f"Synopsis: {d['synopsis']}"
        )
    return "\n\n---\n\n".join(parts)


def _extract_citations(answer: str, docs: list[AnimeDoc]) -> set[int]:
    """Return mal_ids whose title appears verbatim (case-insensitive) in the answer."""
    lower_answer = answer.lower()
    return {d["mal_id"] for d in docs if d["name"].lower() in lower_answer}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = _PRICING.get(model, {"input": 1.0, "output": 1.0})
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


def make_generator(settings: Settings):
    """Return a LangGraph node that generates an answer with citations."""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _call_llm(model: str, messages: list[dict], max_tokens: int):
        return await litellm.acompletion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )

    async def generate(state: RAGState) -> dict:
        # Respect grader decision
        if not state.get("grader_passed", True):
            return {
                "answer": (
                    "I couldn't find anime that closely match your query. "
                    "Try rephrasing or broadening your preferences."
                ),
                "sources": [],
                "model_used": "none",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "cached": False,
            }

        docs = state.get("documents", [])
        if not docs:
            return {
                "answer": "No relevant anime found for your query. Try rephrasing.",
                "sources": [],
                "model_used": "none",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "cached": False,
            }

        query = state.get("rewritten_query") or state["query"]
        top_n = state.get("top_n", 5)
        context = _docs_to_context(docs)

        messages = [
            {"role": "system", "content": _SYSTEM.format(top_n=top_n)},
            {"role": "user",   "content": _HUMAN.format(context=context, query=query, top_n=top_n)},
        ]

        model = settings.default_model
        try:
            resp = await _call_llm(model, messages, settings.max_output_tokens)
        except Exception:
            log.warning("primary_model_failed", model=model, fallback=settings.fallback_model)
            model = settings.fallback_model
            resp = await _call_llm(model, messages, settings.max_output_tokens)

        answer = resp.choices[0].message.content.strip()
        usage = resp.usage
        input_tok  = usage.prompt_tokens if usage else 0
        output_tok = usage.completion_tokens if usage else 0
        cost = _estimate_cost(model, input_tok, output_tok)

        # Citation extraction — which titles appear verbatim in the answer?
        cited_ids = _extract_citations(answer, docs)

        sources = [
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

        log.info(
            "generated",
            model=model,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cost_usd=round(cost, 6),
            cited_n=len(cited_ids),
        )

        return {
            "answer":       answer,
            "sources":      sources,
            "model_used":   model,
            "input_tokens": input_tok,
            "output_tokens":output_tok,
            "cost_usd":     cost,
            "cached":       False,
        }

    return generate
