---
name: canon-plan
description: Spec-driven planning — explore, propose, spec, design, tasks, implementation plan
argument-hint: "[feature description or spec file]"
---

The user invoked `/canon-plan`. Use the Skill tool to invoke the **canon-plan** skill, which guides the user through the spec-driven planning workflow:

1. Explore the codebase for relevant context
2. Propose an approach
3. Create or update a spec
4. Add design details
5. Break into tasks
6. Optionally generate a file-level implementation plan executable by `canon-implement`

If $ARGUMENTS contains a feature description, start from Phase 1 (Explore). If it contains an existing spec file path, jump to Phase 5 (Tasks) or Phase 6 (Implementation Plan).

## Phase 6 plan-path sanity check (enforce on exit)

If you write a Phase 6 implementation plan, after the file is created you **must**
verify it landed at the canonical location. Run this Bash check before reporting
completion:

```bash
plan_path="<path you just wrote>"
if [[ "$plan_path" != docs/canon/plans/* ]]; then
  echo "ERROR: plan written to non-canonical path: $plan_path"
  echo "Move it to docs/canon/plans/ and report the corrected path:"
  echo "  mkdir -p docs/canon/plans && git mv \"$plan_path\" docs/canon/plans/"
  exit 1
fi
```

If the assertion fails, move the plan to `docs/canon/plans/` with `git mv` and
re-report the corrected path. Never tell the user the plan is ready while it
sits outside `docs/canon/plans/` — `canon-implement` and `canon-branch` both
depend on the canonical location.
