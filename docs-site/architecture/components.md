# Components

Per-module documentation for the Canon codebase.

## Project Structure

```
src/canon/
  main.py              # FastAPI app: webhook routes, health checks
  settings.py          # Pydantic Settings (env vars)
  github/              # GitHub App webhook handling
    verify.py          # HMAC SHA-256 signature verification
    client.py          # GitHub API client (JWT auth, httpx)
    spec_utils.py      # Spec file detection and loading
    handlers/          # Event handlers
      on_push.py       # Push event handler
      on_pull_request.py   # PR analysis handler
      on_issue_comment.py  # Interactive commands
  agent/               # Claude agent runtime
    client.py          # Anthropic SDK wrapper
    analyzer.py        # PR analysis + comment formatting
    prompts.py         # System prompt + user message builder
  parser/              # Spec markdown parser
    models.py          # Pydantic: SpecDocument, SpecSection, etc.
    parse.py           # Main parser (frontmatter + sections + comments)
    writer.py          # Insert ticket links, update status comments
  sync/                # Ticket sync
    engine.py          # Forward/reverse sync logic
    status_map.py      # Bidirectional spec↔ticket status mapping
    models.py          # Pydantic: CreateTicketInput/Result, SyncResult
    adapters/          # Jira, Linear, GitHub Issues adapters
  config/              # CANON.yaml parser
    parse.py           # YAML → Pydantic models with validation
  cron/                # Cron job scripts
    sync_status.py     # Standalone reverse sync (K8s CronJob)
  web/                 # Web routes (serves Vue SPA + Jinja2 fallback)
  cli.py               # CLI entrypoint
  mcp/                 # MCP server
frontend/              # Vue 3 SPA (Vite + Tailwind + Pinia)
tests/                 # pytest tests (mirrors src structure)
chart/canon/      # Helm chart for K8s deployment
```

## `github/` — GitHub Integration

### `verify.py`

HMAC SHA-256 signature verification for incoming webhooks. Compares the `X-Hub-Signature-256` header against the computed hash of the request body using the webhook secret.

### `client.py`

Async GitHub API client built on httpx. Handles:
- JWT generation from the GitHub App private key
- Installation access token management
- File content retrieval, PR operations, comment management

### `spec_utils.py`

Utilities for working with specs in GitHub repos:
- `CONFIG_ONLY_RE` — Regex pattern matching CI/config files (used to skip analysis)
- Spec file detection based on `doc_paths` configuration
- Spec loading from a specific branch/commit

### `handlers/`

Event handler modules, each exporting an async handler function:
- `on_push.py` — Watches for spec/doc changes on the default branch
- `on_pull_request.py` — Full PR analysis pipeline
- `on_issue_comment.py` — `@canon` command parsing and execution

## `agent/` — Claude Agent Runtime

### `client.py`

Thin wrapper around the Anthropic Python SDK:
- Model configuration (default: Sonnet 4.5, 128k input, 16k output)
- `is_available` check (verifies API key is set)
- Error types: `AgentAPIError` with status code

### `analyzer.py`

Orchestrates the full analysis pipeline:
- Builds `PRAnalysisContext` from PR data, specs, and context docs
- Calls Claude and parses the JSON response
- Formats the GitHub markdown comment
- Handles the full fallback chain for malformed responses

### `prompts.py`

Constructs the messages sent to Claude:
- `build_system_prompt()` — Base rules + realization instructions + JSON schema
- `build_user_message()` — PR metadata, spec summaries, context docs, diffs
- Token estimation for diff budgeting

## `parser/` — Spec Parser

### `models.py`

Pydantic v2 models representing parsed specs:
- `SpecDocument` — Full spec with frontmatter and sections
- `SpecSection` — Individual section with status, ticket links, ACs
- `AcceptanceCriterion` — Single AC with checked state and realization evidence

### `parse.py`

The main parser. Takes raw markdown and produces a `SpecDocument`:
1. Extract YAML frontmatter via `python-frontmatter`
2. Split on heading boundaries
3. Parse status comments and ticket links from HTML comments
4. Extract acceptance criteria from checkbox lists

### `writer.py`

Writes changes back to spec markdown:
- Insert/update ticket link comments
- Update status comments
- Insert realization evidence comments

## `sync/` — Ticket Sync

### `engine.py`

Forward and reverse sync logic:
- Forward: Create tickets from new spec sections, update existing tickets on spec changes
- Reverse: Poll ticket systems for status changes, update spec files

### `adapters/`

Per-system adapter implementations. Each adapter implements the `TicketAdapter` interface for creating, updating, and querying tickets.

## `config/` — Configuration

### `parse.py`

Parses `CANON.yaml` into typed Pydantic models. Validates all fields and warns on unknown keys for forward compatibility.
