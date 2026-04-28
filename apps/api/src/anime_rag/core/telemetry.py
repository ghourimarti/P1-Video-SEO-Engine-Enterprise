"""OpenTelemetry setup — TracerProvider, OTLP exporter, auto-instrumentation.

Call setup_telemetry() once at app startup, passing the FastAPI app instance.
Returns a module-level tracer for use in routers and nodes.

Exports:
  - Traces → OTLP gRPC endpoint (Grafana Tempo in docker-compose, or any
    OpenTelemetry Collector in production)
  - Auto-instruments: FastAPI routes, httpx (catches LiteLLM + LangChain calls)

When OTEL_EXPORTER_OTLP_ENDPOINT is not set or unreachable, a no-op
tracer is used — the app runs normally with no tracing overhead.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

log = structlog.get_logger(__name__)

# Module-level tracer — import this wherever you need custom spans
tracer: trace.Tracer = trace.get_tracer("anime_rag")


def setup_telemetry(app: FastAPI, service_name: str, otlp_endpoint: str) -> None:
    """Configure OTel and instrument the FastAPI app. Idempotent."""

    resource = Resource.create(
        {
            SERVICE_NAME:    service_name,
            SERVICE_VERSION: "0.5.0",
        }
    )

    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            log.info("otel_exporter_configured", endpoint=otlp_endpoint)
        except Exception as exc:
            log.warning("otel_exporter_failed", error=str(exc))
    else:
        log.info("otel_no_exporter", reason="OTEL_EXPORTER_OTLP_ENDPOINT not set")

    trace.set_tracer_provider(provider)

    # Update the module-level tracer to use the configured provider
    global tracer
    tracer = trace.get_tracer("anime_rag", tracer_provider=provider)

    # Auto-instrument FastAPI (adds spans for all routes)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="/health,/ready,/metrics",
    )

    # Auto-instrument httpx (catches LiteLLM + LangChain outbound calls)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)

    log.info("otel_setup_complete", service=service_name)
