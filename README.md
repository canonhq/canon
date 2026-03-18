<p align="center">
  <img src="https://raw.githubusercontent.com/canonhq/canon/main/docs-site/public/logo.svg" alt="Canon" width="80" />
</p>

<h1 align="center">Canon</h1>

<p align="center">
  <strong>Spec-driven development, automated.</strong><br/>
  Write structured specs in markdown. AI agents handle PR reviews, ticket sync, and code verification.
</p>

<p align="center">
  <a href="https://pypi.org/project/canonhq/"><img src="https://img.shields.io/pypi/v/canonhq?color=blue" alt="PyPI"></a>
  <a href="https://github.com/canonhq/canon/actions/workflows/ci.yml"><img src="https://github.com/canonhq/canon/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/canonhq/canon/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-BSL_1.1-blue" alt="License"></a>
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

### Install

```bash
pip install canonhq        # CLI + MCP server
canon setup                # Creates CANON.yaml in your repo
```

### Create a spec with AI

Using the [Claude Code plugin](https://canonhq.co/docs/getting-started/installation#claude-code-plugin):

```
> /canon-new

Creating spec: User Authentication
✓ Generated docs/specs/user-auth.md with 4 sections, 12 acceptance criteria
```

Or connect any MCP-compatible agent (Claude Code, Cursor, Windsurf) to the Canon knowledge base:

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

### Work with specs

```bash
canon status             # See spec completion across your repo
canon verify             # Verify acceptance criteria against code
canon sync               # Sync spec sections to Jira/Linear/GitHub Issues
canon plan               # Generate an implementation plan from a spec
```

### What happens next

Once specs exist, Canon keeps them alive:

1. **Open a PR** → Canon analyzes the diff against relevant specs and comments with coverage
2. **Close a ticket** → the spec section updates automatically
3. **Code ships** → the agent verifies acceptance criteria are actually implemented

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

[Business Source License 1.1](LICENSE) — free to use, modify, and self-host. The only restriction is offering Canon as a competing commercial hosted service. Converts to Apache 2.0 four years after each release.
