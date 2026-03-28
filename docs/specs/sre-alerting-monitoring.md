---
title: "SRE Alerting & Monitoring"
status: done
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-03-20
updated: 2026-03-20
tags: [sre, alerting, monitoring, posthog, slack, observability]
---

# SRE Alerting & Monitoring

Shift Canon's monitoring from reactive (manually checking PostHog logs) to proactive — automated alerts, an SRE dashboard, enhanced instrumentation, and error-to-issue triage.

## 1. Background

<!-- canon:system:1 status:done -->

Canon has PostHog exception capture and OTel log export (WARNING+) in production, but no alerting pipeline. Errors are only discovered when someone opens PostHog and looks. There's no SRE dashboard, no Slack notifications, and no automated triage. The existing `observability.md` spec (done) covered exception capture; the `slack-integration.md` spec (draft) covers a full Slack query bot. This spec fills the gap between them: the proactive alerting and monitoring layer.

**Current state:**
- PostHog Python SDK with `enable_exception_autocapture=True`
- Global FastAPI exception handler → PostHog
- OTel log export (WARNING+) to PostHog
- `/healthz` and `/readyz` health probes
- No alerting, no dashboards, no Slack notifications
- No request latency or cron job metrics

**Related specs:**
- `observability.md` (done) — exception capture foundation
- `slack-integration.md` (draft) — full Slack bot (separate scope)

## 2. PostHog Alert Actions

<!-- canon:system:2 status:done -->

Configure PostHog's built-in alerting to detect error spikes, new error patterns, and performance anomalies. These alerts feed into Slack (Section 3) and optionally GitHub Issues (Section 6).

### 2.1 Alert Definitions

| Alert | Trigger | Severity |
|-------|---------|----------|
| Exception spike | Exception count > 10 in 5 min window | High |
| New error pattern | First-seen exception fingerprint | Medium |
| Webhook processing slow | p95 webhook duration > 30s over 15 min | Medium |
| Cron job failure | Cron execution event with `success=false` | High |
| Error rate elevated | Error rate > 5% of total requests over 15 min | High |
| Health check failure | Readiness probe returns unhealthy | Critical |

### 2.2 Alert Configuration

Alerts are configured via PostHog Actions + Subscriptions. Configuration should be reproducible (documented or scripted via PostHog API).

### Acceptance Criteria

- [x] Exception spike alert configured in PostHog and firing correctly
- [x] New error pattern alert triggers on first-seen exception fingerprints
- [x] Webhook latency alert triggers when p95 exceeds threshold
- [x] Cron job failure alert triggers on failed cron executions
- [x] Error rate alert triggers when error percentage exceeds threshold
- [x] All alert thresholds are documented and tunable
- [x] Alert definitions are reproducible (API script or documented steps)

## 3. Slack Webhook Notifications

<!-- canon:system:3 status:done -->

Deliver PostHog alerts to a `#canon-alerts` Slack channel via incoming webhook. This is the lightweight alerting path — the full Slack bot with `/canon` commands is a separate spec.

### 3.1 Webhook Setup

- Create Slack incoming webhook for `#canon-alerts` channel
- Store webhook URL in Doppler (`canon/prd`) as `SLACK_ALERTS_WEBHOOK_URL`
- Add to Helm chart as a secret reference

### 3.2 Alert Message Format

Slack messages should include:
- Alert severity indicator (emoji or color)
- Error summary (exception type, message, count)
- Affected endpoint/service
- Time window
- Direct link to PostHog error group or dashboard
- Link to relevant Canon spec (if determinable)

### 3.3 Delivery Paths

Two complementary delivery paths:

1. **PostHog → Slack**: PostHog Action subscriptions that send directly to Slack webhook (for alerts PostHog can evaluate natively)
2. **Canon → Slack**: A lightweight `src/canon/alerts/slack.py` module that posts to the webhook from application code (for custom alerts like cron failures, health degradation)

### Acceptance Criteria

- [x] Slack incoming webhook configured for `#canon-alerts` channel
- [x] Webhook URL stored in Doppler and available as env var
- [x] Helm chart updated with Slack webhook secret
- [x] PostHog alert actions deliver formatted messages to Slack
- [x] Application-side alert module (`alerts/slack.py`) can post custom alerts
- [x] Alert messages include severity, summary, context, and PostHog link
- [x] Alert delivery failures are logged (not silently swallowed)

## 4. SRE Dashboard in PostHog

<!-- canon:system:4 status:done -->

Create a PostHog dashboard providing at-a-glance service reliability visibility.

### 4.1 Dashboard Panels

