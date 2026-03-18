# Canon Plugin for Claude Code

AI-native spec documentation — verify code against specs, track coverage, maintain living docs.

## Installation

```
/plugin marketplace add canonhq/canon
/plugin install canon
```

## Commands

| Command | Description |
|---------|-------------|
| `/canon:context` | Load spec context for your current task |
| `/canon:task` | Pick up a task, implement ACs, mark done |
| `/canon:verify` | Verify code against spec acceptance criteria |
| `/canon:new` | Create a new spec from template |
| `/canon:review` | Review changes against all documentation |
| `/canon:status` | Show spec coverage dashboard |
| `/canon:plan` | Spec-driven planning workflow |
| `/canon:update` | Update spec statuses from code evidence |

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
