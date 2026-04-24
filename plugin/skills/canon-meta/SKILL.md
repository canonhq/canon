---
name: canon-meta
description: >
  Skill discovery and enforcement for Canon. Documents when each Canon skill
  should be invoked and prevents rationalization of skipping spec-driven workflows.
  Use at the start of any conversation or when unsure which Canon skill applies.
allowed-tools:
  - Read
  - Glob
  - Grep
---

# Canon Skill Discovery

You are helping the user find and use the right Canon skill for their task.

## Skill Map

| Skill | Invoke when... |
|-------|---------------|
| **canon-context** | Starting any task, investigating code, reviewing a PR, or needing spec background |
| **canon-plan** | Planning a new feature or project — goes from exploration through spec to implementation plan |
| **canon-new** | Creating a new spec, proposal, ADR, or design document from a template |
| **canon-task** | Picking up a single task from a spec and implementing its acceptance criteria |
| **canon-implement** | Executing a multi-task implementation plan with spec traceability, worktrees, and review |
| **canon-worktree** | Need an isolated workspace for feature work or before executing a plan |
| **canon-branch** | Done with a development branch — verify, update spec statuses, merge/PR/cleanup |
| **canon-interrogate** | Adversarial review of a spec or plan — challenges ACs, validates assumptions, surfaces gaps before implementation |
| **canon-verify** | Checking whether code satisfies spec acceptance criteria (report or gate mode) |
| **canon-review** | Reviewing code changes against all documentation — specs, ADRs, READMEs |
| **canon-update** | Updating spec statuses based on code implementation evidence |
| **canon-audit** | Periodic full audit — scan codebase, update all specs, sync tickets |
| **canon-status** | Quick dashboard of overall spec coverage and project health |

## Workflow Chains

Common sequences where one skill leads to the next:

```
New feature:     canon-plan → canon-interrogate → canon-worktree → canon-implement → canon-branch
Single task:     canon-context → canon-task → canon-verify
Code review:     canon-context → canon-review
Periodic audit:  canon-audit → canon-status
Spec drift:      canon-update → canon-status
```

## Rationalization Table

These thoughts mean STOP — you're about to skip spec-driven workflow:

| Thought | Reality |
|---------|---------|
| "This is just a quick fix" | Quick fixes drift specs. Run `canon-context` to check if a spec covers this. |
| "The spec doesn't exist yet" | Use `canon-new` to create one. Even a 5-minute spec prevents rework. |
| "I'll update the spec later" | Later never comes. Record realization evidence now with `canon-verify`. |
| "This isn't covered by a spec" | Run `canon-context` or MCP `search` — it probably is. |
| "The spec is outdated" | Use `canon-update` to fix it. An outdated spec is a bug, not an excuse. |
| "I know what to do, I don't need the spec" | The spec isn't for you — it's for the next person. Keep it current. |
| "I'll just do this one thing first" | Load context first. 30 seconds of `canon-context` saves 30 minutes of rework. |

## Companion Plugins

Canon covers the **spec-driven workflow** — it doesn't duplicate generic development
discipline. These external plugins complement Canon well:

- **superpowers** — TDD (red-green-refactor), systematic debugging, verification
  discipline. Canon's spec context (via MCP) enriches these workflows: TDD skills
  can know *what* they're testing (the AC), debugging skills can know *what should
  work* (the spec requirement).

Canon skills detect when companion plugins are available and suggest invoking them
at appropriate points (e.g., before implementing an AC, suggest TDD if available).

## Spec Context via MCP

Any skill — Canon or external — can query spec context through the Canon MCP server:

- `mcp__canon__search` — find specs relevant to a topic or file
- `mcp__canon__get_spec` — load a full spec with all sections and ACs
- `mcp__canon__get_section` — load a specific section by ID
- `mcp__canon__get_doc` — get raw markdown for any indexed document
