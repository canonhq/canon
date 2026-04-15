# Canon Plugin for Claude Code

AI-native spec documentation — verify code against specs, track coverage, maintain living docs.

## Installation

Canon ships through two paths. Pick the one that matches what you need:

| Use case | Command | What it produces |
|---|---|---|
| **Set up Canon in a repo** (write `CANON.yaml`, install MCP server, scaffold spec template) | `pipx install canonhq && canon setup` | `CANON.yaml`, `.mcp.json`, `docs/specs/_template.md`, optional `.claude/skills/` |
| **Add Canon skills to Claude Code** (slash commands and skills only) | `claude plugin marketplace add canonhq/canon` then `claude plugin install canon` | Plugin installed under `~/.claude/plugins/`, available in every session |
| **Both** (recommended for new repos) | Run `canon setup` first, then `claude plugin install canon` | Full integration: per-repo config + global plugin |

**When to use the CLI path:**
- You're starting a new Canon repo and need `CANON.yaml` written
- You want the MCP server installed automatically
- You want the spec template scaffolded

**When to use the marketplace path:**
- You already have Canon set up in your repos and just want the slash commands
- You're trying Canon out and don't want to install a Python package

`canon setup` writes `.mcp.json` and `.claude/skills/` so the marketplace install is **not required** if you've already run `canon setup`. The two paths are additive — installing both is supported and produces no conflicts.

Or from inside a Claude Code session:

```
/plugin marketplace add canonhq/canon
/plugin install canon
```

## Multi-Agent Setup

Canon's spec context works in any AI coding agent that supports MCP or rule files. Use `canon setup --agent <platform>` to generate the right config file for each:

| Platform | Command | Output file |
|---|---|---|
| Claude Code | `canon setup --agent claude` | `.claude/CLAUDE.md` |
| Cursor | `canon setup --agent cursor` | `.cursorrules` |
| GitHub Copilot | `canon setup --agent copilot` | `.github/copilot-instructions.md` |
| Codex | `canon setup --agent codex` | `AGENTS.md` |
| Gemini CLI | `canon setup --agent gemini` | `GEMINI.md` |
| All of the above | `canon setup --agent all` | All five files |

Each generated file is ~20 lines. It tells the agent that Canon specs exist, points at `CANON.yaml`, and explains how to access spec context (via the Canon MCP tools or the `canon` CLI). The files are committed to the repo and only need regenerating when Canon ships a new agent-config template.

## Slash Commands

These slash commands appear in `/` autocomplete in any session where the Canon plugin is installed. Each is a thin wrapper that delegates to the corresponding skill — the skill remains the source of truth.

| Command | Wraps | What it does |
|---|---|---|
| `/canon` | `canon-meta` | Entry point — opens skill discovery and helps you pick the right Canon skill |
| `/canon-context` | `canon-context` | Load spec context for the current task |
| `/canon-plan` | `canon-plan` | Explore → propose → spec → design → tasks → implementation plan |
| `/canon-task` | `canon-task` | Pick up a single task from a spec and implement its acceptance criteria |
| `/canon-verify` | `canon-verify` | Check whether code satisfies spec acceptance criteria (report or `--gate` mode) |
| `/canon-status` | `canon-status` | Show spec coverage dashboard for the current repo |

Slash commands accept arguments — for example `/canon-task auth-hardening:2.1` jumps directly to that section.

## Output Style

Canon ships a `canon` output style that formats acceptance criteria, section status changes, realization evidence, and coverage tables consistently. Select it via `/config` → "Output style" → "canon". It's optional — Claude Code's default style still works fine for Canon repos.

## Statusline (optional)

> **Platform note**: Claude Code's plugin system does not currently support shipping a statusline directly from a plugin. Canon ships a reference script you can wire into your user-level statusline manually.

Canon includes a reference statusline script at `plugin/scripts/canon-statusline.sh` that emits a one-line summary of spec health for the active project:

