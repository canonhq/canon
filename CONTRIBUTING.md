# Contributing to Canon

Thanks for your interest in contributing! Canon is an open-source project and we welcome contributions of all kinds — bug reports, feature requests, documentation improvements, and code.

## Getting Started

```bash
git clone https://github.com/canonhq/canon.git
cd canon
uv sync --extra dev
make test
```

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

## Ways to Contribute

- **Report bugs** — [Open an issue](https://github.com/canonhq/canon/issues/new?template=bug_report.md) with steps to reproduce
- **Request features** — [Open an issue](https://github.com/canonhq/canon/issues/new?template=feature_request.md) describing the use case
- **Improve docs** — Fix typos, clarify guides, add examples
- **Submit code** — Bug fixes, new features, test coverage

## Development Workflow

1. Fork the repo and create a feature branch from `main`
2. Make your changes
3. Run tests and linting:
   ```bash
   make test       # Run all tests
   make lint       # Run ruff linter
   make format     # Auto-fix formatting
   ```
4. Open a pull request against `main`

## Code Style

- Python code is formatted and linted with [ruff](https://docs.astral.sh/ruff/)
- Run `make format` to auto-fix lint and formatting issues
- Run `make typecheck` for mypy type checking

## Tests

```bash
make test          # Run all tests
make test-v        # Verbose output
make test-cov      # With coverage report
```

Tests are in `tests/` and mirror the `src/canon/` structure. New features should include tests.

## Project Structure

See the [README](README.md) for a project overview, or the [Architecture docs](https://canonhq.co/docs/architecture/) for a deeper look.

## Code of Conduct

This project follows a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.

## Questions?

Open an issue or start a [discussion](https://github.com/canonhq/canon/discussions) on GitHub.