| Panel | Metric | Visualization |
|-------|--------|---------------|
| Error rate | Exceptions per minute, % of total requests | Line chart |
| Webhook latency | p50 / p95 / p99 processing duration | Line chart |
| Request volume | Requests per minute by endpoint group | Stacked area |
| Success/failure ratio | HTTP 2xx vs 4xx vs 5xx | Stacked bar |
| Active installations | GitHub App installations processing webhooks | Number |
| Cron job health | Last run time, success/failure per job | Table |
| Agent metrics | Claude API calls, avg latency, token usage | Line chart + number |
| Top errors | Most frequent exceptions (last 24h) | Table |
| Rate limit hits | Rate-limited requests per hour | Bar chart |

### 4.2 Time Ranges

Default view: last 24 hours. Presets for 1h, 6h, 24h, 7d, 30d.

### Acceptance Criteria

- [x] PostHog dashboard created with all panels listed above
- [x] Dashboard is shared with the Canon team
- [x] Error rate panel shows exceptions/minute and percentage of total requests
- [x] Webhook latency panel shows p50/p95/p99 percentiles
- [x] Request volume panel breaks down by endpoint group
- [x] Cron job health panel shows last run status per job type
- [x] Agent metrics panel shows Claude API call volume and latency
- [ ] Dashboard loads in under 5 seconds

## 5. Enhanced Instrumentation

<!-- canon:system:5 status:done -->

Add PostHog events and properties to power the SRE dashboard and alerting. All new events go through the existing `analytics.track()` wrapper.

### 5.1 New Events

| Event | Properties | Source |
|-------|-----------|--------|
| `request_completed` | `method`, `path`, `status`, `duration_ms`, `user_agent` | Request logging middleware |
| `cron_job_executed` | `job_name`, `success`, `duration_ms`, `error_message` | Cron job wrapper |
| `agent_call_completed` | `model`, `duration_ms`, `input_tokens`, `output_tokens`, `tool_calls`, `success` | Agent client |
| `db_query_slow` | `query_type`, `duration_ms`, `table` | DB middleware (queries > 500ms) |
| `rate_limit_hit` | `path`, `user_id`, `ip`, `limit`, `window` | Rate limit middleware |
| `health_check_failed` | `check_type`, `error_message` | Health check endpoint |

### 5.2 Implementation Approach

- **Request tracking**: Extend `RequestLoggingMiddleware` to call `analytics.track("request_completed", ...)` alongside existing logging
- **Cron wrapper**: Create a decorator `@tracked_cron(job_name)` that wraps cron functions with timing and success/failure tracking
- **Agent tracking**: Add instrumentation in `src/canon/agent/client.py` after Claude API calls
- **Slow query detection**: Add asyncpg query hook or middleware for queries exceeding threshold

### Acceptance Criteria

- [x] `request_completed` events tracked for all non-health-check HTTP requests
- [x] `cron_job_executed` events tracked for all cron jobs with duration and success status
- [x] `agent_call_completed` events tracked with model, duration, and token counts
- [x] `db_query_slow` events tracked for queries exceeding 500ms
- [x] `rate_limit_hit` events tracked when rate limiter rejects a request
- [x] All new events use the existing `analytics.track()` wrapper
- [x] Event volume does not degrade application performance (< 1ms overhead per event)
- [x] Events include enough context for dashboard panels and alert conditions

## 6. GitHub Issues from Error Patterns

<!-- canon:system:6 status:done -->

Automatically create GitHub issues when PostHog detects recurring error patterns, bridging monitoring into the development workflow.

### 6.1 Triage Logic

When a new error cluster is detected in PostHog (via error tracking groups):

1. Check if a GitHub issue already exists for this error fingerprint (dedup)
2. If not, create a GitHub issue with:
   - Title: exception type and short message
   - Body: stack trace, frequency, first/last seen, affected endpoints
   - Labels: `bug`, `auto-triage`, severity label
   - Link to PostHog error group
3. If the Canon bot can determine a related spec, add spec context to the issue body

### 6.2 Dedup Strategy

- Store error fingerprint → GitHub issue mapping in the database
- Before creating, query for existing open issues with the same fingerprint
- If issue exists and is closed, reopen with "recurrence" comment instead of creating new

### 6.3 Integration Points

- **Trigger**: PostHog webhook on new error group, OR periodic scan via cron job
- **GitHub API**: Use existing `github/client.py` with installation tokens
- **Database**: New table `error_issue_map(fingerprint, issue_number, repo, created_at)`

### Acceptance Criteria

