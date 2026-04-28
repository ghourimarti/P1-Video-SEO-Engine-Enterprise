# Handoff Document — Anime RAG Enterprise

> Complete operational guide for anyone taking ownership of this system.
> Read this before touching production.

---

## 1. What this system does

A production-grade Retrieval-Augmented Generation (RAG) API that recommends anime
based on natural-language queries. A Next.js frontend streams responses token-by-token
via Server-Sent Events. The system is built to demonstrate every layer of a real
enterprise GenAI stack: retrieval quality, security, observability, cost control,
autoscaling, and CI-gated evaluation.

**It is not deployed to real AWS** — all infrastructure is defined as Terraform/Terragrunt
IaC for portfolio demonstration. The local Docker Compose stack is fully functional.

---

## 2. Repository layout

```
P1-Anime-Recommender-Enterprise/
├── apps/
│   ├── api/          FastAPI backend (Python 3.11 + uv)
│   └── web/          Next.js 15 frontend (pnpm)
├── packages/
│   ├── prompts/      Versioned YAML prompt templates
│   └── eval/         RAGAS offline eval + embedding drift detector
├── infra/
│   ├── terraform/    Modules (networking/ecr/iam/rds/elasticache/eks)
│   │                 + Terragrunt envs (dev/prod)
│   ├── helm/         Helm charts (anime-rag-api, anime-rag-web)
│   ├── argocd/       App-of-apps + child Applications (dev/prod × api/web)
│   ├── monitoring/   Prometheus config + Grafana dashboards
│   ├── pgbouncer/    PgBouncer connection pool config
│   └── trivy/        Container scan config
├── scripts/
│   ├── init_db.sql   Postgres bootstrap (pgvector + FTS indexes)
│   ├── ingest.py     CSV → pgvector ingestion
│   └── load_test/    k6 scripts (smoke, full, slo-validation)
├── docs/
│   └── runbooks/     5 operational runbooks (latency, budget, drift, quality, node)
├── .github/workflows/ ci.yaml, cd.yaml, eval-nightly.yaml, model-drift.yaml
└── data/             anime_with_synopsis.csv (269 titles, MAL data)
```

---

## 3. Local development

### Prerequisites

| Tool | Min version |
|---|---|
| Docker + Compose | 24.x |
| Python | 3.11 |
| uv | 0.4.x |
| Node.js | 20.x |
| pnpm | 9.x |

### First run

```bash
# 1. Install all deps
make install

# 2. Copy and fill env
cp .env.example .env
# Required: ANTHROPIC_API_KEY, OPENAI_API_KEY, COHERE_API_KEY

# 3. Start core stack (postgres + redis + api)
make up

# 4. Run migrations + seed data
make alembic-upgrade
make seed

# 5. Open http://localhost:8000/docs
```

### Add observability (optional)

```bash
docker compose --profile observability up -d
# Langfuse → http://localhost:3001
# Prometheus → http://localhost:9090
# Grafana → http://localhost:3002
```

### Add frontend (optional — requires Clerk keys)

```bash
docker compose --profile web up -d web
# Web → http://localhost:3000
```

### Useful commands

```bash
make test           # pytest (unit + integration)
make lint           # ruff + mypy
make eval           # RAGAS offline eval (10 samples)
make load-test-slo  # k6 SLO validation (requires running stack)
make cost-summary   # today's cost from audit_log
make kill-switch-on # force all traffic to cheap model
make trivy-scan     # container vulnerability scan
```

---

## 4. Architecture — data flow

```
User query
    │
    ▼
Next.js (SSE client) ──HTTPS──► FastAPI
                                    │
                         ┌──────────┴──────────┐
                         │   Security layer     │
                         │  JWT · PII · guards  │
                         │  budget check        │
                         └──────────┬──────────┘
                                    │
                         ┌──────────┴──────────┐
                         │  LangGraph pipeline  │
                         │  cache_check         │ ◄── Redis semantic cache
                         │  rewrite             │ ◄── LiteLLM (Haiku)
                         │  retrieve            │ ◄── pgvector + BM25 + RRF
                         │  grade               │ ◄── LiteLLM (Haiku)
                         │  generate            │ ◄── LiteLLM (Haiku/Sonnet)
                         │  cache_write         │ ──► Redis
                         └──────────┬──────────┘
                                    │
                         audit_log (Postgres) + OTel traces (Langfuse)
                         Prometheus metrics ──► Grafana SLO dashboard
```

---

## 5. Key design decisions

| Decision | Rationale |
|---|---|
| pgvector over a dedicated vector DB | Postgres handles hybrid retrieval (dense + BM25 + RRF) without a separate service |
| LangGraph over LangChain LCEL chains | Stateful graph with conditional edges; cache check is a first-class node |
| LiteLLM for LLM calls | Single interface for Anthropic/OpenAI/Groq; model switching via config |
| Clerk for auth | Zero auth-server ops; RS256 JWKS verification in the API |
| Argo Rollouts canary | p95 + error rate Prometheus gates before full traffic shift |
| Terragrunt | DRY multi-env (dev/prod) over raw Terraform modules |
| BudgetGuard fails open | Redis outage must never deny service to users |

