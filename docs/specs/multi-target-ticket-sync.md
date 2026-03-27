---
title: "Close the SDLC Loop: Realization Auto-Commit + Multi-Target Sync"
status: draft
owner: nick
team: canon
ticket_project: null
created: 2026-03-25
updated: 2026-03-25
tags: [sync, integrations, dogfood, jira, linear, github-issues, realization, sdlc]
---

# Close the SDLC Loop: Realization Auto-Commit + Multi-Target Sync

Canon's SDLC loop is broken: when PRs merge, realization checks detect spec progress but create a separate doc-update PR that nobody merges. Specs stall, forward sync never fires, tickets never update. The entire downstream chain is dead because of one manual gate.

This spec fixes the foundation first (close the realization loop, fix config, make failures loud), then builds multi-target sync on top of a working pipeline.

## 1. Background

### The Broken Loop

```
PR merges → realization check finds evidence → doc-update PR created → ❌ nobody merges it
→ specs never update on main → forward sync never fires → tickets never update
```

Canon already has the intelligence to detect what code implements what spec sections. The problem is purely mechanical: spec updates are gated behind a second PR review that adds no value (the analysis was already visible on the original PR).

### The Desired Loop (Model C: Code-Driven)

```
PR merges → realization check finds evidence → specs auto-update on main
→ forward sync fires → tickets update across all configured systems
→ drift detection catches any divergence
```

Nobody manually updates spec status or ticket status. Code is the source of truth. Canon infers the rest.

### Why Multi-Target Matters

Once the loop works, we dogfood all three adapters (Jira, Linear, GitHub Issues) by routing different workstreams to different primary systems with shadow sync to the others. Each system has a genuine operational purpose — not a test environment, but real work.

## 2. Close the Realization Loop

<!-- canon:section:2 status:in_progress -->

Eliminate the manual gate between realization detection and spec updates.

### Current Behavior

On PR merge, `on_pull_request_merged.py` extracts realization data from the bot comment, checks off ACs, advances section status, then creates a **separate PR** on `canon/auto-updates` branch. This PR requires manual review and merge.

### New Behavior

On PR merge, commit spec updates **directly to the default branch** instead of creating a separate PR. The realization evidence was already reviewed on the original PR — the bot comment shows exactly what was detected and why.

### Safety Rails

- Only auto-commit when realization confidence is `realized` (not `partially_realized` or `conflicting`)
- Auto-advance section status only when **all ACs** in a section are checked (existing logic, no change)
- Commit message references the original PR for traceability: `chore(canon): update specs from PR #123`
- If commit fails (e.g., conflict), fall back to creating a PR (existing behavior) and log a warning

### Acceptance Criteria

- [ ] Merge handler commits spec updates directly to main instead of creating a doc-update PR
- [ ] `realized` and `partially_realized` ACs are checked off automatically; `conflicting` ACs are flagged in a PR comment but not checked off
- [ ] Auto-advance from `todo` → `in_progress` → `done` works when all ACs in a section are complete
- [ ] Commit message includes reference to source PR
- [ ] Fallback to PR creation on conflict, with logged warning
- [ ] Existing `canon/auto-updates` PR behavior removed (no orphaned PRs)

## 3. Fix CANON.yaml and Forward Sync

<!-- canon:section:3 status:in_progress -->

The current CANON.yaml is misconfigured — it declares `system: github` but uses Jira-style status values, which means forward sync likely silently fails or maps incorrectly.

### Current Config (Broken)

```yaml
ticket_systems:
  primary:
    system: github
    project: "canonhq/canon-private"
    status_map:
      forward:
        draft: "Backlog"        # ← Jira-style, not GitHub
        todo: "To Do"
        in_progress: "In Progress"
        done: "Done"
```

### Fixed Config

Fix the config to match whichever system is actually primary. Since we're moving to multi-target routing (Section 5), this becomes the GitHub-specific config with correct status values.

### Acceptance Criteria

- [ ] CANON.yaml `ticket_systems` config uses correct status values for each configured system
- [ ] Forward sync successfully creates/updates tickets after spec changes are committed to main
- [ ] Verify end-to-end: merge a PR → spec updates → ticket created/updated (manual test)
- [ ] `agents.realization_check` config flag is actually wired into handler code (currently parsed but never consumed)

## 4. Make Failures Loud

<!-- canon:section:4 status:in_progress -->

The current system has multiple silent failure paths. When sync skips, adapter resolution fails, or the realization check errors, nothing alerts anyone.

### Silent Failures Identified

| Failure | Current Behavior | Fix |
|---------|-----------------|-----|
| Claude analysis fails/times out on PR | No bot comment posted, merge handler finds nothing | Log error, post "analysis failed" comment on PR |
| No bot comment found on merge | Handler returns early silently | Log warning with PR URL |
| Adapter resolution fails (bad config) | `continue` to next file | Log error with config details |
| Forward sync create_ticket fails | Error appended to SyncResult, not surfaced | Post summary to alerting channel |
| Reverse sync cron errors | Logged but not alerted | Add structured error events to PostHog/alerting |

### Acceptance Criteria

- [ ] Failed realization checks post a visible comment on the PR ("Canon analysis failed — spec status may not update automatically")
- [ ] Sync errors are tracked as PostHog events (existing analytics infrastructure) with enough context to diagnose
- [ ] Reverse sync cron emits a summary event after each run: files processed, statuses changed, errors encountered
- [ ] Adapter resolution failures log the config that was attempted, not just "adapter not found"

## 5. Multi-Target Routing with Shadow Sync

