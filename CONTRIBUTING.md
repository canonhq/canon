# Contributing to Canon

Thanks for your interest in contributing to Canon!

## Getting Started

```bash
git clone https://github.com/canonhq/canon.git
cd canon
uv sync --extra dev
make test
```

## Development Workflow

1. Fork the repo and create a feature branch
2. Make your changes
3. Run tests: `make test`
4. Run linter: `make lint`
5. Open a pull request

## Code Style

- Python code is formatted and linted with [ruff](https://docs.astral.sh/ruff/)
- Run `make format` to auto-fix lint issues
- Run `make typecheck` for mypy type checking

## Tests

```bash
make test          # Run all tests
make test-v        # Verbose output
make test-cov      # With coverage report
```

## Project Structure

See [README.md](README.md) for an overview of the codebase layout.

## Reporting Issues

Open an issue at [github.com/canonhq/canon/issues](https://github.com/canonhq/canon/issues).
