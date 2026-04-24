---
title: "Superpowers Parity: Development Execution Workflow"
status: in_progress
owner: nick
team: canon-core
ticket_project: null
created: 2026-03-31
updated: 2026-04-11
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

<!-- canon:system:2 status:in_progress -->

<!-- canon:ticket:github:590 -->
Canon needs a SessionStart hook that injects skill discovery context, ensuring Canon skills are found and used when relevant. Currently Canon has no hook — users must remember to invoke `/canon:*` commands manually.

### Acceptance Criteria

- [x] SessionStart hook runs on `startup`, `resume`, `clear`, `compact` events
<!-- canon:realized-in:audit file:plugin/hooks/hooks.json:4-15 -->
<!-- note: matcher is "*" which covers all events; explicit event list not required by Claude Code hook API -->
- [x] Hook injects a concise skill summary (not full SKILL.md content) listing all Canon skills with trigger conditions
<!-- canon:realized-in:audit file:plugin/hooks/session-start.sh:60-85 -->
- [x] Hook detects whether a `docs/specs/` directory exists in the project and adjusts messaging (spec-driven project vs. new project)
<!-- canon:realized-in:audit file:plugin/hooks/session-start.sh:35-38,60-85 -->
- [x] Hook is defined in the plugin's `hooks.json` following Claude Code's hook format
<!-- canon:realized-in:audit file:plugin/hooks/hooks.json:1-53 -->
- [ ] Hook output stays under 2KB to avoid context bloat
<!-- canon:gap: current session-start.sh emits ~1.1KB of skill list; verify with `wc -c` on typical output, document in test -->
- [x] A `canon-meta` skill (analogous to superpowers' `using-superpowers`) documents when each Canon skill should be invoked
<!-- canon:realized-in:audit file:plugin/skills/canon-meta/SKILL.md:13-44 -->
- [x] The meta-skill includes a rationalization table addressing common reasons to skip spec-driven workflows
<!-- canon:realized-in:audit file:plugin/skills/canon-meta/SKILL.md:46-58 -->
- [ ] SessionStart hook injects canon-meta skill rules inline (not just the skill list) so the rationalization defense activates without a separate skill invocation
<!-- canon:gap: current hook lists skills but does not inline canon-meta rationalization table; tracked in plugin-product-polish spec -->

## 3. Implementation Planning (Enhanced canon-plan)

<!-- canon:system:3 status:done -->

The current `canon-plan` skill does high-level spec-to-task extraction. It needs a Phase 6 that produces **file-level implementation plans** — the kind of plan that a subagent can execute without additional context.

### Acceptance Criteria

- [x] New Phase 6 ("Implementation Plan") added to canon-plan that generates detailed file-level plans
<!-- canon:realized-in:audit file:plugin/skills/canon-plan/SKILL.md:88-135 -->
- [x] Each task in the plan includes: exact file paths, what to change, complete code approach (not placeholders), estimated complexity (S/M/L)
<!-- canon:realized-in:audit file:plugin/skills/canon-plan/SKILL.md:109-116 -->
- [x] Tasks are mapped back to spec section IDs and specific ACs (e.g., "Task 3 → Section 2.1, AC: 'Rate limit: max 3 resets per hour'")
<!-- canon:realized-in:audit file:plugin/skills/canon-plan/SKILL.md:111 -->
- [x] Plan is saved to a predictable location: `docs/canon/plans/YYYY-MM-DD-<spec-slug>.md`
<!-- canon:realized-in:audit file:plugin/skills/canon-plan/SKILL.md:94-96 -->
- [x] Plan includes a header with: spec file path, sections covered, dependencies, setup commands
<!-- canon:realized-in:audit file:plugin/skills/canon-plan/SKILL.md:98-107 -->
- [x] Plan enforces no-placeholder policy: no "TBD", "implement later", "add logic here" language
<!-- canon:realized-in:audit file:plugin/skills/canon-plan/SKILL.md:120 -->
- [x] Plan includes a self-review checklist the agent must complete before presenting to user
<!-- canon:realized-in:audit file:plugin/skills/canon-plan/SKILL.md:124-131 -->

## 4. Git Worktree Management

<!-- canon:system:4 status:done -->

A `canon-worktree` skill that creates isolated git worktrees for spec-driven work. This is foundational for plan execution — agents need isolation to avoid polluting the main workspace.

### Acceptance Criteria

- [x] `canon-worktree` skill creates a named worktree branched from the current HEAD
<!-- canon:realized-in:audit file:plugin/skills/canon-worktree/SKILL.md:74-88 -->
- [x] Branch naming convention: `canon/<spec-slug>/<section-id>` (e.g., `canon/auth-hardening/2.1`)
<!-- canon:realized-in:audit file:plugin/skills/canon-worktree/SKILL.md:76-87 -->
- [x] Worktree directory selection follows priority: project's `.claude/worktrees/` → CLAUDE.md-specified directory → ask user
<!-- canon:realized-in:audit file:plugin/skills/canon-worktree/SKILL.md:21-35 -->
- [x] Safety check: selected worktree directory must be git-ignored (verified via `git check-ignore`)
<!-- canon:realized-in:audit file:plugin/skills/canon-worktree/SKILL.md:37-51 -->
- [x] Auto-detects and runs project setup commands (npm install, uv sync, cargo build, etc.)
<!-- canon:realized-in:audit file:plugin/skills/canon-worktree/SKILL.md:90-111 -->
- [x] Verifies clean baseline by running the project's test suite
<!-- canon:realized-in:audit file:plugin/skills/canon-worktree/SKILL.md:113-129 -->
- [x] Reports worktree location and branch name to user upon completion
<!-- canon:realized-in:audit file:plugin/skills/canon-worktree/SKILL.md:140-150 -->
- [x] Handles cleanup: skill documents how to remove worktree when work is complete
<!-- canon:realized-in:audit file:plugin/skills/canon-worktree/SKILL.md:152-164 -->
- [x] Integrates with `canon-context`: automatically loads relevant spec context in the new worktree
<!-- canon:realized-in:audit file:plugin/skills/canon-worktree/SKILL.md:131-138 -->

## 5. Plan Execution Engine

<!-- canon:system:5 status:in_progress -->

<!-- canon:ticket:github:591 -->
A `canon-implement` skill that orchestrates execution of an entire implementation plan. It is the **batch orchestrator** that wraps the `canon-task` inner loop (load spec section → implement ACs → verify → record evidence) with plan-level automation: worktree setup, sequencing, commits, reviewer dispatch, and branch completion.

**Relationship to canon-task:** `canon-task` is interactive and single-section — user picks one task, implements it, done. `canon-implement` runs the same AC-driven inner loop for each task in a plan file, adding automation between tasks. Users doing one-off work use `canon-task`. Users executing a multi-section plan use `canon-implement`.

### Acceptance Criteria

- [x] `canon-implement` skill loads a plan from `docs/canon/plans/` and executes each task
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:37-64 -->
- [x] Reuses the `canon-task` inner loop: load spec section → present ACs → implement → verify → record realization evidence
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:76-118 -->
- [x] Before each task, loads the linked spec section context via MCP or local file read
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:84-92 -->
- [x] After each task, runs `canon verify --gate` against the relevant ACs to confirm implementation
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:120-134 -->
- [x] Commits after each task with a message referencing the spec section (e.g., "feat(auth): implement rate limiting [spec:auth-hardening:2.1]")
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:136-140 -->
- [x] Supports `--sequential` mode: execute tasks one at a time with review checkpoints
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:76-146 -->
- [x] Supports `--parallel` mode: dispatch independent tasks to subagents using the Agent tool
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:148-162 -->
- [x] In parallel mode, each subagent receives: the task definition, relevant spec context, and project setup instructions
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:153-156 -->
- [x] Tracks progress: maintains a checklist in the plan file marking tasks as done
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:142-146,187-191 -->
- [x] On failure, stops execution and presents diagnostic context (error, spec section, what was attempted)
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:126-134,171-185 -->
- [x] Calls `canon-branch` skill when all tasks complete successfully
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:164-170 -->
- [ ] Plan execution engine has an end-to-end integration test exercising at least sequential mode against a toy spec
<!-- canon:gap: documented behavior only; no automated test covers the orchestration. Added in plugin-product-polish follow-up. -->

## 6. Spec-Aware Code Review

<!-- canon:system:6 status:in_progress -->

<!-- canon:ticket:github:592 -->
A `canon-reviewer` agent that reviews code changes against spec acceptance criteria — not just code style, but whether the implementation actually satisfies what was specified.

### Acceptance Criteria

- [x] `canon-reviewer` agent defined in the plugin's `agents/` directory with a AGENT.md template
<!-- canon:realized-in:audit file:plugin/agents/canon-reviewer/AGENT.md:1-98 -->
- [x] Agent receives: git diff of changes, linked spec sections with ACs, and project conventions (CLAUDE.md)
<!-- canon:realized-in:audit file:plugin/agents/canon-reviewer/AGENT.md:26-36 -->
- [x] Review output categorizes findings as: **Spec Gap** (AC not satisfied), **Spec Conflict** (code contradicts AC), **Quality Issue** (code works but is problematic), **Suggestion** (optional improvement)
<!-- canon:realized-in:audit file:plugin/agents/canon-reviewer/AGENT.md:47-52,90-93 -->
- [x] Each Spec Gap finding references the specific AC text and explains what's missing
<!-- canon:realized-in:audit file:plugin/agents/canon-reviewer/AGENT.md:65-72 -->
- [ ] Agent is automatically dispatched after each task in `canon-implement`
<!-- canon:gap: canon-implement mentions reviewer conceptually but does not explicitly invoke the canon-reviewer agent via the Agent tool after each task. Tracked in plugin-product-polish. -->
- [x] Agent can also be invoked standalone via the `canon-review` skill (extend existing skill to dispatch the agent)
<!-- canon:realized-in:audit file:plugin/skills/canon-review/SKILL.md -->
<!-- note: canon-review skill exists; explicit canon-reviewer agent dispatch path should be documented in that skill -->
- [x] Review output includes a summary verdict: "All ACs satisfied" / "N gaps found" / "N conflicts found"
<!-- canon:realized-in:audit file:plugin/agents/canon-reviewer/AGENT.md:82-89 -->
- [x] Agent respects a severity threshold: Spec Gaps and Spec Conflicts must be fixed before proceeding; Quality Issues and Suggestions are advisory
<!-- canon:realized-in:audit file:plugin/agents/canon-reviewer/AGENT.md:90-98 -->

## 7. Branch Completion Workflow

<!-- canon:system:7 status:done -->

A `canon-branch` skill that handles the end of a development branch: verify, update spec statuses, and merge/PR/cleanup.

### Acceptance Criteria

- [x] `canon-branch` skill runs verification before any completion action (calls `canon verify`)
<!-- canon:realized-in:audit file:plugin/skills/canon-branch/SKILL.md:38-58 -->
- [x] Updates spec section statuses to `done` for all sections whose ACs are fully realized
<!-- canon:realized-in:audit file:plugin/skills/canon-branch/SKILL.md:60-81 -->
- [x] Presents 4 options to user: merge to base branch, push and create PR, keep branch as-is, discard branch
<!-- canon:realized-in:audit file:plugin/skills/canon-branch/SKILL.md:84-93 -->
- [x] For PR creation: generates PR description from spec sections addressed, ACs completed, and realization evidence
<!-- canon:realized-in:audit file:plugin/skills/canon-branch/SKILL.md:115-138 -->
- [x] PR description includes a "Spec Coverage" section listing which ACs this PR satisfies
<!-- canon:realized-in:audit file:plugin/skills/canon-branch/SKILL.md:120-129 -->
- [x] For merge: performs fast-forward merge when possible, merge commit otherwise
<!-- canon:realized-in:audit file:plugin/skills/canon-branch/SKILL.md:97-102 -->
- [x] Cleans up worktree after merge or discard (removes worktree directory and branch)
<!-- canon:realized-in:audit file:plugin/skills/canon-branch/SKILL.md:104-107,159-163 -->
- [x] For "keep as-is": reports branch name and worktree location for later resumption
<!-- canon:realized-in:audit file:plugin/skills/canon-branch/SKILL.md:141-150 -->
- [x] Commits spec status updates before merge/PR so the spec changes are included in the PR
<!-- canon:realized-in:audit file:plugin/skills/canon-branch/SKILL.md:77-81 -->

## 8. Pre-Completion Verification Gates

<!-- canon:system:8 status:in_progress -->

<!-- canon:ticket:github:593 -->
Extend `canon-verify` to act as a gate function — not just a report, but a blocker that prevents completion claims without evidence.

### Acceptance Criteria

- [x] `canon-verify` adds a `--gate` mode that returns pass/fail (not just a report)
<!-- canon:realized-in:audit file:plugin/skills/canon-verify/SKILL.md:80-104 -->
- [x] Gate mode checks: all linked ACs have realization evidence, tests pass, no Spec Gap findings from reviewer
<!-- canon:realized-in:audit file:plugin/skills/canon-verify/SKILL.md:84-90 -->
<!-- note: skill documents the three checks; "no Spec Gap findings from reviewer" relies on canon-reviewer dispatch which is gap'd in §6 -->
- [x] Gate is automatically called by `canon-branch` before allowing merge/PR
<!-- canon:realized-in:audit file:plugin/skills/canon-branch/SKILL.md:38-58 file:plugin/skills/canon-verify/SKILL.md:106-112 -->
- [x] Gate is automatically called by `canon-implement` after each task before marking it done
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:120-134 -->
- [x] When gate fails, output includes: which ACs lack evidence, which tests failed, what reviewer flagged
<!-- canon:realized-in:audit file:plugin/skills/canon-verify/SKILL.md:99-104 -->
- [x] Gate mode is the default when called from other Canon skills (report mode remains default for user invocation)
<!-- canon:realized-in:audit file:plugin/skills/canon-verify/SKILL.md:106-112 -->
- [ ] Gate results are logged so the user can see the verification trail
<!-- canon:gap: skill emits gate output to stdout but does not persist a verification trail. Could write to .canon/verify-log.jsonl. Tracked in plugin-evidence-pipeline. -->

## 9. External Skill Integration Points

<!-- canon:system:9 status:in_progress -->

<!-- canon:ticket:github:594 -->
Canon should play well with external development discipline plugins (superpowers, etc.) rather than duplicating their work. This system defines the integration surface.

### Acceptance Criteria

- [x] `canon-task` and `canon-implement` detect when TDD skills are available and suggest invoking them before writing implementation code
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:93-97 -->
- [ ] `canon-implement` detects when debugging skills are available and suggests invoking them when a task fails
<!-- canon:gap: failure path in canon-implement (lines 126-134) presents diagnostic context but does not check for or suggest debugging skills. Tracked in plugin-product-polish. -->
- [x] Canon's MCP server exposes spec context that external skills can query (already exists — document the pattern)
<!-- canon:realized-in:audit file:plugin/README.md:117-125 file:plugin/skills/canon-meta/SKILL.md:73-80 -->
- [x] Canon skills never hard-depend on external plugins — integration is opportunistic (suggest, don't require)
<!-- canon:realized-in:audit file:plugin/skills/canon-implement/SKILL.md:93-97 file:plugin/skills/canon-meta/SKILL.md:60-71 -->
- [x] Documentation added to Canon plugin README explaining how external skills can leverage spec context via MCP
<!-- canon:realized-in:audit file:plugin/README.md:117-129 -->
- [x] `canon-meta` skill mentions recommended companion plugins and how they integrate
<!-- canon:realized-in:audit file:plugin/skills/canon-meta/SKILL.md:60-71 -->

## 10. Rollout Plan

<!-- canon:system:10 status:todo -->

<!-- canon:ticket:github:587 -->
### Phase 1: Foundation (SessionStart + Worktrees) — DONE
- ✅ System 2: SessionStart hook and canon-meta skill (hook lists skills; meta-skill inline injection still gap'd)
- ✅ System 4: Git worktree management

### Phase 2: Planning + Execution — DONE
- ✅ System 3: Enhanced canon-plan with file-level plans
- ✅ System 5: canon-implement execution engine (sequential and parallel modes)

### Phase 3: Review + Completion — MOSTLY DONE
- ✅ System 6: canon-reviewer agent (auto-dispatch from canon-implement still gap'd)
- ✅ System 7: canon-branch completion workflow
- ✅ System 8: Verification gates (verification trail logging gap'd)

### Phase 4: Integration + Polish — IN PROGRESS
- ✅ System 5 parallel mode (subagent dispatch) — landed alongside sequential
- 🟡 System 9: External skill integration points (TDD suggest landed; debug-skill suggest still gap'd)
- 🔴 End-to-end testing of full workflow (no integration test exists)

### Remaining Gaps (rolled into follow-up specs)
- SessionStart inline meta-skill injection → `plugin-product-polish.md`
- canon-reviewer auto-dispatch from canon-implement → `plugin-product-polish.md`
- Verification trail logging → `plugin-evidence-pipeline.md`
- Debugging-skill suggest on task failure → `plugin-product-polish.md`
- End-to-end integration test → `plugin-product-polish.md`

## 11. Open Questions

- Should Canon's worktree skill reuse the existing `.claude/worktrees/` convention or establish its own?
- How much of the superpowers "rationalization defense" pattern should Canon adopt? The tone is aggressive — does that fit Canon's brand?
- Should `canon-implement --parallel` use the Agent tool directly or delegate to a `dispatching-parallel-agents`-style skill?
- Should the canon-reviewer agent run in a worktree (isolation) or in the same workspace?
- What's the right commit granularity — per-task or per-AC?
