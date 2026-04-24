# Getting Started

Canon is a spec-driven development platform. You write structured specs in markdown, and Canon generates tickets, reviews PRs, and verifies what shipped against your acceptance criteria.

## Install the CLI

The fastest way to start is with the CLI. No server, no sign-up required.

```bash
# With pip
pip install canonhq

# With uv (recommended)
uv tool install canonhq

# Or run without installing
uvx --from canonhq canon --help
```

Then initialize any repo:

```bash
cd your-repo
canon setup
```

That's it. You now have `CANON.yaml`, a spec template, and a working local setup. Jump to the [Quickstart](./quickstart) to write your first spec and see the feedback loop.

## What Can Canon Do?

| Capability | How | Requirements |
|-----------|-----|-------------|
| **Parse & track specs** | `canon status`, `canon tasks` | CLI only |
| **Lint specs** | `canon lint` | CLI only |
| **Verify code against ACs** | `canon verify` | CLI only |
| **Audit with AI** | `canon audit` | CLI + `ANTHROPIC_API_KEY` |
| **Sync to Jira/Linear/GitHub** | `canon sync` | CLI + ticket system credentials |
| **PR analysis & auto-updates** | GitHub App | [GitHub App install](./installation#github-app) |
| **Spec search in your editor** | MCP server | [MCP setup](./installation#mcp-server) |
| **Slash commands in Claude Code** | Plugin | [Plugin install](./installation#claude-code-plugin) |
| **CI checks (lint, coverage, sync)** | GitHub Actions | [Actions setup](/guides/github-actions/) |

Start with the CLI. Add integrations as you need them. See the [CLI Reference](/reference/cli) for the full command list.

## Next Steps

1. **[Installation](./installation)** — All install methods (CLI, GitHub App, MCP, Plugin, Actions, self-hosted)
2. **[Quickstart](./quickstart)** — Write a spec, run the tools, see the loop — in 5 minutes
3. **[Configuration](./configuration)** — Customize `CANON.yaml` for your workflow
4. **[Writing Specs](/guides/writing-specs)** — Spec authoring guide with examples
5. **[Concepts](/concepts/)** — Living specs, delta tracking, coverage model
