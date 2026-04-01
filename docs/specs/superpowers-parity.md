---
title: "Superpowers Parity: Development Execution Workflow"
status: draft
owner: nick
team: canon-core
ticket_project: null
created: 2026-03-31
updated: 2026-03-31
tags: [plugin, claude-code, developer-experience, workflow]
---

# Superpowers Parity: Development Execution Workflow

Canon's Claude Code plugin covers the **documentation lifecycle** well (specs, coverage, audit, ticket sync) but lacks the **development execution lifecycle** that the superpowers plugin provides. This spec adds the missing capabilities so Canon covers the full loop: **spec → plan → execute → review → verify → complete**.

## 1. Background

<!-- canon:system:1 status:draft -->

### Problem

Canon's plugin has 9 skills focused on spec management: create, plan, task, verify, review, update, audit, status, context. The superpowers plugin (v5.0.7) has 14 skills focused on development execution: brainstorming, planning, TDD, debugging, worktrees, plan execution, code review, verification, branch completion, and parallel agent dispatch.

Users who want spec-driven development end-to-end must install both plugins, but the plugins don't integrate — superpowers has no awareness of specs, and Canon has no awareness of development discipline workflows. The result is a disjointed experience where spec context is lost during implementation.

### Opportunity

Canon is uniquely positioned to provide **spec-aware development workflows**. When Canon manages both the spec and the execution, it can:

- Auto-load relevant spec context when starting a task
- Trace every code change back to an acceptance criterion
- Run spec-aware code review (not just style — does this satisfy the AC?)
- Gate completion on spec verification, not just test passing
- Record realization evidence automatically during implementation

### Approach: Selective Absorption

We add capabilities that naturally extend Canon's spec-driven identity. We do NOT duplicate generic development discipline (TDD, debugging) that has no spec coupling. Instead, we provide integration points where Canon's spec context enriches those workflows.

**Add to Canon (spec-coupled):**
- Implementation planning with spec traceability
- Plan execution with AC-linked commits
- Spec-aware code review (reviewer agent)
- Git worktree management for isolated spec work
- Branch completion with spec status updates
- SessionStart hook + skill enforcement
- Pre-completion verification gates (extend canon-verify)

**Leave to external plugins (generic discipline):**
- TDD red-green-refactor cycle
- Systematic debugging methodology
- Generic code style review

**Provide integration points:**
- Canon skills can invoke external TDD/debugging skills when detected
- Canon's spec context is available to any skill via MCP
- Canon-verify can be called as a gate from any workflow

## 2. SessionStart Hook & Skill Enforcement

<!-- canon:system:2 status:todo -->

Canon needs a SessionStart hook that injects skill discovery context, ensuring Canon skills are found and used when relevant. Currently Canon has no hook — users must remember to invoke `/canon:*` commands manually.

### Acceptance Criteria