- [x] New error patterns in PostHog automatically create GitHub issues
- [x] Issues include stack trace, frequency, PostHog link, and severity label
- [x] Duplicate errors do not create duplicate issues (fingerprint dedup)
- [x] Closed issues are reopened on error recurrence with a comment
- [x] Database table tracks error fingerprint → issue mapping
- [x] Canon bot adds spec context to auto-created issues when a related spec is identified
- [x] Auto-triage can be disabled per-repo via CANON.yaml config

## 7. Canon Bot SRE Mode

<!-- canon:system:7 status:done -->

Extend the Canon bot's capabilities to participate in SRE workflows — analyzing errors against specs and providing weekly digests.

### 7.1 Error Analysis on Auto-Created Issues

When a GitHub issue is auto-created from an error (Section 6), the Canon bot:

1. Identifies which spec sections relate to the affected code path
2. Comments on the issue with spec context: "This error is in the webhook handler covered by spec X, section Y"
3. Suggests whether this is a regression (AC was previously passing) or a gap (AC not yet implemented)

### 7.2 Weekly SRE Digest

A weekly summary posted to Slack (`#canon-alerts`) with:

- Total errors this week vs. last week (trend)
- Top 5 error patterns by frequency
- New errors first seen this week
- Cron job success rate
- Webhook processing latency trends
- Open auto-triaged issues

### 7.3 Implementation

- Reuse existing agent infrastructure (`src/canon/agent/`) for error analysis
- Weekly digest as a cron job using `@tracked_cron` from Section 5
- Slack delivery via the `alerts/slack.py` module from Section 3

### Acceptance Criteria

- [x] Canon bot comments on auto-created error issues with relevant spec context
- [x] Bot identifies spec sections related to the affected code path
- [x] Weekly SRE digest posted to Slack with error trends and top patterns
- [x] Digest includes week-over-week error count comparison
- [x] Digest runs as a tracked cron job
- [x] SRE mode can be enabled/disabled via CANON.yaml

## 8. Configuration

<!-- canon:system:8 status:done -->

All SRE features should be configurable via environment variables and CANON.yaml.

### 8.1 Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `SLACK_ALERTS_WEBHOOK_URL` | Slack incoming webhook for alerts | (none, disables Slack alerts) |
| `SRE_ALERTS_ENABLED` | Master toggle for alerting pipeline | `true` |
| `SRE_ERROR_SPIKE_THRESHOLD` | Exception count threshold for spike alert | `10` |
| `SRE_ERROR_SPIKE_WINDOW` | Time window for spike detection (seconds) | `300` |
| `SRE_SLOW_QUERY_THRESHOLD_MS` | Slow query detection threshold | `500` |
| `SRE_AUTO_TRIAGE_ENABLED` | Enable auto GitHub issue creation | `true` |
| `SRE_WEEKLY_DIGEST_ENABLED` | Enable weekly SRE digest | `true` |

### 8.2 CANON.yaml Integration

```yaml
sre:
  alerts_channel: "#canon-alerts"
  auto_triage: true
  weekly_digest: true
  error_spike_threshold: 10
```

### Acceptance Criteria

- [x] All SRE features togglable via environment variables
- [x] CANON.yaml `sre` section parsed and validated
- [x] Sensible defaults — alerting works with minimal config
- [x] Missing Slack webhook gracefully disables Slack delivery (no errors)

## 9. Rollout Plan

<!-- canon:system:9 status:done -->

Phased rollout to build confidence incrementally:

**Phase 1 — Instrumentation (Section 5)**
Add events first so the dashboard has data. Low risk, no external dependencies.

**Phase 2 — Dashboard (Section 4)**
Build the PostHog dashboard once events are flowing. Visual validation of data quality.

**Phase 3 — Slack Alerts (Sections 2 + 3)**
Configure PostHog alerts and Slack webhook. Start with high-severity alerts only to avoid noise.

**Phase 4 — Auto-Triage (Section 6)**
Enable GitHub issue creation from errors. Monitor for false positives before enabling for all repos.

**Phase 5 — Bot SRE Mode (Section 7)**
Extend Canon bot with error analysis and weekly digest. Depends on Sections 3 + 6.

### Acceptance Criteria

- [x] Each phase is deployable independently
- [x] Phase 1 can ship without Slack or GitHub issue integration
- [x] Alert thresholds are tuned based on 1 week of baseline data before enabling notifications

## 10. Open Questions

- What Slack workspace and channel should alerts go to? (Existing workspace or new?)
- Should the SRE dashboard be public within the PostHog project or restricted?
- PostHog alerting limitations — do we need a separate alerting service (e.g., custom cron that queries PostHog API)?
- Should auto-triaged issues go to a specific GitHub project board?
- Token budget for Canon bot SRE analysis — how much Claude usage per error?
