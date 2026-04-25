# Testing Guide

Canon uses a layered testing strategy: unit tests, integration tests, and
scenario-based lifecycle tests. This guide covers how to run each type and
how to add new tests.

## Prerequisites

### With Devbox (recommended)

[Devbox](https://github.com/jetify-com/devbox) provides a reproducible
environment with all required tools.

```bash
# Install devbox (one-time)
curl -fsSL https://get.jetify.com/devbox | bash

# Enter the environment (auto-installs Python, uv, Node, Helm, etc.)
devbox shell
```

### Without Devbox

Ensure you have:
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (latest)
- Docker (for integration and scenario tests)

```bash
uv sync --extra dev --extra cloud
```

## Running Tests

### Unit Tests

Unit tests run in-process with all external dependencies mocked. They're
fast (~35s) and require no external services.

```bash
# All unit tests
devbox run test          # or: uv run pytest

# Verbose
devbox run test:verbose  # or: uv run pytest -v

# Specific file or directory
uv run pytest tests/test_sync/test_linear_adapter.py -v

# Specific test
uv run pytest tests/test_parser/test_parse.py::test_frontmatter -v
```

### Integration Tests

Integration tests run against real services (Postgres, optionally Keycloak)
via Docker Compose. They test the full FastAPI stack via `httpx.AsyncClient`.

```bash
# Start services, run tests, tear down automatically
devbox run integration   # or: ./scripts/run-integration.sh

# Run specific integration tests
./scripts/run-integration.sh -k test_health -v
```

The compose stack starts Postgres 16 with pgvector on port 15432.

### Scenario Tests

Scenario tests simulate different Canon adoption stages. Each scenario is
a fixture repo that Canon CLI commands run against, with mock external
services (WireMock) providing fake Jira, Linear, and GitHub APIs.

```bash
# All scenarios
devbox run scenario      # or: ./scripts/run-scenario.sh

# Single scenario
./scripts/run-scenario.sh fresh-empty
./scripts/run-scenario.sh broken-config -v
```

Available scenarios:
| Scenario | Description |
|----------|-------------|
| `fresh-empty` | Empty repo, no CANON.yaml |
| `fresh-configured` | CANON.yaml present, no specs |
| `first-spec` | One spec file, GitHub Issues adapter |
| `mid-adoption` | 5 specs, mixed statuses, Jira adapter |
| `mature` | 8+ specs, Jira + Linear adapters |
| `oss-mode` | No cloud features, local-only |
| `multi-adapter` | Same spec synced to Jira + GitHub |
| `broken-config` | Intentionally invalid configurations |

### Lint

```bash
devbox run lint          # or: uv run ruff check && uv run ruff format --check
```

## Adding New Tests

### Unit Tests

Add test files under `tests/` mirroring the `src/canon/` structure:
- `src/canon/sync/adapters/linear.py` → `tests/test_sync/test_linear_adapter.py`
- Use `respx` for HTTP mocking
- Use `monkeypatch` for patching
- Mark async tests with `pytest.mark.asyncio` (auto-mode is enabled)

### Integration Tests

Add to `tests/integration/`. Mark with `@pytest.mark.integration`:

```python
@pytest.mark.integration
async def test_something(authed_app_client):
    resp = await authed_app_client.get("/app/dashboard")
    assert resp.status_code == 200
```

### Scenario Tests

1. Create a new directory: `tests/scenarios/<name>/`
2. Add `__init__.py` (empty)
3. Add `fixture/` directory with `CANON.yaml` and optional `docs/specs/*.md`
4. Add `test_<name>.py` (unique basename required):

```python
import pytest
from tests.scenarios.conftest import run_canon

@pytest.mark.scenario
@pytest.mark.parametrize("scenario_repo", ["<name>"], indirect=True)
class TestMyScenario:
    def test_doctor_passes(self, scenario_repo):
        result = run_canon(scenario_repo, "doctor")
        assert result.returncode == 0
```

## Mock Services

### WireMock Stubs

Mock API stubs live in `tests/mocks/wiremock/<adapter>/`:
- `mappings/` — Request matching rules (JSON)
- `__files/` — Response body files

To add a new stub, create a JSON file in `mappings/`:
```json
{
  "request": {
    "method": "POST",
    "urlPathPattern": "/rest/api/3/issue"
  },
  "response": {
    "status": 201,
    "headers": { "Content-Type": "application/json" },
    "jsonBody": { "key": "TEST-1" }
  }
}
```

### Recording from Real APIs

To capture real API interactions as WireMock stubs:

```bash
./scripts/record-contracts.sh jira    # requires JIRA_HOST, JIRA_TOKEN
./scripts/record-contracts.sh linear  # requires LINEAR_API_KEY
./scripts/record-contracts.sh github  # requires GITHUB_TOKEN
```

## Troubleshooting

### Docker not starting

```bash
docker compose -f docker-compose.test.yml up -d --wait
docker compose -f docker-compose.test.yml logs  # check for errors
```

### Port conflicts

The test stack uses non-standard ports to avoid conflicts:
- Postgres: 15432 (not 5432)
- WireMock Jira: 18080
- WireMock Linear: 18081
- WireMock GitHub: 18082
- Keycloak: 18083

If ports are in use: `docker compose -f docker-compose.test.yml down -v`

### Scenario test name collision

All scenario test files must have unique basenames (e.g., `test_fresh_empty.py`,
not `test_scenario.py`). Pytest collects across directories and will error on
duplicate module names.

### Devbox issues

```bash
# Rebuild environment
devbox rm && devbox shell

# Check package availability
devbox search python
```
