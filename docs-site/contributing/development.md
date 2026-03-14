# Development Setup

Get Canon running locally for development.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Node.js 18+ (for the frontend)
- Git

## Clone and Install

```bash
git clone git@github.com:canonhq/canon.git
cd canon

# Install all dependencies (backend + frontend)
make install
```

This runs:
- `uv sync --extra dev` — Python dependencies including dev extras
- `cd frontend && npm ci` — Frontend dependencies

## Environment Variables

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Required for basic development:

| Variable | Description |
|----------|-------------|
| `GH_APP_ID` | GitHub App ID |
| `GH_PRIVATE_KEY` | GitHub App private key (PEM format) |
| `GH_WEBHOOK_SECRET` | GitHub App webhook secret |
| `GH_INSTALLATION_ID` | GitHub App installation ID |
| `ANTHROPIC_API_KEY` | Claude API key for agent runtime |

Optional:

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | GitHub PAT for ticket sync via GitHub Issues |
| `JIRA_HOST` | Jira instance hostname |
| `JIRA_EMAIL` | Jira service account email |
| `JIRA_API_TOKEN` | Jira API token |
| `LINEAR_API_KEY` | Linear API key |
| `LOG_LEVEL` | Logging level (default: `info`) |

## Running Locally

### Backend Only

```bash
# With environment variables configured
make dev

# Without secrets (no auth, limited features)
make dev-no-auth
```

The FastAPI server runs at `http://localhost:3000` with auto-reload.

### Frontend Only

```bash
make dev-frontend
```

Vite HMR server at `http://localhost:5173`.

### Both (recommended)

```bash
make dev
```

The FastAPI server serves the Vue SPA and handles API routes.

## Kubernetes Dev Environment

For testing against real GitHub webhooks and ticket systems, use the DevSpace-based dev environment:

### Additional Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [DevSpace CLI](https://devspace.sh/docs/getting-started/installation) (v6+)
- A Kubernetes cluster with `kubectl` configured
- A container registry (e.g., Docker Hub, GHCR, or cloud provider registry)

### One-Time Setup

```bash
# Authenticate with your container registry
docker login <your-registry>

# Configure kubectl for your cluster
kubectl config use-context <your-cluster>
```

### Usage

```bash
export DEVSPACE_USERNAME=your-name

# Full dev mode
devspace dev

# → http://localhost:3000 (port-forwarded)
```

File changes in `src/`, `templates/`, and `static/` sync into the pod and uvicorn auto-reloads.

### Useful DevSpace Commands

```bash
devspace run logs             # tail pod logs
devspace run sync-secrets     # re-sync secrets
devspace run sync-trigger     # manually run reverse sync cron
devspace purge                # tear down dev environment
```

## Make Commands

Run `make help` for the full list. Key commands:

| Command | Description |
|---------|-------------|
| `make install` | Install all dependencies |
| `make dev` | Run dev server |
| `make test` | Run Python tests |
| `make lint` | Lint backend + frontend |
| `make format` | Auto-fix Python lint errors |
| `make typecheck` | Run mypy + vue-tsc |
| `make build` | Build Vue SPA |
| `make build-docker` | Build production Docker image |
| `make docs-dev` | Run docs site dev server |
| `make docs-build` | Build docs site |
