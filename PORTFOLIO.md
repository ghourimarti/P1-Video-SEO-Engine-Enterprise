# Portfolio Write-up: Anime RAG — Enterprise Production Build

## What I built

A full-stack, production-grade Retrieval-Augmented Generation system — taken from a
bootcamp Streamlit prototype to a deployable enterprise system across 15 engineering
milestones. Every layer you would need to run a GenAI product in production is present
and production-credible, not tutorial-depth.

---

## The problem

Most GenAI portfolio projects stop at "it works on my machine." They lack:
- Real retrieval quality (dense + sparse, not just cosine similarity on 50 documents)
- LLM evaluation with CI gates (not "it looks good")
- Security (no PII handling, no prompt injection defence, no JWT auth)
- Cost controls (no budget enforcement, no model routing)
- Observability (no traces, no SLO dashboards, no drift detection)
- Deployment infrastructure (no K8s manifests, no GitOps, no canary strategy)

This project closes every one of those gaps.

---

## Technical depth, layer by layer

### Retrieval quality

Hybrid retrieval: dense embeddings via `text-embedding-3-large` stored in pgvector,
combined with PostgreSQL full-text search (tsvector + GIN index) using Reciprocal Rank
Fusion. Cohere Rerank v3 cross-encoder re-scores the top-20 candidates to top-5.
The retriever is wrapped in a LangGraph `StateGraph` with a query rewriter node
(expands underspecified queries) and a grader node (filters irrelevant passages before
generation). The result: relevant documents even for vague natural-language queries.

### LLM evaluation with CI gates

100-sample golden set in `packages/eval/golden/golden_set.json`.
RAGAS evaluates three metrics per PR: faithfulness, answer relevancy, context recall.
Any metric below 0.75 fails the CI job and blocks the merge. A promptfoo regression
suite (7 test cases including prompt injection resistance and PII absence) runs
alongside. Nightly GitHub Actions job runs the full golden set and opens a labelled
GitHub issue on regression.

### Security

- **JWT auth**: Clerk RS256 JWKS verification with a 5-minute in-process cache;
  dev bypass when `CLERK_JWKS_URL` is not set.
- **PII scrubbing**: Microsoft Presidio scrubs PERSON/EMAIL/PHONE/CREDIT_CARD/IBAN/
  IP_ADDRESS/SSN/PASSPORT from every query before it reaches the retriever or LLM.
  LOCATION intentionally excluded (anime queries legitimately reference "feudal Japan").
- **Prompt injection guardrails**: regex blocklist for role override, system prompt
  leakage, jailbreak personas, HTML injection, and base64-encoded payloads.
- **Audit log**: every request — including blocked ones — logged to Postgres with
  user ID, model, tokens, cost, PII count, guard result, and trace ID.
- **Security headers**: HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
  on every response.
- **Container hardening**: non-root UID 1001, read-only root filesystem, dropped
  capabilities, Trivy CRITICAL+HIGH gate in CI with SARIF upload to GitHub Security.

### Cost controls

Three-layer system: model routing, kill switch, and budget enforcement.

`ModelRouter` routes queries to `claude-haiku-4-5-20251001` (cheap) for short/simple
queries and `claude-sonnet-4-6` for queries > 30 words or containing analysis keywords.
The kill switch (a Redis flag) collapses all traffic to the cheap model in seconds —
useful during cost spikes or high-latency incidents. `BudgetGuard` tracks per-user
($1/day) and global ($50/day) spend in Redis with TTL = seconds until midnight UTC;
exceeding either returns HTTP 429. Fails open on Redis errors so infra outages never
deny service.

An admin API (`GET/POST /api/v1/admin/cost/kill-switch`,
`GET /api/v1/admin/cost/summary`) exposes operational controls without a database query
for the hot path.

### Observability

- **Structured logging**: structlog with JSON output, request_id and trace_id bound
  via context vars on every request.
- **OpenTelemetry**: distributed traces exported to Langfuse (LLM-specific: prompt,
  completion, model, cost, latency per span) and a local OTLP collector.
- **Prometheus + Grafana**: custom metrics (`rag_requests_total`, `rag_tokens_total`,
  `rag_cost_usd_total`, `rag_request_duration_seconds`) with a 10-panel SLO dashboard
  showing p50/p95/p99 latency, error rate, cache hit rate, cost/hour, token usage by
  model, and PgBouncer pool stats.
- **Embedding drift detection**: weekly GitHub Actions job computes mean cosine
  distance between the golden-set query distribution and recent production queries;
  opens a labelled issue with a remediation checklist if distance > 0.12.

### Infrastructure as Code

Six Terraform modules (networking, ECR, IAM, RDS, ElastiCache, EKS) wired via
Terragrunt with S3/DynamoDB remote state. Dev and prod environments differ in:
NAT gateway topology, RDS instance class and Multi-AZ, Redis node count, EKS node
group sizing, and API CIDR restrictions. All modules expose `mock_outputs` so
`terraform plan` works without real AWS credentials — safe for portfolio demonstration.

### Kubernetes and GitOps

