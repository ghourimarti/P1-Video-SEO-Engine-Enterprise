.PHONY: help install up down build logs lint test eval load-test load-test-smoke load-test-slo \
        seed tf-plan helm-lint alembic-upgrade alembic-revision \
        trivy-scan trivy-scan-api trivy-scan-web drift-check promptfoo \
        kill-switch-on kill-switch-off cost-summary pgbouncer-up

PYTHON     := uv run python
API_DIR    := apps/api
WEB_DIR    := apps/web
API_IMAGE  := anime-rag-api:latest
WEB_IMAGE  := anime-rag-web:latest

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install all deps (Python + Node)
	uv sync --all-packages
	cd $(WEB_DIR) && pnpm install

up: ## Start local stack (postgres + redis + api + observability)
	docker compose up -d
	@echo "API  → http://localhost:8000/docs"
	@echo "Langfuse → http://localhost:3001"
	@echo "Grafana  → http://localhost:3000"

down: ## Tear down local stack
	docker compose down

build: ## Build all Docker images (development target)
	docker compose build

build-prod: ## Build production Docker images (non-root, hardened)
	docker build --target production -t $(API_IMAGE) apps/api
	docker build --target production -t $(WEB_IMAGE) apps/web

logs: ## Follow API logs
	docker compose logs -f api

lint: ## Lint Python (ruff) + types (mypy)
	uv run ruff check .
	uv run ruff format --check .
	cd $(API_DIR) && uv run mypy src

format: ## Auto-format Python
	uv run ruff format .
	uv run ruff check --fix .

test: ## Run unit + integration tests
	cd $(API_DIR) && uv run pytest tests/ -v --tb=short

test-unit: ## Unit tests only
	cd $(API_DIR) && uv run pytest tests/unit/ -v

test-integration: ## Integration tests (requires running stack)
	cd $(API_DIR) && uv run pytest tests/integration/ -v

seed: ## Ingest data/anime_with_synopsis.csv into pgvector
	$(PYTHON) scripts/ingest.py --csv data/anime_with_synopsis.csv

eval: ## Run RAGAS offline eval
	$(PYTHON) -m eval.ragas_runner

load-test-smoke: ## k6 smoke test (1 VU, 30s)
	k6 run scripts/load_test/smoke.js

load-test: ## k6 full ramp load test (0→20 VU, 15 min, SLO check)
	k6 run scripts/load_test/full.js

alembic-upgrade: ## Run Alembic migrations (requires running Postgres)
	cd $(API_DIR) && uv run alembic upgrade head

alembic-revision: ## Create a new Alembic migration (MSG="description")
	cd $(API_DIR) && uv run alembic revision --autogenerate -m "$(MSG)"

tf-plan: ## Terraform plan (dev env, no apply)
	cd infra/terraform && terragrunt run-all plan --terragrunt-working-dir envs/dev

helm-lint: ## Helm lint + dry-run template all charts
	helm lint infra/helm/api
	helm lint infra/helm/web
	helm template anime-rag-api infra/helm/api --dry-run
	helm template anime-rag-web infra/helm/web --dry-run

# ── Security scanning ─────────────────────────────────────────────────────────

trivy-scan-api: ## Trivy scan the API production image (build first with make build-prod)
	trivy image --config infra/trivy/trivy.yaml $(API_IMAGE)

trivy-scan-web: ## Trivy scan the web production image
	trivy image --config infra/trivy/trivy.yaml $(WEB_IMAGE)

trivy-scan: build-prod trivy-scan-api trivy-scan-web ## Build prod images then run Trivy on both

trivy-fs: ## Trivy filesystem scan (catches secrets/misconfigs without building images)
	trivy fs --config infra/trivy/trivy.yaml \
	    --scanners secret,misconfig \
	    --skip-dirs .venv,node_modules,.next \
	    .

# ── Eval ──────────────────────────────────────────────────────────────────────

drift-check: ## Check embedding drift between golden set and recent audit_log queries
	$(PYTHON) -m eval.drift_detector --report drift_report.json

promptfoo: ## Run Promptfoo prompt regression suite (requires npx)
	npx promptfoo eval --config promptfoo.yaml

load-test-slo: ## k6 SLO validation (3 scenarios, hard thresholds, writes slo_report.json)
	k6 run --out json=slo_raw.json scripts/load_test/slo-validation.js

# ── Cost controls ──────────────────────────────────────────────────────────────

API_URL ?= http://localhost:8000

kill-switch-on: ## Activate kill switch — all LLM calls routed to cheap model
	curl -sf -X POST $(API_URL)/api/v1/admin/cost/kill-switch \
	  -H "Content-Type: application/json" \
	  -d '{"active":true,"reason":"manual activation"}' | jq .

kill-switch-off: ## Deactivate kill switch — resume normal model routing
	curl -sf -X POST $(API_URL)/api/v1/admin/cost/kill-switch \
	  -H "Content-Type: application/json" \
	  -d '{"active":false,"reason":"manual deactivation"}' | jq .

cost-summary: ## Print today's cost summary from audit_log
	curl -sf $(API_URL)/api/v1/admin/cost/summary | jq .

# ── PgBouncer ──────────────────────────────────────────────────────────────────

pgbouncer-up: ## Start PgBouncer connection pool alongside postgres
	docker compose --profile pgbouncer up -d pgbouncer
	@echo "PgBouncer → localhost:5433 (routing to postgres:5432)"
