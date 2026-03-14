---
name: canon-status
description: >
  Show a spec coverage dashboard. Use to see overall project status,
  spec progress, and coverage metrics. Works with MCP for org-wide
  metrics or locally by parsing spec files.
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - mcp__canon__get_coverage
  - mcp__canon__list_specs
  - mcp__canon__get_spec
---

# Spec Coverage Dashboard

You are generating a spec coverage dashboard for the user.

## With CLI (preferred — fast local parsing)

Try the CLI first for an instant local dashboard:

```bash
canon status
```

For a single spec detail view:

```bash
canon status --spec <file>
```

If the CLI works, present its output directly. Only fall back to other methods
if the CLI is unavailable or if org-wide metrics are needed.

## With MCP (org-wide metrics)

Use `mcp__canon__get_coverage` to get aggregate metrics:
- Total specs, sections, acceptance criteria
- Coverage percentages (section, AC, realization)
- Health score
- Trend data

Then use `mcp__canon__list_specs` for per-spec breakdown.

## Without MCP (local parsing)

1. Find all specs: `Glob` for `docs/specs/*.md`
2. Read each spec and extract:
   - Frontmatter status
   - Section count and statuses
   - AC counts (total, checked, unchecked)

## Dashboard Format

Present the dashboard as:

```
Spec Coverage Dashboard
========================

Overall: X specs | Y sections | Z acceptance criteria

| Spec | Status | Sections | ACs | Coverage |
|------|--------|----------|-----|----------|
| Auth | in_progress | 4/6 done | 8/12 | 67% |
| Billing | draft | 0/3 done | 0/5 | 0% |

Health Score: XX/100
```

## Section Status Breakdown

For specs the user is interested in, show section-level detail:

```
Auth Spec (in_progress)
  1. Login Flow ........... done
    1.1 Password Reset .... in_progress
  2. OAuth ................ todo
  3. Session Management ... draft
```

## Acceptance Criteria Summary

```
Checked:   8 / 12 (67%)
Realized:  5 / 12 (42%)  ← have code evidence
Unchecked: 4 / 12 (33%)
```