```
canon: 44 specs · 53% · 12 in_progress · 873 open ACs
```

To enable it globally:

```bash
cp ~/.claude/plugins/marketplaces/canon/plugin/scripts/canon-statusline.sh ~/.claude/canon-statusline.sh
chmod +x ~/.claude/canon-statusline.sh
```

Then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/canon-statusline.sh"
  }
}
```

The script exits silently in non-Canon repos, so you can leave it on globally without affecting other projects.

## Skills

### Spec Management
| Skill | Description |
|-------|-------------|
| `/canon:context` | Load spec context for your current task |
| `/canon:new` | Create a new spec from template |
| `/canon:status` | Show spec coverage dashboard |
| `/canon:review` | Review changes against all documentation |
| `/canon:update` | Update spec statuses from code evidence |
| `/canon:audit` | Full spec audit with ticket sync |
| `/canon:verify` | Verify code against spec acceptance criteria (report or gate mode) |

### Development Execution
| Skill | Description |
|-------|-------------|
| `/canon:plan` | Spec-driven planning: explore → propose → spec → design → tasks → implementation plan |
| `/canon:task` | Pick up a single task, implement ACs, mark done |
| `/canon:implement` | Execute a multi-task implementation plan with spec traceability |
| `/canon:worktree` | Create an isolated git worktree for spec-driven work |
| `/canon:branch` | Complete a branch: verify, update spec statuses, merge/PR/cleanup |
| `/canon:meta` | Skill discovery — find the right Canon skill for your task |

## How It Works

Canon treats documentation as living programs. Specs define requirements with structured acceptance criteria. The plugin helps you:

1. **Stay in context** — automatically surfaces relevant specs when you're working
2. **Verify implementation** — checks code against spec ACs, marks them realized
3. **Track progress** — coverage dashboard shows what's done and what's left
4. **Keep docs current** — detects drift between code and documentation

## Spec Format

Specs live in `docs/specs/*.md` with YAML frontmatter:

```yaml
---
title: "Feature Name"
type: spec
status: draft
owner: "name"
team: "team-name"
tags: [auth, api]
---
```

Sections use numbered headings with acceptance criteria:

```markdown
## 1. Login Flow

<!-- canon:system:1 status:in_progress -->

### Acceptance Criteria

- [x] Email validation
- [ ] Rate limiting
<!-- canon:realized-in:PR#42 file:src/auth.py:10-25 -->
```

## MCP Server

The plugin bundles a Canon MCP server that provides:
- `search` — hybrid search across specs
- `get_spec` / `get_section` — read parsed spec data
- `create_spec` — create new specs from templates
- `update_section_status` — update section statuses
- `add_realization` — link code evidence to ACs
- `sync_spec_status` — bulk updates in one commit

All commands work without MCP using local file operations. MCP adds semantic search, write-back to GitHub, and org-wide coverage metrics.

## Configuration

The plugin reads `CANON.yaml` from your repo root:

```yaml
specs:
  doc_paths:
    - "docs/specs/*.md"
  require_review: true

agents:
  pr_analysis: true
  doc_updates: true
```

Run `canon setup` or use the GitHub Action to set up a new repo.

## Agents

| Agent | Description |
|-------|-------------|
| `canon-reviewer` | Spec-aware code review — checks changes against acceptance criteria, categorizes findings as Spec Gap, Spec Conflict, Quality Issue, or Suggestion |

## Integration with External Plugins

Canon's spec context is available to any Claude Code skill via the Canon MCP server. External plugins (like superpowers for TDD/debugging) can query spec context:

- `mcp__canon__get_spec` — load a full spec with all sections and ACs
- `mcp__canon__get_section` — load a specific section by ID
- `mcp__canon__search` — find specs relevant to current work

This means TDD skills can know *what* they're testing (the AC), debugging skills can know *what should work* (the spec), and code review skills can check *spec compliance* (not just code style).

### Recommended Companion Plugins

- **superpowers** — TDD, systematic debugging, verification discipline
