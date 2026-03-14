---
name: canon-task
description: >
  Pick up a spec-driven task, work through its acceptance criteria, and mark it
  done. Bridges the canon CLI workflow with Claude Code's interactive
  capabilities for a guided implementation experience.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - mcp__canon__get_spec
  - mcp__canon__get_section
  - mcp__canon__search
  - mcp__canon__add_realization
  - mcp__canon__update_section_status
---

# Spec-Driven Task Workflow

You are guiding the user through a spec-driven development task — picking up a
work item, implementing it against acceptance criteria, and marking it done.

## Step 1: Show Available Tasks

Try the CLI first for a quick overview:

```bash
canon tasks
```

If the CLI is not available, fall back to local parsing:
1. `Glob` for `docs/specs/*.md`
2. `Read` each spec, find sections with `todo` or `in_progress` status

Present available tasks as a numbered list:
```
Available tasks:
  1. [1] Login Flow (todo) — 0/3 ACs
  2. [2] OAuth (todo) — 0/2 ACs
  3. [3.1] Password Reset (in_progress) — 1/4 ACs
```

Ask the user which task to pick up.

## Step 2: Start the Task

Mark the selected section as `in_progress`:

```bash
canon start <section-id>
```

Or fall back to editing the spec file directly — update the status comment:
```
<!-- canon:system:1.1 status:in_progress -->
```

If `--issue` is needed, the CLI can create a GitHub Issue too.

## Step 3: Present Acceptance Criteria

Load the full section and present ACs as an implementation checklist:

```
Task: 1.1 Password Reset (in_progress)

Acceptance Criteria:
  [ ] Reset email sends within 30 seconds
  [x] Token expires after 1 hour
  [ ] Rate limit: max 3 resets per hour per user
  [ ] Reset link works exactly once
```

## Step 4: Implement

Work through each unchecked AC:
1. Search the codebase for existing relevant code
2. Implement the requirement
3. Verify the implementation satisfies the AC

After implementing each AC, offer to check the box in the spec.

## Step 5: Mark Done

When all ACs are satisfied:

```bash
canon done <section-id>
```

Or edit the spec directly to set status to `done`.

## Step 6: Record Realization Evidence

For each completed AC, add realization evidence linking code to the requirement.

If MCP is available:
```
mcp__canon__add_realization(
  section_id="1.1",
  ac_text="Reset email sends within 30 seconds",
  pr_number=42,
  code_file="src/auth/reset.py",
  lines="15-30"
)
```

Without MCP, insert realization comments directly:
```markdown
- [x] Reset email sends within 30 seconds
<!-- canon:realized-in:PR#42 file:src/auth/reset.py:15-30 -->
```

## Workflow Tips

- Always read the full section content before implementing — context matters
- Check existing code first to avoid duplicating work
- Keep ACs atomic — implement and verify one at a time
- If an AC is unclear, ask the user for clarification before implementing
- Use `canon verify` to double-check implementation coverage
