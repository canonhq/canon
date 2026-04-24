# Claude Code Skills

The Canon plugin for Claude Code provides slash commands (skills) for spec-driven development.

## Installation

Add the Canon marketplace and install the plugin:

```bash
claude plugin marketplace add canonhq/canon
claude plugin install canon
```

Skills are then available as `/canon:<skill>` (e.g., `/canon:verify`).

## Spec Management Skills

### `/canon:context` — Load Spec Context

Load spec context for your current task. Automatically identifies relevant specs from git changes or a user-provided topic.

**Usage:**
```
/canon:context
/canon:context auth migration
```

**What it does:**
- Scans git diff to find changed files
- Matches changes against spec sections
- Loads relevant specs, ACs, and ticket links into context

### `/canon:new` — Create a Spec

Create a new spec document from a template.

**Usage:**
```
/canon:new
/canon:new "User Notifications"
```

**What it does:**
- Walks through structured creation with prompts for title, team, tags
- Creates spec file from template
- Optionally commits to git

### `/canon:verify` — Verify Implementation

Verify code against spec acceptance criteria. Use after implementing a feature or during code review.

**Usage:**
```
/canon:verify
/canon:verify docs/specs/auth-hardening.md
/canon:verify --gate              # Pass/fail gate mode
/canon:verify --gate --section 2.1
```

**What it does:**
- Evaluates each AC as realized, partial, or conflicting
- Reports evidence (file, line numbers) for each evaluation
- Suggests spec or code updates for conflicts
- **Gate mode:** acts as a pass/fail blocker — checks all ACs have evidence, tests pass, no conflicts. Used automatically by `canon-implement` and `canon-branch`.

### `/canon:review` — Review Against Docs

Review code changes against all documentation — specs, ADRs, READMEs, architecture docs.

**Usage:**
```
/canon:review
```

**What it does:**
- Scans all indexed docs for conflicts with current changes
- Flags stale documentation
- Suggests doc updates

### `/canon:status` — Coverage Dashboard

Show spec coverage dashboard.

**Usage:**
```
/canon:status
```

**What it does:**
- Displays per-spec and per-section coverage metrics
- Shows realized vs. total acceptance criteria
- Highlights stale or blocked sections

### `/canon:update` — Update Spec Statuses

Update spec statuses based on code implementation evidence.

**Usage:**
```
/canon:update
/canon:update docs/specs/auth-hardening.md
```

**What it does:**
- Scans codebase for implementation evidence
- Proposes status transitions for spec sections
- Applies updates with realization evidence

### `/canon:audit` — Full Spec Audit

Full audit workflow: scan all specs against the codebase, update statuses, sync to ticket system, and commit. Combines `/canon:update` + `canon sync` into a single command.

**Usage:**
```
/canon:audit
```

**What it does:**
- Discovers all specs and audits each against the codebase in parallel
- Updates section statuses based on implementation evidence
- Runs `canon sync` to create/update GitHub Issues for actionable sections
- Commits and pushes the changes

## Development Execution Skills

### `/canon:plan` — Spec-Driven Planning

Start a spec-driven planning workflow from exploration through spec creation to implementation tasks and detailed implementation plans.

**Usage:**
```
/canon:plan
```

**What it does:**
- **Phase 1-2:** Explores codebase, proposes approach
- **Phase 3-4:** Creates spec with sections, ACs, and technical design
- **Phase 5:** Generates task list mapped to spec sections
- **Phase 6:** Produces a file-level implementation plan with exact file paths, code approach, and complexity estimates — ready for `/canon:implement`

### `/canon:interrogate` — Adversarial Spec Review

Adversarial review of specs and implementation plans. Challenges ACs for testability, validates codebase assumptions, surfaces missing edge cases, and flags scope issues — before implementation begins. Use after `/canon:plan` or when reviewing an existing spec for quality.

**Usage:**
```
/canon:interrogate
/canon:interrogate docs/specs/auth-hardening.md
/canon:interrogate docs/canon/plans/2026-03-31-auth-hardening.md
```

