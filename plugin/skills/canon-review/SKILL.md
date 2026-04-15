---
name: canon-review
description: >
  Review code changes against all documentation — specs, ADRs, READMEs,
  architecture docs. Broader than verify. Use during code review or before
  merging to catch documentation drift.
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - mcp__canon__search
  - mcp__canon__get_spec
  - mcp__canon__get_doc
  - mcp__canon__list_specs
  - mcp__canon__list_docs
---

# Review Changes Against Documentation

You are reviewing code changes against all project documentation.

## Step 1: Identify Changes

```bash
git diff --name-only HEAD 2>/dev/null || git diff --name-only --cached 2>/dev/null
```

If reviewing a PR, examine all changed files.

## Step 2: Find Relevant Documentation

Search broadly — not just specs but all docs:
- `docs/specs/*.md` — spec files
- `docs/adrs/*.md` — architecture decision records
- `docs/**/*.md` — any documentation
- `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`

Use MCP `search` or local `Glob` + `Grep` to find docs mentioning changed files, functions, or concepts.

## Step 3: Check for Drift

For each relevant doc, check:
1. **Accuracy** — does the doc still accurately describe the code?
2. **Completeness** — are new features/changes reflected in docs?
3. **Consistency** — do docs agree with each other?
4. **Spec compliance** — do code changes align with spec requirements?

## Step 4: Report Findings

Organize findings by severity:

### Must Fix
- Documentation that is now **incorrect** due to code changes
- Spec ACs that are **contradicted** by the implementation

### Should Update
- Docs that are **incomplete** — missing new functionality
- README sections that reference **changed** behavior

### Consider
- Opportunities to **improve** documentation
- Specs that could be **updated** to reflect implementation learnings

## Step 5: Suggest Updates

For each finding, provide specific suggestions for what to change in the documentation.

## Standalone canon-reviewer Dispatch

For tighter spec-compliance review (vs the broad documentation drift check
above), dispatch the **canon-reviewer** agent via the Agent tool. It focuses
narrowly on whether code satisfies spec acceptance criteria and categorizes
findings as **Spec Gap**, **Spec Conflict**, **Quality Issue**, or
**Suggestion** (with severity rules — Spec Gaps and Conflicts are blockers).

Use canon-reviewer when:
- The user wants AC-level verdicts, not documentation drift
- A spec has clearly enumerated ACs you can pass to the reviewer as input
- You're working outside a canon-implement loop (canon-implement dispatches the
  reviewer automatically after each task)

Pass the reviewer: the diff, the spec section ID, and `CLAUDE.md` if present.
