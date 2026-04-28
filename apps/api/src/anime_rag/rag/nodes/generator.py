"""Response generation node — LiteLLM with metrics + Langfuse metadata."""

from __future__ import annotations

import structlog
import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

from anime_rag.core.metrics import rag_tokens_total, rag_cost_usd_total
from anime_rag.core.settings import Settings
from anime_rag.rag.state import RAGState
from anime_rag.rag.utils import docs_to_context, extract_citations, estimate_cost, build_sources

log = structlog.get_logger(__name__)

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


def make_generator(settings: Settings):

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
    async def _call_llm(model: str, messages: list[dict], max_tokens: int, metadata: dict):
        return await litellm.acompletion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
            metadata=metadata,
        )

    async def generate(state: RAGState) -> dict:
        if not state.get("grader_passed", True):
            return {
                "answer": (
                    "I couldn't find anime that closely match your query. "
                    "Try rephrasing or broadening your preferences."
                ),
                "sources": [], "model_used": "none",
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "cached": False,
            }

        docs = state.get("documents", [])
        if not docs:
            return {
                "answer": "No relevant anime found for your query. Try rephrasing.",
                "sources": [], "model_used": "none",
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "cached": False,
            }

        query = state.get("rewritten_query") or state["query"]
        top_n = state.get("top_n", 5)

        messages = [
            {"role": "system", "content": _SYSTEM.format(top_n=top_n)},
            {"role": "user",   "content": _HUMAN.format(
                context=docs_to_context(docs), query=query, top_n=top_n
            )},
        ]

        lf_metadata = {
            "generation_name": "anime-recommend",
            "prompt_version":  "v1",
            "trace_id":        state.get("trace_id"),
        }

        model = settings.default_model
        try:
            resp = await _call_llm(model, messages, settings.max_output_tokens, lf_metadata)
        except Exception:
            log.warning("primary_model_failed", model=model, fallback=settings.fallback_model)
            model = settings.fallback_model
            resp = await _call_llm(model, messages, settings.max_output_tokens, lf_metadata)

        answer     = resp.choices[0].message.content.strip()
        usage      = resp.usage
        input_tok  = usage.prompt_tokens     if usage else 0
        output_tok = usage.completion_tokens if usage else 0
        cost       = estimate_cost(model, input_tok, output_tok)

        rag_tokens_total.labels(model=model, token_type="input").inc(input_tok)
        rag_tokens_total.labels(model=model, token_type="output").inc(output_tok)
        rag_cost_usd_total.labels(model=model).inc(cost)

        cited_ids = extract_citations(answer, docs)
        sources   = build_sources(docs, cited_ids)

        log.info(
            "generated",
            model=model,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cost_usd=round(cost, 6),
            cited_n=len(cited_ids),
        )

        return {
            "answer":        answer,
            "sources":       sources,
            "model_used":    model,
            "input_tokens":  input_tok,
            "output_tokens": output_tok,
            "cost_usd":      cost,
            "cached":        False,
        }

    return generate
