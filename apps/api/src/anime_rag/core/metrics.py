"""Custom Prometheus metrics for the RAG pipeline.

Import and update these anywhere in the codebase. Prometheus client
handles thread/async safety automatically.

Panels these feed in Grafana (infra/monitoring/grafana/dashboards/anime_rag.json):
  1. Requests / sec           ← rag_requests_total
  2. P95 latency              ← rag_request_duration_seconds
  3. Cache hit rate           ← rag_cache_hits_total / rag_requests_total
  4. Error rate               ← rag_errors_total / rag_requests_total
  5. Token throughput         ← rag_tokens_total
  6. Estimated cost / hour    ← rag_cost_usd_total
  7. Retrieval duration       ← rag_retrieval_duration_seconds
  8. Model distribution       ← rag_requests_total by model label
"""

from prometheus_client import Counter, Histogram

# ── Request-level ─────────────────────────────────────────────────────────────

rag_requests_total = Counter(
    "rag_requests_total",
    "Total RAG recommendation requests",
    ["model", "cached"],
)

rag_request_duration_seconds = Histogram(
    "rag_request_duration_seconds",
    "End-to-end RAG request duration in seconds",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0],
)

rag_errors_total = Counter(
    "rag_errors_total",
    "Total failed RAG requests",
    ["error_type"],
)

# ── LLM cost / tokens ─────────────────────────────────────────────────────────

rag_tokens_total = Counter(
    "rag_tokens_total",
    "Total tokens processed by the LLM",
    ["model", "token_type"],   # token_type: "input" | "output"
)

rag_cost_usd_total = Counter(
    "rag_cost_usd_total",
    "Cumulative estimated LLM cost in USD",
    ["model"],
)

# ── Cache ─────────────────────────────────────────────────────────────────────

rag_cache_hits_total = Counter(
    "rag_cache_hits_total",
    "Cache hit count by tier",
    ["tier"],   # "exact" | "semantic"
)

# ── Retrieval ─────────────────────────────────────────────────────────────────

rag_retrieval_duration_seconds = Histogram(
    "rag_retrieval_duration_seconds",
    "Hybrid retrieval phase duration (embed + dense + BM25 + RRF + rerank)",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)

rag_retrieved_docs_count = Histogram(
    "rag_retrieved_docs_count",
    "Number of documents after reranking / grading",
    buckets=[0, 1, 2, 3, 5, 10, 20],
)