<!-- canon:section:5 status:in_progress -->

Once the single-system loop is working (Sections 2-4), add multi-target routing to dogfood all three adapters through real work.

### Operational Routing Model

| Workstream | Primary System | Why You'll Look At It |
|-----------|---------------|----------------------|
| Product development (features, bugs) | Linear | Daily driver for eng work |
| Public-facing work (plugin SDK, docs, community) | GitHub Issues | Community engagement, open-source |
| Enterprise/customer simulation, infra ops | Jira | Simulates customer Jira usage, ops visibility |

### Shadow Sync

Each spec section syncs to one primary target (determined by routing rules) and zero or more shadow targets. Shadows are read-only projections — reverse sync reads from primary only.

```yaml
ticket_mapping:
  routing_rules:
    - match:
        tags: [product, feature, bug]
      target: linear
      shadow_targets: [jira, github]
    - match:
        tags: [community, docs, plugin-sdk]
      target: github
      shadow_targets: [linear]
    - match:
        tags: [enterprise, infra, ops]
      target: jira
      shadow_targets: [linear, github]
    - match:
        default: true
      target: linear
      shadow_targets: []
```

### Acceptance Criteria

- [ ] Free Jira Cloud instance provisioned at a Canon-owned Atlassian site
- [ ] Linear workspace configured with Canon project for product work
- [ ] `RoutingRule` model supports `shadow_targets` field
- [ ] Forward sync creates tickets in primary + all shadow targets
- [ ] Spec writer records ticket IDs for all targets (primary and shadow)
- [ ] Reverse sync reads status from primary target only
- [ ] Shadow tickets labeled `canon:shadow`
- [ ] Adapter factory supports instantiating multiple adapters simultaneously
- [ ] Existing single-target configs continue to work (backward compatible)
- [ ] CANON.yaml routing rules configured for canon-private per the routing model above

## 6. Drift Detection

<!-- canon:section:6 status:in_progress -->

With multi-target sync running, detect when systems diverge.

### What Constitutes Drift

- Primary says "done" but a shadow says "in_progress"
- Any shadow is more than one status transition behind primary
- A shadow ticket was manually modified outside Canon

### Reporting

- `canon audit` includes a cross-system drift report
- PR review agent flags specs with active drift when reviewing related code
- Drift metrics logged alongside reverse sync cron

### Design Decisions (from discussion)

- **Shadows are read-only** — Canon manages them, manual edits are drift
- **Report only, no auto-heal** — during dogfooding, drift signals are valuable; auto-heal would mask sync bugs
- **Drift checks run inside existing reverse sync cron** — no separate schedule

### Acceptance Criteria

- [ ] `canon audit` compares ticket status across all targets for multi-synced specs
- [ ] Drift report shows: spec section, primary status, shadow statuses, divergence type
- [ ] PR review agent flags specs with active drift when reviewing related code
- [ ] Cron job logs drift metrics alongside reverse sync
- [ ] Drift is informational (warning), not blocking

## 7. Rollout Plan

<!-- canon:section:7 status:draft -->

Sequenced to fix foundations before adding complexity.

### Phase 1: Close the Loop (prerequisite for everything else)
1. Change merge handler to commit spec updates directly to main
2. Fix CANON.yaml config for the current primary system
3. Add error logging/alerting for silent failure paths
4. Verify end-to-end: PR merge → spec auto-updates → ticket created

### Phase 2: Provision Environments
1. Provision Jira Cloud free instance
2. Configure Linear workspace with Canon project
3. Add all credentials to Doppler
4. Verify each adapter works independently with real credentials

### Phase 3: Multi-Target Sync
1. Add `shadow_targets` to routing model
2. Extend forward sync to iterate over primary + shadows
3. Extend spec writer to track multiple ticket IDs
4. Configure CANON.yaml routing rules for canon-private
5. Run first full sync across all three systems

### Phase 4: Drift Detection
1. Implement cross-system status comparison in `canon audit`
2. Wire drift warnings into PR review agent
3. Add drift metrics to reverse sync cron

### Phase 5: Steady State
- All workstreams routed through their primary systems
- Reverse sync cron running, drift reported
- Iterate on routing rules based on what feels natural

## 8. Decisions

Resolved during planning (2026-03-25):

1. **Confidence threshold for auto-commit**: Auto-check individual ACs at both `realized` and `partially_realized` confidence. Auto-advance section status when all ACs are complete. `conflicting` ACs are flagged in a PR comment but never auto-committed.

2. **PR author notification**: Yes. Post a follow-up comment on the merged PR summarizing spec updates (which ACs checked, which sections advanced). Builds trust in automation and creates audit trail. Can be disabled later once stable.

3. **Jira free tier API limits**: 100 req/min is sufficient for Canon's volume (~20-30 spec sections). Non-issue.

4. **Primary system for Phase 1**: GitHub Issues at repo level (`canonhq/canon-private`). Longer-term, the GitHub adapter should evolve toward **GitHub Projects V2** as the organizational unit (cross-repo boards, custom fields, workflows) — this is a separate future spec as it requires moving from the REST Issues API to the GraphQL Projects V2 API.

5. **Shadow tickets**: Read-only. Canon manages them; manual edits are flagged as drift.

6. **Drift detection**: Report-only, no auto-heal. Drift signals are valuable during dogfooding to surface sync bugs.

7. **Drift check cadence**: Piggyback on existing reverse sync cron. No separate schedule.

## 9. Open Questions

- GitHub Projects V2 migration: scope and timeline TBD, separate spec needed
