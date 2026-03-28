---
title: "Slack Product Experience"
status: in_progress
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-03-28
updated: 2026-03-28
tags: [slack, product, notifications, workflows, enterprise]
depends_on:
  - slack-integration
---

# Slack Product Experience

Elevate Canon's Slack integration from a collection of working commands into a cohesive product experience. The existing `slack-integration` spec delivered the infrastructure and read-only surface; this spec focuses on wiring the living system, completing the interactive loop, and adding product-differentiating capabilities.

## 1. Background

<!-- canon:system:1 status:done -->

Canon's Slack integration has broad coverage — slash commands, @mention NL queries, Block Kit dashboards, notification dispatchers, digest builders, and a permission model — but critical pieces aren't connected. The `NotificationDispatcher` is never called. NL queries receive no spec context. All workflow action buttons are stubs. The permission system hardcodes every user to READ.

The result: users must actively pull information via `/canon` commands. Canon's vision doc describes the goal as "pull, not push" — targeted alerts, proactive insights, opt-in digests. The infrastructure exists; the wiring doesn't.

This spec closes the gap in three tracks:
1. **Wire the Living System** — connect existing code so users get proactive value without asking
2. **Complete the Interactive Loop** — make workflow actions real so Slack becomes a control surface
3. **Product Differentiation** — add capabilities that make Canon's Slack presence uniquely valuable

**Related:** [slack-integration](./slack-integration.md), [sre-alerting-monitoring](./sre-alerting-monitoring.md), [enterprise-adoption-enablement](./enterprise-adoption-enablement.md)

## 2. Wire Proactive Notifications

<!-- canon:system:2 status:done -->

The `NotificationDispatcher` class in `src/canon/slack/notifications.py` implements 7 notification types with quiet hours and per-type config, but no event handler calls it. This section wires it into the GitHub event pipeline.

### 2.1 Notification Dispatcher Lifecycle

