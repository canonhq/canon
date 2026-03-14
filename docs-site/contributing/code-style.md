# Code Style

Canon uses automated tools for consistent code style. All checks run in CI.

## Python

### Linter: Ruff

[Ruff](https://docs.astral.sh/ruff/) handles both linting and formatting:

```bash
# Check for lint errors
make lint-backend

# Auto-fix lint errors + format
make format
```

Or directly:

```bash
uv run ruff check           # lint
uv run ruff check --fix     # auto-fix
uv run ruff format          # format
uv run ruff format --check  # check formatting without changing files
```

### Type Checking: mypy

```bash
make typecheck
# or
uv run mypy src/canon
```

### Conventions

- **Python 3.12+** — Use modern syntax (type unions `X | Y`, `match` statements, etc.)
- **Pydantic v2** — All data models use Pydantic with strict validation
- **Async by default** — Use `async def` for handler functions and API calls
- **httpx** — Async HTTP client (not requests)

## Frontend

### Linter: ESLint

```bash
make lint-frontend
# or
cd frontend && npm run lint
```

### Type Checking: vue-tsc

```bash
cd frontend && npm run type-check
```

## Commit Messages

Use conventional commit format:

```
type: short description

Longer description if needed.
```

Types:
- `feat:` — New feature
- `fix:` — Bug fix
- `docs:` — Documentation changes
- `refactor:` — Code restructuring
- `test:` — Test additions/changes
- `chore:` — Build/tooling changes
- `spec:` — Spec file additions/changes

Examples:
```
feat: add Linear ticket sync adapter
fix: handle empty spec sections in parser
docs: update self-hosting guide for Auth0
spec: add user notifications spec
```
