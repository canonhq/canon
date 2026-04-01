# Canon Plugin for Claude Code

AI-native spec documentation — verify code against specs, track coverage, maintain living docs.

## Installation

From the terminal:

```bash
claude plugin marketplace add canonhq/canon
claude plugin install canon
```

Or from inside a Claude Code session:

```
/plugin marketplace add canonhq/canon
/plugin install canon
```

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
