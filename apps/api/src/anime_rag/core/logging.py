"""Structured logging configuration — structlog with OTel trace_id correlation.

Call setup_logging() once at app startup (before the first log statement).

In development:  coloured ConsoleRenderer (human-readable)
In production:   JSON lines (machine-parseable; shipped to Loki / CloudWatch)

OTel trace_id / span_id are automatically injected into every log record
when a request is being processed, enabling log ↔ trace correlation in
Grafana.
"""

from __future__ import annotations

import logging
import uuid

import structlog
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


# ── OTel → structlog bridge ────────────────────────────────────────────────────

def _inject_otel_ids(logger, method, event_dict: dict) -> dict:
    """Structlog processor: add trace_id + span_id from the active OTel span."""
    span = trace.get_current_span()
    if span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"]  = format(ctx.span_id,  "016x")
    return event_dict


# ── Setup ──────────────────────────────────────────────────────────────────────

def setup_logging(log_level: str = "INFO", environment: str = "development") -> None:
    """Configure structlog for the whole process. Call exactly once."""

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _inject_otel_ids,
    ]

    if environment == "development":
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib `logging` into structlog so third-party libs are captured
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# ── Request context middleware ─────────────────────────────────────────────────

class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request_id, path, and method to structlog context vars per request.

    This means every log statement during request handling automatically
    includes these fields — no manual passing required.
    """

    async def dispatch(self, request: Request, call_next):
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request.headers.get("X-Request-ID", str(uuid.uuid4())),
            path=request.url.path,
            method=request.method,
        )
        response = await call_next(request)
        structlog.contextvars.unbind_contextvars("request_id", "path", "method")
        return response
