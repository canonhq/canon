# Installation

## CLI (start here) {#cli}

The Canon CLI is a Python package that works in any repo. No server or account required.

### Prerequisites

- **Python 3.12+** — check with `python3 --version`
- **Git** — Canon reads your repo structure

### Install

::: code-group

```bash [uv (recommended)]
uv tool install canonhq
```

```bash [pip]
pip install canonhq
```

```bash [pipx]
pipx install canonhq
```

:::

Verify it works:

```bash
canon --help
```

### Initialize a repo

```bash
cd your-repo
canon setup
```

This creates:
- `CANON.yaml` — project configuration
- `docs/specs/_template.md` — starter spec template
- `docs/specs/` directory

### Optional: AI features

For AI-powered audit (`canon audit`), set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Most CLI commands (status, tasks, lint, verify, sync) work without an API key.

### Optional: Ticket sync credentials

To sync specs with your ticket system:

| System | Credentials |
|--------|------------|
| **GitHub Issues** | `GITHUB_TOKEN` or `gh` CLI authenticated |
| **Jira** | `canon login` (OAuth) or `JIRA_URL` + `JIRA_TOKEN` |
| **Linear** | `canon login` (OAuth) or `LINEAR_API_KEY` |

---

## GitHub App {#github-app}

The GitHub App adds automated PR analysis — Canon comments on every PR with spec references and realization status. Install this after you've tried the CLI and want to automate.

### 1. Install the App

Visit the [Canon GitHub App](https://github.com/apps/canon) page and click **Install**. Select your organization and choose which repositories to enable.

### 2. Ensure CANON.yaml exists

If you haven't already run `canon setup`, create a minimal config:

```yaml
version: "1"

specs:
  doc_paths:
    - "docs/specs/*.md"

agents:
  pr_analysis: true
  doc_updates: true
  realization_check: true
```

### 3. Open a PR

The Canon bot will analyze your PR against relevant specs and post a comment with spec references, realization status, and any discrepancies.

---

## Claude Code Plugin {#claude-code-plugin}

The plugin adds spec-driven slash commands (`/canon:context`, `/canon:task`, `/canon:verify`, etc.) to Claude Code sessions.

### Install

```bash
claude plugin marketplace add canonhq/canon
claude plugin install canon
```

Or use the CLI to set up both MCP and agent config:

```bash
canon setup --agent claude
```

### Available skills

| Skill | Description |
|-------|-------------|
| `/canon:context` | Load spec context for your current task |
| `/canon:task` | Pick up a task, implement ACs, mark done |
| `/canon:verify` | Verify code against spec acceptance criteria |
| `/canon:new` | Create a new spec from template |
| `/canon:review` | Review changes against all documentation |
| `/canon:status` | Show spec coverage dashboard |
| `/canon:plan` | Spec-driven planning workflow |
| `/canon:update` | Update spec statuses from code evidence |
| `/canon:audit` | Full spec audit with ticket sync |

::: tip
`canon setup --agent claude` configures MCP and agent instructions but doesn't install the plugin marketplace entry. For slash commands, install the plugin separately.
:::

---

## MCP Server {#mcp-server}

The MCP server connects any MCP-compatible editor (Claude Code, Cursor, Windsurf, VS Code Copilot) to your spec knowledge base.

### Configure in Claude Code

`canon setup` creates `.mcp.json` automatically. To add it manually:

```json
{
  "mcpServers": {
    "canon": {
      "command": "uvx",
      "args": ["--from", "canonhq", "canon-mcp"]
    }
  }
}
```

### Available tools

| Tool | Description |
|------|-------------|
| `search` | Hybrid search (vector + BM25) across all indexed docs |
| `get_spec` / `get_section` | Read parsed spec data with frontmatter and ACs |
| `create_spec` | Create new specs from templates |
| `update_section_status` | Update section statuses |
| `add_realization` | Link code evidence to acceptance criteria |
| `sync_spec_status` | Bulk status updates in one commit |

### Other editors

For Cursor, Windsurf, or VS Code — consult your editor's MCP documentation and point it at the Canon MCP server using the same `uvx` command above.

---

## GitHub Actions {#github-actions}

Run Canon checks in CI — spec linting, coverage reports, ticket sync, and more.

### Quick setup

```yaml
name: Canon Lint
on: pull_request

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/spec-lint@v1
```

See the full [GitHub Actions guide](/guides/github-actions/) for all available actions (lint, verify, coverage, sync, audit, and more).

---

## Self-Hosted {#self-hosted}

Deploy Canon to your own Kubernetes cluster for full control over data.

See the [Self-Hosting Guide](/guides/self-hosting) for:
- GitHub App creation
- Kubernetes secret management
- Helm chart installation
- Jira/Linear/GitHub Issues configuration