- [ ] SessionStart hook runs on `startup`, `resume`, `clear`, `compact` events
- [ ] Hook injects a concise skill summary (not full SKILL.md content) listing all Canon skills with trigger conditions
- [ ] Hook detects whether a `docs/specs/` directory exists in the project and adjusts messaging (spec-driven project vs. new project)
- [ ] Hook is defined in the plugin's `hooks.json` following Claude Code's hook format
- [ ] Hook output stays under 2KB to avoid context bloat
- [ ] A `canon-meta` skill (analogous to superpowers' `using-superpowers`) documents when each Canon skill should be invoked
- [ ] The meta-skill includes a rationalization table addressing common reasons to skip spec-driven workflows

## 3. Implementation Planning (Enhanced canon-plan)

<!-- canon:system:3 status:todo -->

The current `canon-plan` skill does high-level spec-to-task extraction. It needs a Phase 6 that produces **file-level implementation plans** — the kind of plan that a subagent can execute without additional context.

### Acceptance Criteria

- [ ] New Phase 6 ("Implementation Plan") added to canon-plan that generates detailed file-level plans
- [ ] Each task in the plan includes: exact file paths, what to change, complete code approach (not placeholders), estimated complexity (S/M/L)
- [ ] Tasks are mapped back to spec section IDs and specific ACs (e.g., "Task 3 → Section 2.1, AC: 'Rate limit: max 3 resets per hour'")
- [ ] Plan is saved to a predictable location: `docs/canon/plans/YYYY-MM-DD-<spec-slug>.md`
- [ ] Plan includes a header with: spec file path, sections covered, dependencies, setup commands
- [ ] Plan enforces no-placeholder policy: no "TBD", "implement later", "add logic here" language
- [ ] Plan includes a self-review checklist the agent must complete before presenting to user

## 4. Git Worktree Management

<!-- canon:system:4 status:todo -->

A `canon-worktree` skill that creates isolated git worktrees for spec-driven work. This is foundational for plan execution — agents need isolation to avoid polluting the main workspace.

### Acceptance Criteria

- [ ] `canon-worktree` skill creates a named worktree branched from the current HEAD
- [ ] Branch naming convention: `canon/<spec-slug>/<section-id>` (e.g., `canon/auth-hardening/2.1`)
- [ ] Worktree directory selection follows priority: project's `.claude/worktrees/` → CLAUDE.md-specified directory → ask user
- [ ] Safety check: selected worktree directory must be git-ignored (verified via `git check-ignore`)
- [ ] Auto-detects and runs project setup commands (npm install, uv sync, cargo build, etc.)
- [ ] Verifies clean baseline by running the project's test suite
- [ ] Reports worktree location and branch name to user upon completion
- [ ] Handles cleanup: skill documents how to remove worktree when work is complete
- [ ] Integrates with `canon-context`: automatically loads relevant spec context in the new worktree

## 5. Plan Execution Engine

<!-- canon:system:5 status:todo -->

A `canon-implement` skill that orchestrates execution of an entire implementation plan. It is the **batch orchestrator** that wraps the `canon-task` inner loop (load spec section → implement ACs → verify → record evidence) with plan-level automation: worktree setup, sequencing, commits, reviewer dispatch, and branch completion.

**Relationship to canon-task:** `canon-task` is interactive and single-section — user picks one task, implements it, done. `canon-implement` runs the same AC-driven inner loop for each task in a plan file, adding automation between tasks. Users doing one-off work use `canon-task`. Users executing a multi-section plan use `canon-implement`.

### Acceptance Criteria

- [ ] `canon-implement` skill loads a plan from `docs/canon/plans/` and executes each task
- [ ] Reuses the `canon-task` inner loop: load spec section → present ACs → implement → verify → record realization evidence
- [ ] Before each task, loads the linked spec section context via MCP or local file read
- [ ] After each task, runs `canon verify --gate` against the relevant ACs to confirm implementation
- [ ] Commits after each task with a message referencing the spec section (e.g., "feat(auth): implement rate limiting [spec:auth-hardening:2.1]")
- [ ] Supports `--sequential` mode: execute tasks one at a time with review checkpoints
- [ ] Supports `--parallel` mode: dispatch independent tasks to subagents using the Agent tool
- [ ] In parallel mode, each subagent receives: the task definition, relevant spec context, and project setup instructions
- [ ] Tracks progress: maintains a checklist in the plan file marking tasks as done
- [ ] On failure, stops execution and presents diagnostic context (error, spec section, what was attempted)
- [ ] Calls `canon-branch` skill when all tasks complete successfully

## 6. Spec-Aware Code Review

<!-- canon:system:6 status:todo -->

A `canon-reviewer` agent that reviews code changes against spec acceptance criteria — not just code style, but whether the implementation actually satisfies what was specified.

### Acceptance Criteria

- [ ] `canon-reviewer` agent defined in the plugin's `agents/` directory with a AGENT.md template
- [ ] Agent receives: git diff of changes, linked spec sections with ACs, and project conventions (CLAUDE.md)
- [ ] Review output categorizes findings as: **Spec Gap** (AC not satisfied), **Spec Conflict** (code contradicts AC), **Quality Issue** (code works but is problematic), **Suggestion** (optional improvement)
- [ ] Each Spec Gap finding references the specific AC text and explains what's missing
- [ ] Agent is automatically dispatched after each task in `canon-implement`
- [ ] Agent can also be invoked standalone via the `canon-review` skill (extend existing skill to dispatch the agent)
- [ ] Review output includes a summary verdict: "All ACs satisfied" / "N gaps found" / "N conflicts found"
- [ ] Agent respects a severity threshold: Spec Gaps and Spec Conflicts must be fixed before proceeding; Quality Issues and Suggestions are advisory

## 7. Branch Completion Workflow

<!-- canon:system:7 status:todo -->

A `canon-branch` skill that handles the end of a development branch: verify, update spec statuses, and merge/PR/cleanup.

### Acceptance Criteria

- [ ] `canon-branch` skill runs verification before any completion action (calls `canon verify`)
- [ ] Updates spec section statuses to `done` for all sections whose ACs are fully realized
- [ ] Presents 4 options to user: merge to base branch, push and create PR, keep branch as-is, discard branch
- [ ] For PR creation: generates PR description from spec sections addressed, ACs completed, and realization evidence
- [ ] PR description includes a "Spec Coverage" section listing which ACs this PR satisfies
- [ ] For merge: performs fast-forward merge when possible, merge commit otherwise
- [ ] Cleans up worktree after merge or discard (removes worktree directory and branch)
- [ ] For "keep as-is": reports branch name and worktree location for later resumption
- [ ] Commits spec status updates before merge/PR so the spec changes are included in the PR

## 8. Pre-Completion Verification Gates

<!-- canon:system:8 status:todo -->

Extend `canon-verify` to act as a gate function — not just a report, but a blocker that prevents completion claims without evidence.

### Acceptance Criteria

- [ ] `canon-verify` adds a `--gate` mode that returns pass/fail (not just a report)
- [ ] Gate mode checks: all linked ACs have realization evidence, tests pass, no Spec Gap findings from reviewer
- [ ] Gate is automatically called by `canon-branch` before allowing merge/PR
- [ ] Gate is automatically called by `canon-implement` after each task before marking it done
- [ ] When gate fails, output includes: which ACs lack evidence, which tests failed, what reviewer flagged
- [ ] Gate mode is the default when called from other Canon skills (report mode remains default for user invocation)
- [ ] Gate results are logged so the user can see the verification trail

## 9. External Skill Integration Points

<!-- canon:system:9 status:todo -->

Canon should play well with external development discipline plugins (superpowers, etc.) rather than duplicating their work. This system defines the integration surface.

### Acceptance Criteria

- [ ] `canon-task` and `canon-implement` detect when TDD skills are available and suggest invoking them before writing implementation code
- [ ] `canon-implement` detects when debugging skills are available and suggests invoking them when a task fails
- [ ] Canon's MCP server exposes spec context that external skills can query (already exists — document the pattern)
- [ ] Canon skills never hard-depend on external plugins — integration is opportunistic (suggest, don't require)
- [ ] Documentation added to Canon plugin README explaining how external skills can leverage spec context via MCP
- [ ] `canon-meta` skill mentions recommended companion plugins and how they integrate

## 10. Rollout Plan

<!-- canon:system:10 status:draft -->

### Phase 1: Foundation (SessionStart + Worktrees)
- System 2: SessionStart hook and canon-meta skill
- System 4: Git worktree management
- These are prerequisites for everything else

### Phase 2: Planning + Execution
- System 3: Enhanced canon-plan with file-level plans
- System 5: canon-implement execution engine (sequential mode first)

### Phase 3: Review + Completion
- System 6: canon-reviewer agent
- System 7: canon-branch completion workflow
- System 8: Verification gates

### Phase 4: Integration + Polish
- System 5 parallel mode (subagent dispatch)
- System 9: External skill integration points
- End-to-end testing of full workflow

## 11. Open Questions

- Should Canon's worktree skill reuse the existing `.claude/worktrees/` convention or establish its own?
- How much of the superpowers "rationalization defense" pattern should Canon adopt? The tone is aggressive — does that fit Canon's brand?
- Should `canon-implement --parallel` use the Agent tool directly or delegate to a `dispatching-parallel-agents`-style skill?
- Should the canon-reviewer agent run in a worktree (isolation) or in the same workspace?
- What's the right commit granularity — per-task or per-AC?
