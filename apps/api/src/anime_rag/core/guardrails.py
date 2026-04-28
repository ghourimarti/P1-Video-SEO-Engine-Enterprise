"""Prompt injection detection and query guardrails.

Two layers:
1. Keyword/pattern blocklist — fast, zero-latency regex scan.
2. Structural heuristics — catches common jailbreak patterns
   (role override, instruction smuggling, base64 payloads).

Returns a GuardResult with `blocked: bool` and a `reason` string.
No LLM call is made — this runs before the RAG pipeline.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

import structlog

log = structlog.get_logger(__name__)

# ── Blocklist patterns ────────────────────────────────────────────────────────
# Each tuple: (human-readable label, compiled regex)
_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Role override attempts
    ("role_override",       re.compile(r"\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context)", re.I)),
    ("system_prompt_leak",  re.compile(r"\b(print|repeat|reveal|show|output|display)\b.{0,20}?\b(system\s+prompt|instructions?|initial\s+prompt)\b", re.I)),
    # Jailbreak personas
    ("persona_jailbreak",   re.compile(r"\b(dan|jailbreak|do\s+anything\s+now|developer\s+mode|god\s+mode|unrestricted\s+mode)\b", re.I)),
    # Instruction smuggling via markdown/html
    ("html_injection",      re.compile(r"<\s*(script|iframe|object|embed|form|input)\b", re.I)),
    # Excessive special chars (common in many injection payloads)
    ("special_char_flood",  re.compile(r"[^\w\s,.!?'\-]{10,}")),
]

# ── Heuristics ────────────────────────────────────────────────────────────────
_MAX_QUERY_LEN = 512          # enforced by schema, but double-checked here
_MAX_NEWLINES  = 15           # legitimate queries rarely have many newlines
_B64_MIN_LEN   = 40           # minimum length to bother decoding


def _looks_like_base64(text: str) -> bool:
    """Return True if any word in text decodes to a long printable string."""
    for token in text.split():
        if len(token) < _B64_MIN_LEN:
            continue
        try:
            decoded = base64.b64decode(token + "==", validate=True).decode("utf-8", errors="strict")
            if len(decoded) > 20 and decoded.isprintable():
                return True
        except Exception:
            pass
    return False


@dataclass
class GuardResult:
    blocked: bool
    reason: str = ""


def check(query: str) -> GuardResult:
    """Run all guard checks on the raw user query string."""

    if len(query) > _MAX_QUERY_LEN:
        return GuardResult(blocked=True, reason="query_too_long")

    if query.count("\n") > _MAX_NEWLINES:
        return GuardResult(blocked=True, reason="excessive_newlines")

    for label, pattern in _PATTERNS:
        if pattern.search(query):
            log.warning("prompt_injection_detected", pattern=label, query_snippet=query[:80])
            return GuardResult(blocked=True, reason=label)

    if _looks_like_base64(query):
        log.warning("prompt_injection_detected", pattern="base64_payload", query_snippet=query[:80])
        return GuardResult(blocked=True, reason="base64_payload")

    return GuardResult(blocked=False)
