---
name: canon-audit
description: >
  Full spec audit: scan codebase for implementation evidence, update spec
  statuses, sync to ticket system, and commit. Combines canon-update + sync
  into a single workflow. Use periodically to keep specs accurate.
allowed-tools:
  - Read
  - Edit
  - Glob
  - Grep
  - Bash
  - Task
  - mcp__canon__list_specs
  - mcp__canon__get_spec
  - mcp__canon__get_section
  - mcp__canon__search
  - mcp__canon__update_section_status
  - mcp__canon__add_realization
  - mcp__canon__sync_spec_status
---

# Spec Audit

You are running a full spec audit: scanning the codebase for implementation evidence, updating spec statuses, syncing to the ticket system, and committing.

## Step 1: Discover All Specs

Find every spec file:
- MCP: `mcp__canon__list_specs` to get all specs
- Local fallback: `Glob` for `docs/specs/*.md`

## Step 2: Audit Each Spec in Parallel

For each spec, launch a **Task agent** (subagent_type=Explore) that:

1. Reads the full spec
2. For each numbered section with a non-done status:
   - Searches the codebase for implementation of its acceptance criteria
   - Checks for relevant files, functions, tests, routes, components
   - Evaluates: all ACs met → **done**, some met → **in_progress**, none → stays as-is
3. Returns a table: section number, title, current status, recommended status, evidence summary

**Important**: Launch agents in parallel (multiple Task calls in one message) to audit specs concurrently. Group into batches of 4-5 if there are many specs.

Background sections (§1 "Background" with only context, no ACs) should be marked `done` since they are informational — they should never generate tickets.

## Step 3: Present Audit Summary

Compile results into a summary table:

| Spec | Section | Current | Proposed | Evidence |
|------|---------|---------|----------|----------|
| auth-hardening | §2 Login Providers | todo | done | LoginView.vue, routes.py |
| auth-hardening | §5 RBAC | todo | todo | org_members table missing |

Show totals: X sections to update, Y already correct, Z unchanged.

## Step 4: Apply Status Updates

After user confirms (or immediately if they said "just do it"):

1. **Edit spec files** to update status comments:
   - `<!-- canon:system:N status:done -->` for completed sections
   - `<!-- canon:system:N status:in_progress -->` for partial implementations
   - Fix any non-standard status comments (e.g., `<!-- status: todo -->` → `<!-- canon:system:N status:todo -->`)
2. **Check off realized ACs**: For each AC that Claude evaluated as "realized" with medium/high confidence, the audit checks the checkbox (`- [ ]` → `- [x]`) and inserts a realization evidence comment (`<!-- canon:realized-in:audit file:PATH:LINES -->`). Use `--no-ac-updates` to skip this.
3. Update spec-level frontmatter `status:` if appropriate (all sections done → spec done)

## Step 5: Sync to Ticket System

Run the sync CLI to create/update GitHub Issues:

```bash
uv run canon sync --dry-run
```

Show the dry-run output to the user. If it looks right:

```bash
uv run canon sync
```

This creates issues only for `todo` and `in_progress` sections — done/draft/deprecated sections are skipped.

## Step 6: Commit and Push

Stage the updated spec files and commit:

```bash
git add docs/specs/*.md
git commit -m "docs: update spec statuses based on codebase audit

<summary of changes>"
git push
```

## Status Transition Rules

- Only propose **forward** transitions unless there's clear evidence of regression
- Valid states: `draft` → `todo` → `in_progress` → `done`
- Also: `blocked` (with reason), `deprecated`
- Background/context sections with no ACs → `done`
- Sections where all ACs are checked and code exists → `done`
- Sections with partial implementation → `in_progress`
- Don't change `todo` sections that have no implementation yet — they're correctly queued for work

## Tips

- If MCP is available, prefer `mcp__canon__sync_spec_status` for bulk updates
- The `canon sync` CLI respects `ticket_project` in spec frontmatter for routing
- Sections with existing ticket links (`<!-- canon:ticket:github:123 -->`) get updated, not duplicated
- Use `--dry-run` on sync to preview before creating issues