Two Helm charts (API and web) with per-env values overrides. The API chart uses
Argo Rollouts `Rollout` in production (canary 20%→50%→100%) and a plain `Deployment`
in dev. Canary gates are Prometheus `AnalysisTemplate` metrics: p95 latency < 15 s
and error rate < 1%; three consecutive passes required before proceeding.

ArgoCD app-of-apps pattern: one root `Application` watches `infra/argocd/apps/` and
reconciles four child Applications. Dev auto-syncs; prod requires an explicit
`argocd app sync` call triggered by the CD workflow after the smoke test passes.

### CI/CD

Four GitHub Actions workflows:
- `ci.yaml` — lint (ruff, mypy, ESLint, tsc) → unit tests with live postgres+redis
  services → 10-sample RAGAS eval gate → Trivy container scan → Helm lint
- `cd.yaml` — OIDC AWS auth → ECR push (BuildKit, GHA cache) → ArgoCD dev sync +
  smoke test → GitHub Environment approval gate → ArgoCD prod sync → Rollouts canary
  wait → prod smoke test + auto-rollback on failure
- `eval-nightly.yaml` — full 100-sample RAGAS, GitHub step summary, issue on failure
- `model-drift.yaml` — embedding drift, 90-day artifact retention, issue with
  remediation checklist

### Scale validation

k6 SLO validation with three concurrent scenarios (health 5 VU constant, recommend
0→20 VU stepped ramp, stream 2 VU TTFB). Hard thresholds enforced as CI gates.
PgBouncer in transaction mode: 200 client connections → 20 Postgres server connections,
preventing connection exhaustion under concurrent load.

---

## Decisions I would explain in an interview

**Why pgvector instead of Pinecone/Weaviate?**
Postgres handles hybrid retrieval natively. RRF fusion of dense and sparse results
happens in SQL. Adding a separate vector database adds an operational dependency and
network hop without improving retrieval quality at this scale.

**Why LangGraph instead of a simple chain?**
The cache-check node must short-circuit the rest of the graph. LangGraph's conditional
edges express this cleanly. The stateful graph also makes it easy to inspect
intermediate state (which node failed, what the rewritten query was) in Langfuse traces.

**Why Argo Rollouts instead of a standard K8s rolling update?**
Prometheus-gated canary deployments automatically abort and roll back if p95 latency
or error rate spikes. A rolling update doesn't give you that signal until all pods
are updated — by which point the damage is done.

**Why does BudgetGuard fail open?**
A Redis outage is an infrastructure problem; it should not translate into a user-facing
`429`. The cost of a few unbudgeted requests during a Redis failure is lower than the
cost of denying service to legitimate users.

**Why Haiku by default, not Sonnet?**
Cost. Haiku is ~15× cheaper per token and fast enough for most anime recommendation
queries. The ModelRouter escalates to Sonnet only for queries that signal complex
reasoning (> 30 words, or contains comparison/analysis keywords). The kill switch
can force the entire fleet to Haiku in seconds during a cost event.

---

## Tech stack summary

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.11, uv |
| RAG pipeline | LangGraph, LiteLLM, Cohere Rerank v3 |
| LLMs | Anthropic Claude (Sonnet 4.6 / Haiku 4.5), Groq fallback |
| Embeddings | OpenAI text-embedding-3-large |
| Vector store | pgvector (Postgres 16) + full-text BM25 + RRF |
| Cache | Redis 7 (semantic cache cosine 0.92) |
| Auth | Clerk (RS256 JWKS) |
| PII / guardrails | Microsoft Presidio, custom regex guardrails |
| Frontend | Next.js 15, App Router, SSE streaming |
| Observability | structlog, OpenTelemetry, Langfuse, Prometheus, Grafana |
| Evaluation | RAGAS, Promptfoo, k6, custom embedding drift detector |
| Security scanning | Trivy (CRITICAL+HIGH, secrets, misconfigs) |
| IaC | Terraform + Terragrunt (6 modules, dev/prod envs) |
| Container | Docker multi-stage (non-root UID 1001, read-only fs) |
| Kubernetes | EKS 1.31, Karpenter, KEDA, ESO, Argo Rollouts |
| GitOps | ArgoCD app-of-apps |
| CI/CD | GitHub Actions (OIDC AWS auth, Buildx cache) |
| Connection pool | PgBouncer (transaction mode) |
| Cost controls | ModelRouter, KillSwitch, BudgetGuard (all Redis-backed) |

---

## What this demonstrates

1. **Retrieval engineering**: hybrid dense + sparse + rerank, not just
   `similarity_search()` on a toy corpus.
2. **Production eval discipline**: CI-gated RAGAS scores, regression suite,
   nightly monitoring, drift detection.
3. **Security instinct**: JWT, PII, injection, audit log, container hardening —
   applied correctly rather than checkbox-style.
4. **Cost engineering**: model routing, kill switch, budget enforcement, cost
   attribution dashboard — built for the real constraint of LLM token spend.
5. **Observability depth**: structured logs, distributed traces, Prometheus metrics,
   SLO dashboard, drift alerts — not just `print()` debugging.
6. **Infrastructure maturity**: real Terraform modules with remote state, Helm charts
   with per-env overrides, Argo Rollouts canary with automatic rollback.
7. **Engineering judgment**: every design decision has a documented rationale
   (see HANDOFF.md §5); tradeoffs are named, not hidden.
