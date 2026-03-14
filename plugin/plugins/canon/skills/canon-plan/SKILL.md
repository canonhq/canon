---
name: canon-plan
description: >
  Spec-driven planning workflow inspired by OpenSpec. Use when starting a new
  feature or project to go from exploration through spec creation to
  implementation tasks. Follows the explore-propose-spec-design-tasks lifecycle.
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

## Workflow Tips

- Don't skip exploration — understanding context prevents rework
- Keep ACs specific and testable
- Design docs should live alongside specs, not separately
- Tasks should map back to spec sections for traceability