---

## 6. Secret management

### Local development

All secrets live in `.env` (git-ignored). See `.env.example` for all required keys.

### Production (Kubernetes)

Secrets are stored in **AWS Secrets Manager** under keys:
- `anime-rag/prod/api/secrets` — API secrets (DB password, API keys, Clerk secret)
- `anime-rag/dev/api/secrets` — dev equivalents

**External Secrets Operator (ESO)** syncs them into Kubernetes `Secret` objects
every hour (configurable via `externalSecret.refreshInterval` in Helm values).

The API pod reads them via `envFrom.secretRef` — they never appear in plaintext
in any manifest.

### Rotating secrets

```bash
# 1. Update the secret in AWS Secrets Manager
aws secretsmanager put-secret-value \
  --secret-id anime-rag/prod/api/secrets \
  --secret-string '{"ANTHROPIC_API_KEY":"sk-ant-new..."}'

# 2. Force ESO to re-sync immediately
kubectl annotate externalsecret anime-rag-api-secrets \
  force-sync=$(date +%s) -n anime-rag-prod

# 3. Restart the API pods to pick up the new env
kubectl rollout restart deployment/anime-rag-api -n anime-rag-prod
```

---

## 7. Deployment

### Dev (auto-deploys on every push to main)

The `cd.yaml` GitHub Actions workflow:
1. Builds API + web Docker images → pushes to ECR with `sha-<8-char>` tags
2. Calls `argocd app sync dev-api` + `argocd app sync dev-web`
3. Runs smoke test against the dev API URL

### Production (requires manual approval)

The same workflow, after dev smoke test passes:
1. Waits for GitHub Environment approval (`prod` environment in repo settings)
2. `argocd app sync prod-api` → triggers Argo Rollouts canary
3. Canary: 20% traffic → 2 min pause → Prometheus analysis → 50% → analysis → 100%
4. Analysis gates: p95 latency < 15 s AND error rate < 1 %
5. On failure: rollout aborted and undone automatically

### Required GitHub secrets

| Secret | Description |
|---|---|
| `AWS_ACCOUNT_ID` | 12-digit AWS account ID |
| `AWS_DEPLOY_ROLE_ARN` | IAM role for OIDC-based ECR + EKS access |
| `ARGOCD_SERVER` | ArgoCD server address |
| `ARGOCD_AUTH_TOKEN` | ArgoCD API token |
| `DEV_API_URL` | Dev API public URL (for smoke test) |
| `PROD_API_URL` | Prod API public URL |
| `OPENAI_API_KEY` | For CI eval jobs |
| `ANTHROPIC_API_KEY` | For CI eval jobs |

---

## 8. Operational runbooks

| Scenario | Runbook |
|---|---|
| p95 latency > 15 s | [docs/runbooks/high-latency.md](docs/runbooks/high-latency.md) |
| Budget 429 spike | [docs/runbooks/budget-exhausted.md](docs/runbooks/budget-exhausted.md) |
| Embedding drift alert | [docs/runbooks/embedding-drift.md](docs/runbooks/embedding-drift.md) |
| RAGAS quality regression | [docs/runbooks/ragas-regression.md](docs/runbooks/ragas-regression.md) |
| Node failure / CrashLoop | [docs/runbooks/node-failure.md](docs/runbooks/node-failure.md) |

---

## 9. Monitoring

**Grafana** (local: http://localhost:3002, prod: Grafana Cloud or self-hosted):
- **SLO Dashboard** — p95 latency, error rate, cache hit rate, cost/hour
- **Anime RAG Dashboard** — tokens by model, request rate, cost

**Langfuse** (local: http://localhost:3001):
- Every LLM call traced with prompt/completion/cost/latency
- Trace ID propagated through the full request → easy correlation

**GitHub Actions nightly jobs**:
- `eval-nightly.yaml` — RAGAS full golden-set eval (100 samples), opens issue on regression
- `model-drift.yaml` — embedding drift check, opens issue if distance > 0.12

---

## 10. Known limitations and future work

| Limitation | Impact | Suggested fix |
|---|---|---|
| No real AWS deployment | Portfolio only | Provision with `terragrunt run-all apply` on real account |
| 269-title corpus | Recommendations limited to MAL sample | Ingest full MAL dataset (~17 000 titles) |
| Single-region | No geo-redundancy | Add Route 53 failover to second region |
| PgBouncer in docker-compose only | No K8s sidecar | Add PgBouncer as a sidecar container in the API Helm chart |
| Admin endpoints unauthenticated | Anyone can toggle kill switch | Add admin JWT claim check to cost router |
| RAGAS uses gpt-4o-mini judge | Cost ~$0.15/eval run | Acceptable; use self-hosted judge for high-volume |
| Karpenter v1beta1 API | Will need migration to v1 API | Update EC2NodeClass + NodePool manifests for Karpenter ≥ 1.0 |
