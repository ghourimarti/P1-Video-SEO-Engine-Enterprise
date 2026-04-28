.PHONY: help install up down build logs lint test eval load-test seed tf-plan helm-lint alembic-upgrade alembic-revision

PYTHON     := uv run python
API_DIR    := apps/api
WEB_DIR    := apps/web

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

build: ## Build all Docker images
	docker compose build

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

load-test: ## k6 load test (requires running stack)
	k6 run scripts/load_test/smoke.js

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
