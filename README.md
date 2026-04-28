# Anime RAG — Enterprise Production Build

> Transformed from a bootcamp Streamlit prototype into a production-grade RAG system.
> Demonstrates the full stack required for enterprise GenAI: hybrid retrieval, LLM
> observability, security guardrails, autoscaling Kubernetes, and CI-gated evaluation.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Next.js 15 (App Router)  ·  Clerk auth  ·  SSE streaming   │  apps/web
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP / SSE
┌────────────────────────────▼────────────────────────────────┐
│  FastAPI  ·  LangGraph RAG pipeline  ·  LiteLLM routing      │  apps/api
│  Hybrid retrieval: pgvector + BM25 + RRF + Cohere reranker  │
│  Security: JWT middleware · rate limit · PII · guardrails    │
└──────┬──────────────┬──────────────┬──────────────┬─────────┘
       │              │              │              │
  Postgres 16     Redis 7       Langfuse        Prometheus
  (pgvector)  (semantic cache) (LLM traces)    + Grafana
```

## Milestone Map

| # | Milestone | Status |
|---|---|---|
| M0 | Clean up original repo (remove blobs, add .env.example) | ✅ Done |
| M1 | Project scaffold (this repo) | ✅ Done |
| M2 | FastAPI backend + LangGraph RAG pipeline + pgvector ingestion + Alembic | ✅ Done |
| M3 | Hybrid retrieval (BM25 + dense + RRF + Cohere reranker + query rewrite) | ✅ Done |
| M4 | Redis semantic cache + Docker Compose full stack | ✅ Done |
| M5 | structlog + OpenTelemetry + Langfuse self-hosted + Prometheus/Grafana | ✅ Done |
| M6 | Next.js frontend + Clerk + SSE streaming + citations UI | ✅ Done |
| M7 | Security layer (JWT, rate limiting, PII detection, prompt injection, audit log) | ✅ Done |
| M8 | Testing + RAGAS golden eval (100 samples) + Promptfoo + k6 | ✅ Done |
| M9 | Multi-stage Dockerfiles (non-root, layer-cached, trivy scan) | ✅ Done |
| M10 | Terraform + Terragrunt IaC (EKS, RDS, ElastiCache, ECR, IAM) | 🔜 |
| M11 | Helm charts + ArgoCD app-of-apps + Argo Rollouts canary | 🔜 |
| M12 | GitHub Actions CI/CD (lint → test → eval gate → deploy) | 🔜 |
| M13 | Cost controls (token budgets, model routing, kill switch) | 🔜 |
| M14 | Scale validation (k6 ramp, SLOs, PgBouncer, runbooks) | 🔜 |
| M15 | Production hardening sweep + HANDOFF.md + PORTFOLIO.md | 🔜 |

## Quick Start (local development)

```bash
# 1. Install deps
make install

# 2. Copy env
cp .env.example .env
# Fill in GROQ_API_KEY, OPENAI_API_KEY (for embeddings), ANTHROPIC_API_KEY

# 3. Start stack
make up
# API docs  → http://localhost:8000/docs
# Langfuse  → http://localhost:3001
# Grafana   → http://localhost:3000

# 4. Ingest data (M2 — available after milestone 2)
make seed

# 5. Run tests
make test

# 6. Lint
make lint
```

## Project Layout

```
P1-Anime-Recommender-Enterprise/
├── apps/
│   ├── api/          # FastAPI backend (Python 3.11, uv)
│   └── web/          # Next.js 15 frontend (pnpm)
├── packages/
│   ├── prompts/      # Versioned YAML prompt templates
│   └── eval/         # RAGAS offline evaluation
├── infra/
│   ├── terraform/    # IaC (modules + Terragrunt envs)
│   ├── helm/         # Kubernetes Helm charts
│   └── monitoring/   # Prometheus + Grafana config
├── scripts/
│   ├── init_db.sql   # Postgres bootstrap (pgvector + full-text indexes)
│   ├── ingest.py     # CSV → pgvector ingestion
│   └── load_test/    # k6 load test scripts
├── data/             # anime_with_synopsis.csv (269 titles, MAL data)
├── docs/             # Architecture docs, ADRs, runbooks
└── .github/workflows/# CI/CD pipelines
```

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| LLM routing | LiteLLM | Haiku→Sonnet→Groq cascading, cost control |
| Embeddings | text-embedding-3-large | Best MTEB score in OpenAI family |
| Vector DB | pgvector (Postgres 16) | Hybrid retrieval without a separate service |
| Full-text | tsvector + GIN index | BM25 over synopsis at zero added infra |
| Reranker | Cohere Rerank v3 | Cross-encoder quality at API cost |
| RAG orchestration | LangGraph | Stateful: rewrite → retrieve → grade → generate |
| Cache | Redis 7 | Semantic cache (cosine 0.92) + rate limiting |
| Auth | Clerk | JWT verification, zero auth-server ops |
| Observability | Langfuse + OTel + Prometheus | LLM traces + app metrics + Grafana dashboards |
| Security | Presidio + Guardrails AI | PII redaction + output validation |
| IaC | Terraform + Terragrunt | DRY multi-env (dev/prod) |
| K8s | EKS 1.31 + Karpenter + KEDA | Node + pod autoscaling |
| CI/CD | GitHub Actions + ArgoCD | GitOps with canary rollbacks |
| Eval | RAGAS + Promptfoo | CI-gated quality gate (faithfulness ≥ 0.75) |

## Original Project

The bootcamp prototype this was built from:
[P1-Video-SEO-Engine](../P1-Video-SEO-Engine/) — Streamlit + ChromaDB + deprecated RetrievalQA