The `NotificationDispatcher` should be instantiated at app startup (alongside the existing `SlackAlerter`) and stored on `app.state`. It requires a `slack_sdk.WebClient` (from the Bolt app's bot token) and the `SlackConfig` from CANON.yaml.

### 2.2 Spec Status Change Notifications

When a push event modifies a spec file's frontmatter `status` field, call `send_spec_status_change()`. The `on_push.py` handler already detects spec file changes for cache invalidation; extend it to diff the old vs new status.

### 2.3 Coverage Regression Notifications

When a push removes checked acceptance criteria (coverage drops), call `send_coverage_regression()`. This is a critical notification that bypasses quiet hours.

### 2.4 PR Analysis Summary

After the Claude agent analyzes a PR that touches spec files, call `send_pr_analysis_summary()` with the list of affected specs and realized ACs.

### 2.5 Stale Spec Warnings

Add a lightweight cron check (daily) that scans for specs with `status: in_progress` and no commits touching them in N days (configurable, default 14). Call `send_stale_spec_warning()` for each.

### 2.6 Ticket Sync Failure Alerts

When the ticket sync engine encounters an adapter error, call `send_ticket_sync_failure()`. The error message is already sanitized in the dispatcher.

### 2.7 Review Requested Notifications

When `/canon review <spec>` is invoked, also call `send_review_requested()` so the review request appears in the configured channel (not just the invoking channel).

### Acceptance Criteria

- [x] `NotificationDispatcher` instantiated at startup and stored on `app.state`
- [x] `on_push` handler detects spec status changes and calls `send_spec_status_change()`
- [x] `on_push` handler detects coverage regression and calls `send_coverage_regression()`
- [x] `on_pull_request` handler calls `send_pr_analysis_summary()` after agent analysis
- [x] Stale spec cron job runs daily and calls `send_stale_spec_warning()` for specs untouched >N days
- [x] Ticket sync engine calls `send_ticket_sync_failure()` on adapter errors
- [x] `/canon review` triggers `send_review_requested()` to the configured channel
- [x] All notifications respect quiet hours config except critical types
- [x] All notifications respect per-type toggle config from CANON.yaml
- [x] Notification delivery failures are logged but do not fail the parent operation

## 3. Spec-Aware NL Queries

<!-- canon:system:3 status:done -->

The `@canon` mention handler calls Claude with only the raw user question and thread history. It should inject relevant spec context so Claude can actually answer spec-related questions.

### 3.1 Spec Context Injection

Before calling Claude, use `SpecLoader.search(query)` to find up to 5 relevant specs. Include their title, status, coverage stats, and section summaries in the system prompt. This transforms `@canon` from a generic chatbot into a spec-aware assistant.

### 3.2 Deferred Response Pattern

For queries that take >3 seconds (GitHub API + Claude latency), use Slack's `response_url` or `chat.postMessage` to reply asynchronously rather than blocking the acknowledgement. Add a "thinking..." ephemeral message while processing.

### 3.3 Query Intent Detection

Detect common query patterns to optimize response:
- "status of X" → direct `SpecLoader.get_by_slug()` lookup, no Claude call needed
- "what specs are blocked/stale/in progress" → direct `SpecLoader.filter_by_status()`
- Free-form questions → full Claude call with spec context

### Acceptance Criteria

- [x] `handle_mention` loads up to 5 relevant specs via `SpecLoader.search()` and includes them in the Claude system prompt
- [x] Spec context includes title, status, section count, coverage percentage, and section names
- [x] Queries taking >3s use deferred response pattern with "thinking..." indicator
- [x] Direct status queries ("status of X") resolve via `SpecLoader` without a Claude call
- [x] Filter queries ("specs in progress") resolve via `SpecLoader.filter_by_status()` without a Claude call
- [x] NL responses cite specific spec names and sections when answering
- [x] Spec context is truncated to stay within Claude's context budget (max ~8K tokens of spec content)

## 4. Complete Workflow Actions

<!-- canon:system:4 status:done -->

All interactive buttons currently acknowledge but perform no real work. This section makes them functional.

### 4.1 Approve Spec Action

"Approve" should update the spec's `review_status` frontmatter to `approved` via a GitHub commit. Post a threaded confirmation with the commit SHA.

### 4.2 Request Changes Action

The modal submission should post the feedback as a GitHub issue comment (or PR comment if the spec has an open PR). Include the Slack user's name and the feedback text.

### 4.3 Sync Tickets Action

Trigger the ticket sync engine for the specific spec. Show progress in an ephemeral message, then post results (tickets created/updated) in-thread.

### 4.4 Dashboard Refresh Action

Re-fetch specs via `SpecLoader` (with cache invalidation), rebuild dashboard blocks, and use `chat.update` to replace the existing dashboard message.

### 4.5 Slack-to-GitHub Identity Mapping

Wire `resolve_permission()` to actually map Slack users to GitHub logins. Start with a simple `/canon link <github-username>` command that stores the mapping. Fall back to email matching via `users.info` API.

### Acceptance Criteria

- [x] "Approve" button commits `review_status: approved` to the spec file via GitHub API
- [x] "Approve" posts threaded confirmation with commit SHA and author
- [x] "Approve" requires WRITE or ADMIN permission
- [x] "Request Changes" modal submission posts feedback as threaded reply and updates GitHub frontmatter
- [x] "Request Changes" includes the Slack user's display name and feedback text
- [x] "Sync Tickets" triggers the sync engine for the target spec and reports results
- [x] "Sync Tickets" requires ADMIN permission
- [x] "Refresh" invalidates `SpecLoader` cache and updates the dashboard message in-place via `chat.update`
- [x] `/canon link <github-username>` stores Slack→GitHub identity mapping
- [x] `resolve_permission()` uses stored identity mapping to resolve WRITE/ADMIN roles
- [x] Identity mapping falls back to email matching via Slack `users.info` API
- [x] All write actions verify permissions before executing

## 5. Team Digest Delivery

<!-- canon:system:5 status:done -->

`build_digest_blocks()` produces well-formatted per-team weekly digests, but no delivery mechanism exists.

### 5.1 CANON.yaml Team Digest Config

Add `team_digests` support to the `SlackConfig` parser:

```yaml
slack:
  digest:
    team_digests:
      platform:
        channel: "#platform-specs"
        schedule: "monday 09:00"
      backend:
        channel: "#backend-specs"
        schedule: "monday 09:00"
```

### 5.2 Digest Cron Job

Create a K8s CronJob (similar to the existing `weekly_digest` SRE cron) that:
1. Loads CANON.yaml for each configured repo
2. For each `team_digests` entry, builds and sends the digest to the configured channel
3. Includes coverage delta from the previous week

### 5.3 On-Demand Digest

Add `/canon digest [team]` subcommand that generates and posts the digest immediately for the given team (or all teams if omitted).

### Acceptance Criteria

- [x] `SlackDigestConfig` model supports `team_digests` map with channel and schedule per team
- [x] `team_digests` config key is recognized in CANON.yaml validation (no "Unknown key" warning)
- [x] Digest cron job iterates team digest configs and sends to each configured channel
- [x] Digest includes coverage delta from previous week
- [x] `/canon digest [team]` subcommand posts the digest on demand
- [x] Digest delivery failures are logged and do not block other teams' digests

## 6. Home Tab

<!-- canon:system:6 status:done -->

A persistent App Home Tab gives users a personal dashboard without needing to remember slash commands.

### 6.1 Personal Dashboard

When a user opens the Canon app's Home tab, display:
- **My Specs**: specs where the user is `owner` (matched via identity mapping)
- **My Team's Coverage**: aggregate coverage for the user's team
- **Recent Activity**: last 10 notification events relevant to the user
- **Quick Actions**: buttons for common operations (list specs, view dashboard, link GitHub account)

### 6.2 Onboarding State

If the user hasn't linked their GitHub identity, the Home Tab should show an onboarding prompt with a "Link GitHub Account" button instead of the personalized dashboard.

### Acceptance Criteria

- [x] `app_home_opened` event handler registered in Bolt app
- [x] Home Tab shows "My Specs" filtered by owner identity mapping
- [x] Home Tab shows team coverage stats
- [x] Home Tab shows recent activity (last 10 notifications)
- [x] Home Tab shows onboarding prompt when GitHub identity is not linked
- [x] Home Tab includes "Link GitHub Account" button that triggers identity mapping flow
- [x] Home Tab refreshes on each open (no stale cache)

## 7. Spec Creation from Slack

<!-- canon:system:7 status:done -->

Enable lightweight spec creation without leaving Slack.

### 7.1 `/canon new` Command

`/canon new <title>` opens a modal with fields:
- **Title** (pre-filled from command text)
- **Type** (spec, proposal, design, adr — dropdown)
- **Team** (dropdown populated from known teams)
- **Background** (textarea — brief motivation)

On submit, create the spec file in the repo via GitHub API using the standard template, and post a confirmation with the GitHub URL.

### Acceptance Criteria

- [x] `/canon new <title>` opens a creation modal
- [x] Modal includes title, type, team, and background fields
- [x] Submission creates spec file in `docs/specs/` via GitHub API commit
- [x] Created spec uses the standard template with frontmatter
- [x] Confirmation message includes GitHub URL to the new spec
- [x] Spec creation requires WRITE or ADMIN permission

## 8. Smart Notification Preferences

<!-- canon:system:8 status:done -->

Reduce notification fatigue by letting users personalize what they see.

### 8.1 Per-User Mute

`/canon mute <spec-slug>` mutes notifications for a specific spec. `/canon unmute <spec-slug>` reverses it. Mute state stored per Slack user ID.

### 8.2 Follow by Interest

Track which specs a user queries via `/canon status` or `@canon` mentions. After N queries about the same spec (default 3), offer to auto-follow it for proactive notifications.

### 8.3 Channel-Level Overrides

Allow CANON.yaml to route specific notification types to specific channels:

```yaml
slack:
  notifications:
    coverage_regression:
      enabled: true
      channel: "#eng-alerts"
    spec_status_change:
      enabled: true
      channel: "#specs"
```

### Acceptance Criteria

- [x] `/canon mute <spec>` suppresses notifications for that spec for the invoking user
- [x] `/canon unmute <spec>` re-enables notifications
- [x] Mute state persists across pod restarts (stored in DB or config)
- [x] System tracks user query patterns and suggests following frequently-queried specs
- [x] Per-notification-type channel routing supported in CANON.yaml
- [x] Channel-level overrides validated in config parser

## 9. Rollout Plan

<!-- canon:system:9 status:todo -->

### Phase 1: Wire the Living System (Track 1)

Ship sections 2, 3, and 5. This delivers the highest-impact change: users start receiving proactive notifications and getting spec-aware answers from `@canon` without any new UI.

**Success criteria:** At least 1 team receives weekly digests and proactive spec change notifications for 2 weeks.

### Phase 2: Interactive Loop (Track 2)

Ship section 4. This makes Slack a real workflow surface — approve specs, request changes, sync tickets, all from Slack.

**Success criteria:** At least 5 spec approvals or change requests completed entirely within Slack.

### Phase 3: Differentiation (Track 3)

Ship sections 6, 7, and 8. These are product-differentiating features that make Canon's Slack presence uniquely valuable vs competitors.

**Success criteria:** Home Tab DAU > 30% of workspace members; at least 3 specs created from Slack.

### Acceptance Criteria

- [ ] Phase 1 shipped and validated with at least 1 team for 2 weeks
- [ ] Phase 2 shipped and 5+ workflow actions completed in Slack
- [ ] Phase 3 shipped and Home Tab adoption measured
