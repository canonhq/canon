---
name: canon-update
description: >
  Update spec statuses based on code implementation evidence. Use after
  implementing features to keep specs in sync with reality. Scans the codebase
  for implementation evidence and proposes status transitions.
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - mcp__canon__get_spec
  - mcp__canon__get_section
  - mcp__canon__search
  - mcp__canon__update_section_status
  - mcp__canon__add_realization
  - mcp__canon__sync_spec_status
---

# Update Spec Statuses

You are scanning the codebase to update spec statuses based on implementation evidence.

## Quick Status Updates with CLI

For simple status transitions, use the CLI directly:

```bash
canon start <section-id>   # Mark section as in_progress
canon done <section-id>    # Mark section as done
```

Add `--issue` to create/update GitHub Issues alongside the status change:

```bash
canon start <section-id> --issue
canon done <section-id> --issue
```

For bulk automated updates based on code evidence, continue with the workflow below.

## Step 1: Load Specs

If the user specifies a spec, load it. Otherwise, load all specs:
- MCP: `mcp__canon__list_specs` then `mcp__canon__get_spec` for each
- Local: `Glob` for `docs/specs/*.md` then `Read` each

## Step 2: Scan for Implementation Evidence

For each spec section with unchecked ACs or non-done status:

1. **Search the codebase** for implementation:
   - `Grep` for function names, class names, or keywords from the AC
   - Check recent git commits: `git log --oneline --since="30 days ago"`
   - Look at test files for test coverage of the requirement

2. **Evaluate** each section:
   - All ACs checked + code exists → **done**
   - Some ACs checked + active work → **in_progress**
   - No ACs checked + no code → stays as-is

## Step 3: Propose Updates

Present proposed changes as a table:

| Section | Current | Proposed | Evidence |
|---------|---------|----------|----------|
| 1.1 Password Reset | todo | in_progress | `src/auth/reset.py` exists, 2/3 ACs done |
| 2. OAuth | todo | done | Full implementation in `src/auth/oauth/` |

## Step 4: Apply Updates

Ask the user to confirm before applying. Then:

**With MCP (preferred):** Use `mcp__canon__sync_spec_status` for bulk updates in a single commit.

**Without MCP:** Use `Edit` to modify the spec files locally:
- Update status comments: `<!-- canon:system:1.1 status:in_progress -->`
- Check AC boxes: `- [x] Requirement text`

## Status Transitions

Valid states: `draft` → `todo` → `in_progress` → `done`
Also: `blocked` (with reason), `deprecated`

Only propose forward transitions unless there's clear evidence of regression.
