# Canon

Spec-driven development platform. Write structured specs, sync tickets, and get AI-powered context in your PRs and IDE.

## What Canon Does

- **Spec parser** — Structured markdown specs with frontmatter, sections, and status tracking
- **Ticket sync** — Bidirectional sync between specs and Jira, Linear, or GitHub Issues
- **CLI** — `canon setup`, `canon sync`, `canon status`, `canon audit`, and more
- **MCP server** — Model Context Protocol integration for AI assistants
- **GitHub App** — PR analysis with spec context, automated doc updates
- **Claude Code plugin** — Spec-aware skills for Claude Code

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)

### Install

```bash
git clone https://github.com/canonhq/canon.git
cd canon
uv sync --extra dev
```

### Set Up a Repo

```bash
# Initialize CANON.yaml in your project
canon setup

# Configure environment (copy and fill in your keys)
cp .env.example .env
```

### Run Tests

```bash
uv run pytest
uv run pytest -v          # verbose
uv run ruff check         # lint
```

### CLI Usage

```bash
canon setup               # Initialize CANON.yaml in current repo
canon status              # Show spec coverage status
canon tasks               # List open tasks from specs
canon sync                # Sync spec sections to tickets
canon audit               # Full spec audit with optional sync
canon verify              # Verify spec structure
canon plan                # Generate implementation plan from spec
```

### MCP Server

Canon includes an MCP server for AI assistant integration:

```bash
canon-mcp                 # Start MCP server (stdio transport)
```

## Project Structure

```
src/canon/
  cli/          # CLI commands (setup, sync, status, audit, etc.)
  parser/       # Spec markdown parser (frontmatter + sections)
  sync/         # Ticket sync engine (Jira, Linear, GitHub Issues)
  agent/        # Claude agent runtime for PR analysis
  config/       # CANON.yaml parser and validation
  mcp/          # MCP server for AI assistant integration
  github/       # GitHub API client utilities
plugin/         # Claude Code plugin with spec-aware skills
docs/           # Self-hosting and configuration docs
docs-site/      # Documentation website (VitePress)
chart/          # Helm chart for Kubernetes deployment
```

## Configuration

Canon is configured via `CANON.yaml` in your repo root:

```yaml
team: my-team
ticket_system: github     # github | jira | linear
project_key: owner/repo
specs:
  auto_tickets: true
  require_review: false
agents:
  doc_updates: true
  pr_analysis: true
  stale_detection: 30d
```

## Environment Variables

See `.env.example` for all available configuration. At minimum you need:

- `ANTHROPIC_API_KEY` — For the Claude agent runtime
- `GH_APP_ID` + `GH_PRIVATE_KEY` — For the GitHub App integration
- Ticket system credentials (Jira/Linear/GitHub token) for sync

## License

MIT — see [LICENSE](LICENSE).
