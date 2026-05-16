---
name: canon-plan
description: >
  Spec-driven planning workflow inspired by OpenSpec. Use when starting a new
  feature or project to go from exploration through spec creation to
  implementation tasks and detailed implementation plans. Follows the
  explore-propose-spec-design-tasks-plan lifecycle.
allowed-tools:
  - Read
  - Write
  - Glob
  - Grep
  - Bash
  - mcp__canon__search
  - mcp__canon__get_spec
  - mcp__canon__get_doc
  - mcp__canon__create_spec
---

# Spec-Driven Planning

You are guiding the user through a spec-driven planning workflow.

## Quick Task Extraction with CLI

For an existing spec, try the CLI first to extract a structured task plan:

```bash
canon plan <spec-file>
```

This parses the spec, lists todo/in_progress sections as tasks with ACs as
subtasks, and includes dependency information. Use this as a starting point
for the planning workflow below.

## Phase 1: Explore

Understand the current state:
1. What exists in the codebase relevant to this work?
2. Are there existing specs that overlap or depend on this?
3. What constraints exist (architecture, dependencies, timeline)?

Search with MCP `search` or local `Glob` + `Grep` to find related code and docs.

## Phase 2: Propose

Based on exploration, propose an approach:
1. **Scope** — what will this spec cover?
2. **Approach** — high-level technical direction
3. **Dependencies** — what does this depend on?
4. **Risks** — what could go wrong?

Present this as a short proposal for the user to approve before writing the full spec.

## Phase 3: Spec

Create the spec document:
1. Use `/canon:new` or `mcp__canon__create_spec` to create the file
2. Fill in:
   - Background and motivation
   - Requirements with specific acceptance criteria
   - Technical design
   - Rollout plan

Each AC should be:
- **Specific** — testable, not vague
- **Independent** — can be verified on its own
- **Valuable** — directly ties to user value

## Phase 4: Design

Add technical design details:
1. Architecture decisions
2. API contracts
3. Data model changes
4. Integration points

## Phase 5: Tasks

Break the spec into implementation tasks:
1. Map each section/AC to concrete work items
2. Identify dependencies between tasks
3. Suggest implementation order
4. Estimate relative complexity

Present as a task list the user can use directly or sync to their ticket system.

## Phase 6: Implementation Plan

Optionally generate a detailed, executable plan that `canon-implement` can run.
This goes beyond Phase 5's task list — each task must have enough detail for a
subagent to execute without additional context.

### Plan File Location

You **MUST** save the plan to:

```
docs/canon/plans/YYYY-MM-DD-<spec-slug>.md
```

Do **not** write to any of these locations, even if another plan-writing skill
(e.g. `superpowers:writing-plans`) suggests them:

- `.claude/plans/...` — Claude's session-scratch directory
- `docs/superpowers/plans/...` — superpowers plugin convention
- repo root, `docs/plans/`, `plans/`, or any other ad-hoc path

If `docs/canon/plans/` does not yet exist, create it (`mkdir -p docs/canon/plans`).
The canonical location is how `/canon:implement` discovers plans and how
`canon-branch` ties plan files back to spec sections; writing elsewhere silently
breaks both flows.

### Plan Header (required)

```markdown
# Implementation Plan: <Feature Name>

**Spec:** `docs/specs/<spec-file>.md`
**Sections covered:** <list of section IDs>
**Dependencies:** <external dependencies or setup needed>
**Setup commands:** <commands to run before starting>
```

### Task Structure (required per task)

Each task must include:
1. **Spec reference** — section ID and specific ACs this task addresses
2. **File paths** — exact files to create or modify
3. **What to change** — concrete description of the implementation approach
4. **Complexity** — S (< 30 min), M (30-60 min), L (> 60 min)
5. **Dependencies** — which other tasks must complete first

### Quality Gates

- NO placeholders: "TBD", "implement later", "add logic here" are forbidden
- Every task must map to at least one spec AC
- Every AC in scope must be covered by at least one task

### Self-Review Checklist

Before presenting the plan to the user:
- [ ] Plan file path starts with `docs/canon/plans/` and matches the
  `YYYY-MM-DD-<spec-slug>.md` shape (no `.claude/plans/`, no `docs/superpowers/plans/`)
- [ ] Every task has exact file paths
- [ ] Every AC in scope is covered by a task
- [ ] Dependencies between tasks are identified
- [ ] No placeholder language exists
- [ ] Setup commands are complete and tested

### Handoff

Before implementing, suggest an adversarial review:

```
Plan ready. Before implementing, consider running /canon:interrogate to
red-team this plan — it will challenge AC quality, validate codebase
assumptions, and surface missing edge cases.
```

Once the plan is approved (and optionally interrogated), the user can execute
it with `/canon:implement`.

## Workflow Tips

- Don't skip exploration — understanding context prevents rework
- Keep ACs specific and testable
- Design docs should live alongside specs, not separately
- Tasks should map back to spec sections for traceability
- Phase 6 is optional — use it when the work is complex enough to need subagent execution
