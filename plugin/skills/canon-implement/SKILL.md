---
name: canon-implement
description: >
  Execute an implementation plan task-by-task with spec traceability. Orchestrates
  the canon-task inner loop with plan-level automation: worktree setup, commits,
  reviewer dispatch, and branch completion. Use when you have a plan from
  canon-plan Phase 6 to execute.
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
  - mcp__canon__sync_spec_status
  - Agent
---

# Execute Implementation Plan

You are executing a multi-task implementation plan with spec traceability at every
step. This skill orchestrates the `canon-task` inner loop (load spec → implement
ACs → verify → record evidence) for each task in a plan, adding automation between
tasks.

**Relationship to canon-task:** `canon-task` is interactive and single-section —
user picks one task, implements it, done. `canon-implement` runs the same AC-driven
inner loop for each task in a plan file, adding worktree setup, commits, reviewer
dispatch, verification gates, and branch completion. Use `canon-task` for one-off
work. Use `canon-implement` for multi-section plans.

## Step 1: Load Plan

Accept a plan file path as argument. If none provided, list available plans from
both the canonical location and common misplaced locations:

```bash
# Canonical location (always preferred)
ls docs/canon/plans/*.md 2>/dev/null

# Misplaced locations — surface them, but nudge migration
ls .claude/plans/*.md docs/superpowers/plans/*.md 2>/dev/null
```

If any plans are found outside `docs/canon/plans/`, print a single-line warning
before the selection prompt that names the actual misplaced source paths:

```
⚠ Plans found outside docs/canon/plans/:
    <list each misplaced plan, one per line>
  To move them into the canonical location, run:
    mkdir -p docs/canon/plans
    git mv <misplaced-plan> docs/canon/plans/   # repeat per file
  canon-implement can still run plans from their current location, but
  canon-branch and the spec-coverage tooling expect them under docs/canon/plans/.
```

Generate the `git mv` commands from the actual hits — do not hard-code
`.claude/plans/*.md` (the misplaced plan may be under `docs/superpowers/plans/`
or any other non-canonical path that the scan picks up).

Do **not** auto-migrate plans — the user may have intentional state in those
locations from another plugin (e.g. `superpowers:writing-plans`). Detection +
nudge keeps the canonical location authoritative without destroying user state.

Parse the plan to extract:
- Task list with dependencies
- Spec references (section IDs and ACs per task)
- File paths per task
- Setup commands from the plan header

Present the task overview to the user:
```
Plan: <plan-name>
Spec: <spec-file>
Tasks: N total (N independent, N with dependencies)

  1. [  ] Task one (S) — Section 2.1, 3 ACs
  2. [  ] Task two (M) — Section 2.2, 2 ACs [depends on: 1]
  3. [  ] Task three (S) — Section 3.1, 4 ACs
  ...

Proceed? (yes / review task N / skip to task N)
```

## Step 2: Setup

If not already in a worktree, suggest invoking `canon-worktree`:
```
Not in a git worktree. Run /canon:worktree first for isolation,
or continue in the current workspace.
```

Run any setup commands listed in the plan header.

## Step 3: Execute Tasks

For each task, respecting dependency order:

### 3a. Announce
```
--- Task N/<total>: <subject> [spec:<section-id>] ---
```

### 3b. Load Spec Context
Load the linked spec section via MCP (`mcp__canon__get_section`) or by reading
the spec file directly. Present the target ACs:
```
Target ACs for this task:
  [ ] AC text one
  [ ] AC text two
```

### 3c. Companion Skill Check
Before implementing, check if development discipline skills are available:
- If a TDD skill is in the session, suggest writing a failing test for the AC first
- This is recommended but not required — Canon suggests, doesn't enforce

### 3d. Implement (canon-task inner loop)
1. Search the codebase for existing relevant code
2. Implement the requirement
3. For each AC, verify the implementation satisfies it

### 3e. Record Realization Evidence
For each completed AC, record evidence via MCP:
```
mcp__canon__add_realization(
  section_id="2.1",
  ac_text="Rate limit: max 3 resets per hour",
  code_file="src/auth/rate_limit.py",
  lines="42-60"
)
```

Or insert realization comments directly in the spec file:
```markdown
- [x] Rate limit: max 3 resets per hour
<!-- canon:realized-in: file:src/auth/rate_limit.py:42-60 -->
```

### 3f. Verify (gate mode)
Run `canon verify --gate --section <id>` for the relevant section. This checks
that every in-scope AC is marked as checked. Then run the project's test suite
(`uv run pytest`, `npm test`, etc.) to confirm tests pass.

If gate **passes** and tests **pass**: proceed to spec-aware review.
If either **fails**: stop and present diagnostic context:
```
Gate failed for Task N:
  - AC "..." lacks realization evidence
  - Tests failing: <summary>

Options: fix now / skip task / abort plan
```

If a debugging skill is available in the session (e.g.,
`superpowers:systematic-debugging`), suggest invoking it before retrying.
Detection is opportunistic — never hard-depend on external plugins. If no
debugging skill is loaded, proceed with the standard fix-and-retry flow.

### 3f.5. Spec-Aware Review

Before committing, dispatch the **canon-reviewer** agent via the Agent tool to
verify that the code actually satisfies the AC (not just that the AC is marked
checked). Pass:

- The git diff of the just-completed task (`git diff HEAD`)
- The spec section ID and AC list from Step 3b
- The project conventions from `CLAUDE.md` if present

The reviewer categorizes findings as **Spec Gap**, **Spec Conflict**, **Quality
Issue**, or **Suggestion**. Apply the severity rules:

- **Spec Gap or Spec Conflict** → STOP the plan. Present the findings and offer:
  fix now / skip task / abort plan.
- **Quality Issue or Suggestion** → print the findings but proceed to commit.
  These are advisory and do not block plan execution.

The two-layer verification (gate + reviewer) catches the case where an AC is
marked checked but the implementation is wrong or incomplete.

### 3g. Commit
```bash
git add <files changed>
git commit -m "feat(<scope>): <description> [spec:<spec-slug>:<section-id>]"
```

### 3h. Update Plan Progress
Mark the task as done in the plan file:
```markdown
  - [x] Task N: <subject>
```

## Step 4: Parallel Mode (--parallel)

When independent tasks have no dependency edges between them, they can be
dispatched to subagents:

1. Identify independent task groups from the dependency graph
2. For each independent task, dispatch a subagent via the Agent tool:
   - Include: task definition, spec section content, project setup instructions
   - The subagent runs steps 3a-3h for its task
3. Collect results from all subagents
4. Verify all gates passed
5. Commit sequentially (to maintain clean git history)

Use sequential mode by default. Parallel mode is for plans with many independent
tasks where speed matters.

## Step 5: Completion

When all tasks are done:
```
Plan complete: N/N tasks done

Invoke /canon:branch to verify, update spec statuses, and merge/PR.
```

If any tasks failed or were skipped:
```
Plan partially complete: N/M tasks done, K skipped/failed

Completed:
  [x] Task 1: ...
  [x] Task 3: ...

Skipped/Failed:
  [ ] Task 2: <reason>

Fix remaining tasks manually or re-run /canon:implement to retry.
```

## Interruption Recovery

If the session is interrupted mid-plan, the plan file's checkboxes show which
tasks completed. Re-running `/canon:implement` on the same plan file will skip
already-checked tasks and resume from the first unchecked task.
