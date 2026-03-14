.PHONY: help install install-backend install-frontend install-docs \
       dev dev-no-auth dev-frontend \
       test test-backend test-frontend test-integration test-e2e \
       lint lint-backend lint-frontend format typecheck \
       build build-frontend build-docker \
       clean clean-frontend clean-docker \
       docker-run docker-dev helm-template \
       docs-dev docs-build docs-preview

# ── Defaults ──────────────────────────────────────────────
DOCKER_REGISTRY ?= registry.digitalocean.com/gv-shared
DOCKER_IMAGE    ?= $(DOCKER_REGISTRY)/canon
DOCKER_TAG      ?= latest
HELM_RELEASE    ?= canon
HELM_NAMESPACE  ?= canon

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Install ───────────────────────────────────────────────
install: install-backend install-frontend ## Install all dependencies

install-backend: ## Install Python dependencies
	uv sync --extra dev

install-frontend: ## Install frontend dependencies
	cd frontend && npm ci

install-docs: ## Install docs site dependencies
	cd docs-site && npm ci

# ── Dev Servers ───────────────────────────────────────────
dev: ## Run FastAPI dev server with Doppler secrets on :3000
	doppler run -- uv run uvicorn canon.main:app --reload --port 3000

dev-no-auth: ## Run FastAPI dev server without secrets (no auth)
	uv run uvicorn canon.main:app --reload --port 3000

dev-frontend: ## Run Vite HMR server for frontend-only work (:5173)
	cd frontend && npm run dev

# ── Test ──────────────────────────────────────────────────
test: test-backend ## Run Python tests

test-backend: ## Run Python tests
	uv run pytest

test-backend-v: ## Run Python tests (verbose)
	uv run pytest -v

test-cov: ## Run Python tests with coverage
	uv run pytest --cov --cov-report=term-missing

test-cov-unit: ## Run unit tests with JSON coverage output
	uv run pytest --cov --cov-report=json:coverage-unit.json

test-cov-integration: ## Run integration tests with JSON coverage output
	uv run pytest -m integration --override-ini "addopts=" --cov --cov-report=json:coverage-integration.json

test-cov-report: ## Generate coverage PR comment locally
	uv run python scripts/coverage_report.py \
		--unit coverage-unit.json \
		--integration coverage-integration.json \
		--combined coverage-combined.json

test-integration: ## Run integration tests
	uv run pytest -m integration --override-ini "addopts=" -v

test-frontend: ## Run frontend type-check
	cd frontend && npm run type-check

test-e2e: ## Run Playwright e2e tests
	npx playwright test

# ── Lint & Format ─────────────────────────────────────────
lint: lint-backend lint-frontend ## Lint everything

lint-backend: ## Lint Python with ruff
	uv run ruff check

lint-frontend: ## Lint frontend with eslint
	cd frontend && npm run lint

format: ## Auto-fix Python lint errors
	uv run ruff check --fix
	uv run ruff format

typecheck: ## Run mypy + vue-tsc type checks
	uv run mypy src/canon
	cd frontend && npm run type-check

# ── Build ─────────────────────────────────────────────────
build: build-frontend docs-build ## Build frontend + docs assets

build-frontend: ## Build Vue SPA for production
	cd frontend && npm run build

build-docker: ## Build production Docker image
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .

build-wheel: ## Build Python wheel
	uv build --wheel

# ── Docker ────────────────────────────────────────────────
docker-run: ## Run production Docker image locally
	doppler run -- docker run --rm -p 3000:3000 --env-file <(doppler secrets download --no-file --format env) $(DOCKER_IMAGE):$(DOCKER_TAG)

docker-dev: ## Build and run dev Docker image with reload
	docker build -f Dockerfile.dev -t canon-dev . && \
	doppler run -- docker run --rm -p 3000:3000 --env-file <(doppler secrets download --no-file --format env) \
		-v $(PWD)/src:/app/src \
		-v $(PWD)/templates:/app/templates \
		-v $(PWD)/static:/app/static \
		canon-dev

docker-push: ## Push Docker image to registry
	docker push $(DOCKER_IMAGE):$(DOCKER_TAG)

# ── Helm ──────────────────────────────────────────────────
helm-template: ## Render Helm chart templates locally
	helm template $(HELM_RELEASE) chart/canon -n $(HELM_NAMESPACE)

helm-lint: ## Lint the Helm chart
	helm lint chart/canon

helm-diff: ## Show diff of what helm upgrade would change
	helm diff upgrade $(HELM_RELEASE) chart/canon -n $(HELM_NAMESPACE)

# ── Clean ─────────────────────────────────────────────────
clean: clean-frontend ## Clean build artifacts

clean-frontend: ## Remove frontend build output
	rm -rf frontend/dist static/app frontend/.vite frontend/tsconfig.tsbuildinfo

clean-docker: ## Remove local Docker images
	docker rmi $(DOCKER_IMAGE):$(DOCKER_TAG) canon-dev 2>/dev/null || true

clean-all: clean clean-docker ## Clean everything including Docker images
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist

# ── Docs ─────────────────────────────────────────────────
docs-dev: ## Run VitePress dev server (run install-docs first)
	cd docs-site && npm run dev

docs-gen-refs: ## Generate CLI, MCP, and API reference docs
	uv run python docs-site/.vitepress/scripts/gen-refs.py

docs-build: ## Build VitePress static site (auto-generates refs)
	cd docs-site && npm run build

docs-preview: ## Preview built docs site
	cd docs-site && npm run preview
