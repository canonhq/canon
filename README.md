<p align="center">
  <img src="https://canonhq.co/logo.svg" alt="Canon" width="80" />
</p>

<h1 align="center">Canon</h1>

<p align="center">
  <strong>Spec-driven development, automated.</strong><br/>
  Write structured specs in markdown. AI agents handle PR reviews, ticket sync, and code verification.
</p>

<p align="center">
  <a href="https://pypi.org/project/canonhq/"><img src="https://img.shields.io/pypi/v/canonhq?color=blue" alt="PyPI"></a>
  <a href="https://github.com/canonhq/canon/actions/workflows/ci.yml"><img src="https://github.com/canonhq/canon/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/canonhq/canon/blob/main/LICENSE"><img src="https://img.shields.io/github/license/canonhq/canon" alt="License"></a>
  <a href="https://canonhq.co/docs"><img src="https://img.shields.io/badge/docs-canonhq.co-green" alt="Docs"></a>
</p>

---

## The Problem

Documentation drifts the moment it's written. Specs live in Notion or Confluence, disconnected from the code they describe. Tickets lose context. Nobody knows if what shipped actually matches what was planned.

Canon fixes this by treating specs as **living programs** — structured markdown that AI agents continuously verify against your codebase.

## What Canon Does

**Spec-Aware PR Reviews** — When a PR opens, Canon analyzes the diff against relevant specs, identifies which acceptance criteria are addressed, and flags gaps.

**Bidirectional Ticket Sync** — Spec sections become tickets in Jira, Linear, or GitHub Issues. Close a ticket and the spec updates. Mark a section done and the ticket closes.

**Code-Aware Verification** — AI reads your code to verify that acceptance criteria are actually implemented — not just that a ticket was closed.

**Coverage Dashboard** — Track spec completion across your org by repo, team, and status.

**CLI & MCP Server** — The `canon` CLI provides plan, verify, status, and sync commands. The MCP server gives any AI coding agent (Claude Code, Cursor, Windsurf) access to your spec knowledge base.

## How It Works

```
                    ┌─────────────────┐
                    │   PM writes     │
                    │  structured     │
                    │     spec        │
                    └───────┬─────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │   Canon indexes all markdown │
              │  (specs, ADRs, guides, READMEs) │
              └─────────────┬───────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ PR opened  │ │  Tickets   │ │ Cron: spec │
     │ → analyze  │ │ → sync     │ │ → verify   │
     │   vs spec  │ │   sections │ │   vs code  │
     └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
           │              │              │
           └──────────────┼──────────────┘
                          ▼
              ┌─────────────────────────────┐
              │   Spec updates with evidence │
              │   (realized-in, status, PRs)  │
              └─────────────────────────────┘
```

Specs define **intent** (what should be built). Code reveals **reality** (what shipped). Canon closes the loop between the two.

## Choose Your Path

| Path | Best for | What you get |
|------|----------|--------------|
| **[GitHub App](https://canonhq.co/docs/getting-started/installation)** | Teams wanting full automation | PR analysis, ticket sync, doc maintenance, coverage dashboard |
| **[CLI](https://canonhq.co/docs/reference/cli)** | Individual developers | `canon setup`, `status`, `sync`, `verify`, `plan`, `audit` |
| **[MCP Server](https://canonhq.co/docs/getting-started/installation#mcp-server)** | AI-assisted development | Spec search and context in Claude Code, Cursor, Windsurf |
| **[Claude Code Plugin](https://canonhq.co/docs/getting-started/installation#claude-code-plugin)** | Claude Code users | Slash commands for spec-driven workflows |
| **[Self-Hosted](https://canonhq.co/docs/guides/self-hosting)** | Full control | Deploy on your own K8s cluster |

## Quick Start

### Install the CLI

```bash
pip install canonhq
```

### Set up a repo

```bash
canon setup          # Creates CANON.yaml
```

### Write a spec

Create `docs/specs/my-feature.md`:

```markdown
---
title: User Authentication
status: draft
priority: high
---

## 1. Login Flow

Users can log in with email and password.

- [ ] POST /auth/login accepts email + password
- [ ] Returns JWT token on success
- [ ] Rate-limits to 5 attempts per minute

## 2. Session Management

- [ ] Tokens expire after 24 hours
- [ ] Refresh tokens extend sessions by 7 days
```

### Check coverage

```bash
canon status         # See spec completion
canon verify         # Verify specs against code
canon sync           # Sync sections to tickets
```

### Connect your AI agent

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

## Documentation

Full documentation is at **[canonhq.co/docs](https://canonhq.co/docs)**:

- **[Getting Started](https://canonhq.co/docs/getting-started/)** — Installation, quickstart, configuration
- **[Concepts](https://canonhq.co/docs/concepts/)** — Spec-driven development, living specs, coverage
- **[Guides](https://canonhq.co/docs/guides/)** — Writing specs, self-hosting, ticket sync, CI integration
- **[Reference](https://canonhq.co/docs/reference/)** — CLI, MCP tools, REST API, spec format, CANON.yaml

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and guidelines.

```bash
git clone https://github.com/canonhq/canon.git
cd canon
uv sync --extra dev
make test
```

## License

MIT — see [LICENSE](LICENSE).
