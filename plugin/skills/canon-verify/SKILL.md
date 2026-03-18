---
name: canon-verify
description: >
  Verify code implementation against spec acceptance criteria. Use when you want
  to check if code satisfies spec requirements, after implementing a feature,
  or during code review. Evaluates each AC as realized, partial, or conflicting.
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - mcp__canon__get_spec
  - mcp__canon__get_section
  - mcp__canon__search
  - mcp__canon__add_realization
  - mcp__canon__update_section_status
---

# Verify Code Against Spec

You are verifying whether the current codebase satisfies a spec's acceptance criteria.

## Quick Check with CLI

Try the CLI first for a fast static check:

```bash
canon verify
```

Or for a specific section:

```bash
canon verify --section <id>
```

This greps the codebase for keywords from each unchecked AC and classifies them
as "likely realized", "not started", or "unknown". Use the results as a starting
point, then do deeper analysis with the steps below.

## Step 1: Load the Spec

If the user specifies a spec file, load it directly. Otherwise, identify the relevant spec:
- Check recent changes: `git diff --name-only HEAD`
- Search for matching specs using MCP `search` or local `Glob` + `Grep`

Load the full spec with `mcp__canon__get_spec` or `Read`.

## Step 2: Evaluate Each Acceptance Criterion

For each AC checkbox in the spec:

1. **Search the codebase** for implementation evidence using `Grep` and `Read`
2. **Classify** the AC:
   - **Realized** — code fully implements the requirement
   - **Partial** — code partially implements it (explain what's missing)
   - **Not Started** — no implementation found
   - **Conflicting** — implementation contradicts the requirement

## Step 3: Present Results

Format as a table:

| AC | Status | Evidence |
|----|--------|----------|
| Rate limiting | Realized | `src/auth/rate_limit.py:42-60` |
| Email validation | Partial | Validates format but not domain |
| OAuth support | Not Started | — |

## Step 4: Offer Write-Back (MCP only)

If MCP is available, offer to:
- Update section statuses: `mcp__canon__update_section_status`
- Record realization evidence: `mcp__canon__add_realization`

Ask the user before making any writes.

## Spec Format Reference

AC checkboxes appear under `### Acceptance Criteria` headings:
```markdown
- [x] Checked (done)
- [ ] Unchecked (not done)
```

Realization comments appear after ACs:
```
<!-- canon:realized-in:PR#42 file:src/auth.py:10-25 -->
```
