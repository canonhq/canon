.PHONY: help setup install install-cli setup-claude install-docs \
       test test-v test-cov \
       lint format typecheck \
       build-wheel \
       clean \
       docs-dev docs-build docs-preview

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────
setup: install ## First-time setup: install deps, create CANON.yaml + .mcp.json
	uv run canon setup --non-interactive

install-cli: ## Install canon CLI globally (installs or upgrades)
	uv tool install --force canonhq
	@echo ""
	@echo "Installed. Verify with: canon --help"

setup-claude: ## Configure Claude Code MCP (.mcp.json only, won't touch CANON.yaml)
	@if [ ! -f .mcp.json ]; then \
		printf '{\n  "mcpServers": {\n    "canon": {\n      "type": "stdio",\n      "command": "uvx",\n      "args": ["--from", "canonhq", "canon-mcp"]\n    }\n  }\n}\n' > .mcp.json; \
		echo "Created .mcp.json with Canon MCP config."; \
		echo "Tip: consider adding .mcp.json to your .gitignore."; \
	else \
		echo ".mcp.json already exists — verify it includes the canon MCP server."; \
	fi
	@echo "Restart Claude Code to pick up MCP changes."

# ── Install ───────────────────────────────────────────────
install: ## Install all dependencies
	uv sync --extra dev

install-docs: ## Install docs site dependencies
	cd docs-site && npm ci

# ── Test ──────────────────────────────────────────────────
test: ## Run tests
	uv run pytest

test-v: ## Run tests (verbose)
	uv run pytest -v

test-cov: ## Run tests with coverage
	uv run pytest --cov --cov-report=term-missing

# ── Lint & Format ─────────────────────────────────────────
lint: ## Lint Python with ruff
	uv run ruff check

format: ## Auto-fix lint errors
	uv run ruff check --fix
	uv run ruff format

typecheck: ## Run mypy type checks
	uv run mypy src/canon

# ── Build ─────────────────────────────────────────────────
build-wheel: ## Build Python wheel
	uv build --wheel

# ── Clean ─────────────────────────────────────────────────
clean: ## Clean build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist

# ── Docs ──────────────────────────────────────────────────
docs-dev: ## Run VitePress dev server (run install-docs first)
	cd docs-site && npm run dev

docs-build: ## Build VitePress static site
	cd docs-site && npm run build

docs-preview: ## Preview built docs site
	cd docs-site && npm run preview