**What it does:**
- **Pass 1 — AC Quality:** Evaluates each acceptance criterion for testability, specificity, measurability, independence, and scope
- **Pass 2 — Codebase Assumptions:** Validates every file path, function, pattern, and dependency referenced in the spec or plan
- **Pass 3 — Missing Concerns:** Checks whether the spec addresses error handling, edge cases, security, migration, backwards compatibility, observability, rollback, and performance
- **Pass 4 — Plan Coherence (plans only):** Verifies AC coverage, task-to-AC mapping, dependency ordering, scope creep, placeholders, and file conflicts
- Produces a findings report (Blockers / Warnings / Questions) and a clear **PASS** or **FAIL** verdict
- **PASS:** no blockers — recommends proceeding to `/canon:implement`
- **FAIL:** lists blockers that must be fixed before implementation; re-run to confirm fixes

### `/canon:task` — Work on a Task

Pick up a spec-driven task, work through its acceptance criteria, and mark it done. Best for single-section, interactive work.

**Usage:**
```
/canon:task
```

**What it does:**
- Lists available tasks from spec acceptance criteria
- Guides you through implementation of each AC
- Marks ACs as realized with code evidence
- Updates spec status when all ACs are done
- Suggests TDD and debugging skills when companion plugins are available

### `/canon:implement` — Execute an Implementation Plan

Execute a multi-task implementation plan end-to-end with spec traceability. Orchestrates the `canon-task` inner loop across all tasks in a plan.

**Usage:**
```
/canon:implement
/canon:implement docs/canon/plans/2026-03-31-auth-hardening.md
```

**What it does:**
- Loads a plan from `docs/canon/plans/` and executes each task in dependency order
- For each task: loads spec context → implements ACs → verifies → records realization evidence → commits
- Runs `canon verify --gate` after each task
- Commits with spec references (e.g., `feat(auth): rate limiting [spec:auth-hardening:2.1]`)
- Tracks progress in the plan file (checkboxes)
- Supports `--parallel` mode for independent tasks via subagents
- Calls `canon-branch` on completion

### `/canon:worktree` — Create Isolated Worktree

Create an isolated git worktree for spec-driven work. Use before executing implementation plans or when you need workspace isolation.

**Usage:**
```
/canon:worktree
```

**What it does:**
- Creates a named worktree branched from HEAD (`canon/<spec-slug>/<section-id>`)
- Verifies the worktree directory is git-ignored
- Auto-detects and runs project setup (npm install, uv sync, cargo build, etc.)
- Verifies clean baseline by running tests
- Loads relevant spec context into the session

### `/canon:branch` — Complete a Branch

Complete a development branch: verify specs, update statuses, and merge/PR/cleanup.

**Usage:**
```
/canon:branch
```

**What it does:**
- Runs `canon verify --gate` for all spec sections touched on the branch
- Updates spec section statuses to `done` where all ACs are realized
- Offers 4 options: merge, push+PR, keep as-is, or discard
- Generates PR descriptions with spec coverage (which ACs this PR satisfies)
- Cleans up worktree after merge or discard

### `/canon:meta` — Skill Discovery

Find the right Canon skill for your task. Lists all skills with trigger conditions, workflow chains, and a rationalization table.

**Usage:**
```
/canon:meta
```

**What it does:**
- Maps all Canon skills with when to invoke each one
- Shows common workflow chains (new feature, single task, audit, review, spec drift)
- Provides a rationalization table addressing common reasons to skip spec-driven workflows
- Lists recommended companion plugins (e.g., superpowers for TDD)

## Agents

### `canon-reviewer` — Spec-Aware Code Review

A subagent that reviews code changes against spec acceptance criteria. Focus is on spec compliance, not just code style.

**What it does:**
- Reviews git diff against linked spec sections and ACs
- Categorizes findings: **Spec Gap** (AC not satisfied), **Spec Conflict** (contradicts AC), **Quality Issue**, **Suggestion**
- Automatically dispatched after each task in `canon-implement`
- Can be invoked standalone via `canon-review`
