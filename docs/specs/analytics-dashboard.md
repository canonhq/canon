---
title: "Analytics Dashboard"
status: in_progress
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-03-24
updated: 2026-03-24
tags: [enterprise, analytics, dashboard, admin, posthog]
---

# Analytics Dashboard

A top-level analytics view in the Canon web app that proves Canon's value to enterprise customers. Surfaces a time-based health score combining momentum, freshness, and time-to-ship metrics — all powered by PostHog event data. Tiered access: org admins see org-wide metrics, engineering managers see their team's view.

## 1. Background

<!-- canon:system:1 status:done -->

Canon tracks extensive operational data via PostHog (webhooks, syncs, PR analyses, editor saves, MCP tool calls, auth events) but none of this is visible to org admins. Enterprise customers need to justify Canon's value to leadership — they need a dashboard that answers: "Is Canon making us faster? Is the team using it? Are our specs living documents or shelfware?"

**Existing infrastructure:**
- ~20 PostHog event types already tracked server-side via `analytics.track()`
- Daily coverage snapshot CronJob captures per-spec coverage metrics
- Coverage API (`/api/coverage`) with trend data and repo/team breakdowns
- Permission system with `specs:read`, `specs:write`, `specs:admin` roles
- PostHog group analytics with `organization` group type

**Related specs:**
- `enterprise-adoption-enablement.md` (draft) — Engineering Metrics Export section (§7) defines future webhook/API export; this dashboard is the in-app counterpart
- `enterprise-scale-infrastructure.md` (draft) — infrastructure changes that affect event volume
- `observability.md` (done) — PostHog integration foundation

**Sub-project context:** This is the first spec in a decomposed enterprise admin suite. Follow-up specs will cover user/role management, org settings, billing admin, and audit logs.

## 2. PostHog Event Taxonomy

<!-- canon:system:2 status:in_progress -->

Enrich Canon's PostHog event stream with lifecycle events that power the analytics dashboard. Existing events are leveraged as-is; new events fill gaps in ticket mapping, spec lifecycle, config usage, and SRE tracking.

**Event inventory for health score computation:**

| Event | Status | Used By |
|-------|--------|---------|
| `spec_saved` | Existing (`editor_routes.py`) | Momentum, Freshness |
| `pr_analyzed` | Existing (`on_pull_request.py`) | Momentum, Freshness, Time-to-Ship |
| `mcp_tool_called` | Existing (`mcp/server.py`) | Momentum |
| `forward_sync_completed` | Existing (`on_push.py`) | — (aggregate; replaced by per-ticket events below) |
| `ticket_created` | **New** | Momentum, Time-to-Ship, Adoption |
| `ticket_closed` | **New** | Time-to-Ship |
| `ac_realized` | **New** | Momentum, Coverage |
| `spec_detected` | **New** | Time-to-Ship |
| `spec_status_changed` | **New** | Freshness |
| `config_loaded` | **New** | Feature Usage |

### 2.1 Ticket Mapping Lifecycle Events

New events emitted from the sync engine (`sync/engine.py`) and webhook router (`webhooks/router.py`) to track individual ticket operations. The existing `forward_sync_completed` is aggregate — these provide per-ticket granularity needed for cycle time and adoption metrics.

| Event | Emit Location | Key Properties |
|-------|--------------|----------------|
| `ticket_created` | `engine.forward_sync` after `adapter.create_ticket` | `repo, spec_path, section_id, ticket_system, ticket_id, issue_type, routed_to` |
| `ticket_deduped` | `engine.forward_sync` on dedup match | `repo, spec_path, section_id, ticket_id, dedup_method` |
| `ticket_closed` | `engine.forward_sync` lifecycle sync | `repo, spec_path, section_id, ticket_id, reason` |
| `ticket_reopened` | `engine.forward_sync` lifecycle sync | `repo, spec_path, section_id, ticket_id` |
| `ticket_status_synced` | `engine.reverse_sync` on status change | `repo, spec_path, section_id, ticket_id, old_state, new_state, ticket_system` |
| `ticket_routing_matched` | `sync/engine.forward_sync` during routing rule evaluation | `repo, spec_path, section_id, matched_rule, target_system` |

### 2.2 Spec Lifecycle Events

New events tracking spec document lifecycle, emitted from push handlers (`github/handlers/on_push.py`) and the coverage cron.

| Event | Emit Location | Key Properties |
|-------|--------------|----------------|
| `spec_detected` | `on_push` when new spec first seen | `repo, spec_path, title, author, team, type, section_count, ac_count` |
| `spec_status_changed` | `on_push` when frontmatter status differs | `repo, spec_path, from_status, to_status` |
| `ac_realized` | PR analysis when AC linked to code | `repo, spec_path, section_id, ac_index, pr_number, confidence` |
| `stale_spec_detected` | stale detection cron | `repo, spec_path, days_since_update, last_code_change` |

### 2.3 CANON.yaml Feature Usage Events

New events tracking which features each repo has enabled, emitted when config is loaded.

| Event | Emit Location | Key Properties |
|-------|--------------|----------------|
| `config_loaded` | `org_config` on CANON.yaml parse | `repo, auto_tickets, require_review, lifecycle_sync, ticket_systems, routing_rules_count, ide_auto_context, ide_auto_verify, sre_enabled, has_ticket_mapping` |
| `config_feature_used` | Various feature activation points | `repo, feature, outcome` |

### 2.4 SRE Events

| Event | Emit Location | Key Properties |
|-------|--------------|----------------|
| `sre_alert_fired` | Alert handler | `repo, alert_type, severity, details` |
| `weekly_digest_sent` | Weekly digest cron | `org, repos_covered, specs_covered, alerts_count` |

### 2.5 Group Analytics Standardization

All `analytics.track()` calls must include `groups={"organization": org}` to enable PostHog org-level aggregation. Existing calls that omit the group parameter must be updated where org context is available.

**Call sites requiring migration** (omit `groups` today):
- `mcp/server.py` — ~11 `mcp_tool_called` calls (org available from request context)
- `webhooks/router.py` — `webhook_ticket_sync` (org available from webhook payload)
- `agent/client.py` — `agent_call_completed` (org passed as parameter)
- `alerts/cron_utils.py` — `cron_job_executed` (org may not be available; skip if not)
- `db/query_hooks.py` — `db_query_slow` (no org context; skip)

**Call sites to skip** (no org context available, or org-agnostic):
- `auth/deps.py` — `auth_denied` events (fires before org is resolved)
- `auth/middleware.py` — `auth_denied` events (same reason)
- `main.py` — `health_check_failed` (system-level, no org)
- `web/middleware.py` — `rate_limit_hit` (fires before org resolution)

### Acceptance Criteria

- [x] `ticket_created` event emitted on every individual ticket creation in forward sync
<!-- canon:realized-in:audit file:src/canon/sync/engine.py:304 -->
<!-- canon:realized-in:PR#503 file:src/canon/github/handlers/on_push.py -->
- [x] `ticket_deduped` event emitted when dedup finds existing ticket (with method: fingerprint or title)
<!-- canon:realized-in:audit file:src/canon/sync/engine.py:261 -->
- [x] `ticket_closed` event emitted when lifecycle sync closes a ticket
<!-- canon:realized-in:audit file:src/canon/sync/engine.py:366 -->
- [x] `ticket_reopened` event emitted when lifecycle sync reopens a ticket
<!-- canon:realized-in:audit file:src/canon/sync/engine.py:399 -->
- [x] `ticket_status_synced` event emitted on every reverse sync status change
<!-- canon:realized-in:audit file:src/canon/sync/engine.py:594 -->
<!-- canon:realized-in:PR#503 file:src/canon/cron/sync_status.py -->
- [ ] `ticket_routing_matched` event emitted when routing rules resolve a section to a target system
- [x] `spec_detected` event emitted when a new spec file is first seen on push
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_push.py:330 -->
- [x] `spec_status_changed` event emitted when spec frontmatter status changes between pushes
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_push.py:354 -->
- [x] `ac_realized` event emitted individually for each AC realized during PR analysis
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_pull_request.py:364 -->
- [x] `stale_spec_detected` event emitted by stale detection when spec exceeds threshold
<!-- canon:realized-in:audit file:src/canon/cron/stale_check.py:120 -->
- [x] `config_loaded` event emitted when CANON.yaml is parsed, including all feature flag booleans
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_push.py:293 -->
- [ ] `config_feature_used` event emitted when a config-driven feature activates
- [x] `sre_alert_fired` event emitted when SRE alerting triggers
<!-- canon:realized-in:audit file:src/canon/alerts/slack.py:49 -->
- [x] `weekly_digest_sent` event emitted when weekly digest is delivered
<!-- canon:realized-in:audit file:src/canon/cron/weekly_digest.py:52 -->
- [x] Existing `analytics.track()` calls with org context include `groups={"organization": org}` (mcp, webhooks, agent — ~15 call sites; editor already migrated)
<!-- canon:realized-in:audit file:src/canon/mcp/server.py:197 file:src/canon/sync/engine.py:269 file:src/canon/agent/client.py:76 -->
- [x] Call sites without org context (auth denials, health checks, rate limits, slow queries) are left as-is
<!-- canon:realized-in:audit file:src/canon/auth/deps.py file:src/canon/main.py -->
- [x] All new events include `groups={"organization": org}` parameter
<!-- canon:realized-in:audit file:src/canon/sync/engine.py:313 file:src/canon/github/handlers/on_push.py:340 -->

## 3. Health Score Algorithm

<!-- canon:system:3 status:in_progress -->

A time-based composite score (0–100) that measures Canon's value in an organization. The score rewards momentum and freshness over static coverage, answering "is Canon making things better over time?"

### 3.1 Momentum Pillar (35% weight)

Measures whether Canon activity is trending up, flat, or declining over a rolling 4-week window.

```
activities = [spec_saved, ticket_created, pr_analyzed, ac_realized, mcp_tool_called]

this_week  = count(activities, last 7 days)
prev_week  = count(activities, 8–14 days ago)
four_wk_avg = count(activities, last 28 days) / 4

week_over_week = clamp(this_week / prev_week, 0.5, 2.0)
trend_vs_avg   = clamp(this_week / four_wk_avg, 0.5, 2.0)

momentum_raw = week_over_week * 0.6 + trend_vs_avg * 0.4
momentum = normalize(momentum_raw, range=[0.5, 2.0], output=[0, 100])
```

- Score 50 = flat (same activity as prior weeks)
- Above 50 = growing adoption
- Below 50 = declining usage

### 3.2 Freshness Pillar (30% weight)

Measures how well specs track reality. A "fresh" org has specs that evolve alongside code changes.

```
For each spec with at least one AC:
  days_since_spec_update = now - max(spec_saved.timestamp, spec_status_changed.timestamp)
  days_since_code_change = now - max(pr_analyzed.timestamp where spec referenced)

  If no PR has ever referenced this spec:
    Exclude from freshness calculation (spec has no code counterpart yet)

  staleness_gap = days_since_spec_update - days_since_code_change

  spec_freshness = 100                              if staleness_gap ≤ 7
                   max(0, 100 - (staleness_gap - 7) * 5)  otherwise

org_freshness = weighted_average(spec_freshness, weight=spec.total_ac)
               (only includes specs with at least one associated PR)
```

Specs with more ACs weigh more — a stale 50-AC spec matters more than a stale 3-AC one. Specs with no associated PRs are excluded from the calculation (they have no code counterpart to measure freshness against).

### 3.3 Time-to-Ship Pillar (35% weight)

Measures how quickly work moves through Canon's lifecycle stages, compared to the org's own historical baseline.

```
Lifecycle stages (median days, trailing period):
  spec_detected    → ticket_created   = "Planning"
  ticket_created   → first pr_analyzed = "Development Start"
  first pr_analyzed → PR merged        = "Review Cycle"
  PR merged        → ticket_closed     = "Completion Lag"

total_cycle = sum of stage medians (last N days, where N = `days` query param, default 30)
baseline    = sum of stage medians (days N+1 through 2N ago)

improvement_ratio = clamp(baseline / total_cycle, 0.5, 2.0)
time_to_ship = normalize(improvement_ratio, range=[0.5, 2.0], output=[0, 100])
```

Self-referential: measures whether the org is getting faster, not compared to an arbitrary benchmark. New orgs start at 50.

### 3.4 Composite Score

```
health_score = momentum * 0.35 + freshness * 0.30 + time_to_ship * 0.35
```

Score interpretation:
- 80–100: Excellent — Canon deeply integrated, measurable acceleration
- 60–79: Good — strong adoption, some freshness or velocity gaps
- 40–59: Growing — early adoption, clear improvement trajectory
- 0–39: Getting Started — insufficient data or very early usage

### 3.5 Insufficient Data Handling

When an org has fewer than 7 days of event data, the health score shows "Insufficient data" rather than a misleading number. Individual pillars that lack data show "—" with a tooltip explaining what data is needed.

### Acceptance Criteria

- [x] Momentum pillar computed from 4-week rolling activity counts across 5 event types
<!-- canon:realized-in:audit file:src/canon/health_score.py:28 file:src/canon/web/analytics_routes.py:115-123 -->
- [x] Momentum score of 50 represents flat activity (same as prior week)
<!-- canon:realized-in:audit file:src/canon/health_score.py:16-38 -->
- [x] Freshness pillar computed from per-spec staleness gap weighted by AC count
<!-- canon:realized-in:audit file:src/canon/health_score.py:41-52 -->
- [x] Freshness excludes specs with no associated PR events (no code counterpart)
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:138-146 -->
- [x] Freshness penalizes specs where code changed but spec didn't update (staleness gap > 7 days)
<!-- canon:realized-in:audit file:src/canon/health_score.py:50 -->
- [ ] Time-to-Ship pillar computed from median lifecycle stage durations
- [x] Time-to-Ship is self-referential (current period vs org's own prior period)
<!-- canon:realized-in:audit file:src/canon/health_score.py:55-61 file:src/canon/web/analytics_routes.py:173-191 -->
- [x] Composite health score uses weights: Momentum 35%, Freshness 30%, Time-to-Ship 35%
<!-- canon:realized-in:audit file:src/canon/health_score.py:65 -->
- [ ] Orgs with < 7 days of data show "Insufficient data" instead of a score
- [x] Individual pillars without data show "—" with explanatory tooltip
<!-- canon:realized-in:audit file:frontend/src/components/analytics/PillarCard.vue:22 -->
- [x] Health score computation handles division by zero gracefully (empty periods)
<!-- canon:realized-in:audit file:src/canon/health_score.py:11,29-34,57 -->

## 4. Analytics API

<!-- canon:system:4 status:in_progress -->

New backend endpoints that query PostHog via HogQL and shape data for the frontend dashboard. Uses a new `analytics_query.py` module separate from the existing write-only `analytics.py`.

### 4.1 PostHog Query Client

New module `src/canon/analytics_query.py` wrapping PostHog's Query API for server-side reads.

```python
class PostHogQueryClient:
    """Read-only PostHog query client using HogQL."""

    def __init__(self, api_key: str, project_id: str, host: str): ...
    async def query(self, hogql: str) -> list[dict]: ...
```

Uses `httpx` with the PostHog personal API key (new setting: `POSTHOG_PERSONAL_API_KEY`). The existing `POSTHOG_KEY` is a project API key (write-only); querying requires a personal API key with read access.

Configuration:
- Request timeout: 10 seconds per query
- Max result rows: 10,000 (sufficient for weekly aggregations across any org size)
- On timeout or error: return stale cached data if available, otherwise return `{"error": "analytics_unavailable"}` with HTTP 200 (not 500 — partial page render is better than a crash)
- No retries — the aggressive caching layer means the next request will retry naturally

### 4.2 API Endpoints

All endpoints mounted under `/app/{org}/api/analytics/`, requiring `specs:read` permission.

**`GET /health`** — Health score + 3 pillars + 30-day sparkline trend
- Query params: `team` (optional), `days` (default 30)
- Returns: `{ score, label, trend: [{date, score}], pillars: {momentum: {score, delta, summary}, freshness: {...}, time_to_ship: {...}} }`
- Cache: 1 hour

**`GET /momentum`** — Activity trends, top repos, top contributors
- Query params: `team`, `days`
- Returns: `{ weekly_activity: [{week, event_type, count}], top_repos: [{repo, count}], top_contributors: [{user, count}] }`
- Cache: 15 minutes

**`GET /freshness`** — Per-spec freshness scores
- Query params: `team`, `days`
- Returns: `{ specs: [{spec_path, repo, freshness_score, days_since_update, days_since_code}], summary: {fresh_count, stale_count, avg_gap_days} }`
- Cache: 15 minutes

**`GET /time-to-ship`** — Cycle time stages and trend
- Query params: `team`, `days`
- Returns: `{ stages: [{name, median_days, trend_pct}], total_cycle_days, improvement_pct, trend: [{week, total_cycle}] }`
- Cache: 15 minutes

**`GET /feature-usage`** — CANON.yaml feature adoption across repos
- Query params: none (always org-wide)
- Returns: `{ features: [{name, enabled_count, total_repos, pct}], repos_with_config, repos_without_config }`
- Cache: 1 hour

### 4.3 Permission Scoping

Admins (`specs:admin` permission) see org-wide data by default with an optional `team` filter. Non-admin users also see org-wide data but cannot access the `/feature-usage` endpoint (org-level config data).

**Note on team scoping:** Canon does not currently model user-to-team membership. The `team` query parameter is a voluntary filter — users select their team from a dropdown populated by distinct `team` values found across specs in the org. A future "User & Role Management" spec (part of the enterprise admin suite) will introduce team assignment, at which point non-admin users can be auto-scoped. Until then, all authenticated users see org-wide analytics with optional team filtering.

```python
# Feature-usage is admin-only (exposes org config details)
@app_router.get("/{org}/api/analytics/feature-usage")
async def api_feature_usage(
    ...,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_ADMIN)),
): ...

# Other analytics endpoints use specs:read (all authenticated users)
@app_router.get("/{org}/api/analytics/health")
async def api_analytics_health(
    ...,
    team: str = "",  # voluntary filter
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
): ...
```

### 4.4 Caching Strategy

Cache keys: `analytics:{org}:{endpoint}:{team}:{days}`. Use in-process TTL cache (consistent with existing `_cache` patterns in `org_config.py`). Caches are TTL-only with no event-driven invalidation — analytics data is inherently approximate and a 15–60 minute lag is acceptable. When the shared cache layer (enterprise-scale-infrastructure spec) is implemented, these caches migrate automatically.

### Acceptance Criteria

- [x] New `PostHogQueryClient` class in `src/canon/analytics_query.py` queries PostHog HogQL API
<!-- canon:realized-in:audit file:src/canon/analytics_query.py:14 -->
<!-- canon:realized-in:PR#509 file:.github/scripts/export-oss.sh -->
- [ ] New setting `POSTHOG_PERSONAL_API_KEY` for read access to PostHog query API
- [x] `GET /analytics/health` returns composite score, pillar breakdown, and 30-day trend
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:506 -->
- [x] `GET /analytics/momentum` returns weekly activity, top repos, and top contributors
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:521 -->
- [x] `GET /analytics/freshness` returns per-spec freshness scores and summary
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:536 -->
- [x] `GET /analytics/time-to-ship` returns lifecycle stage durations and improvement trend
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:551 -->
- [x] `GET /analytics/feature-usage` returns CANON.yaml feature adoption percentages
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:566 -->
- [x] Health, momentum, freshness, time-to-ship endpoints require `specs:read` permission
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:512,527,542,557 -->
- [x] Feature-usage endpoint requires `specs:admin` permission
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:570 -->
- [x] All endpoints except feature-usage accept optional `team` query parameter for voluntary filtering
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:510,525,540,555 -->
- [ ] Team dropdown populated from distinct `team` values across org's specs
- [ ] PostHog query timeout set to 10 seconds; stale cache returned on timeout
- [x] Health endpoint cached for 1 hour
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:517 -->
- [x] Momentum, freshness, time-to-ship endpoints cached for 15 minutes
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:532,547,562 -->
- [x] Feature-usage endpoint cached for 1 hour
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:575 -->
- [x] Endpoints return graceful "insufficient data" response when PostHog has no events
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:88-89 -->
- [x] Endpoints handle PostHog API errors without crashing (return partial data or error message)
<!-- canon:realized-in:audit file:src/canon/web/analytics_routes.py:93-96 -->

## 5. Frontend Dashboard

<!-- canon:system:5 status:in_progress -->

New Vue 3 view and components implementing the Executive Summary layout: hero health score, pillar cards, and stacked trend charts.

### 5.1 Route and Navigation

Add route `/app/:org/analytics` in `router/index.ts`. Add "Analytics" link to `AppNav.vue` (`frontend/src/components/layout/AppNav.vue`) main navigation between "Tasks" and "Editor", visible to all authenticated users (all roles have `specs:read`).

### 5.2 Component Architecture

```
views/AnalyticsView.vue
  ├─ AnalyticsFilterBar.vue     — team picker + time range (7d/30d/90d)
  ├─ HealthScoreHero.vue        — big score, progress bar, sparkline, label
  ├─ PillarRow.vue
  │   ├─ PillarCard.vue         — Momentum (score, ↑↓→, summary text)
  │   ├─ PillarCard.vue         — Freshness
  │   └─ PillarCard.vue         — Time-to-Ship
  ├─ MomentumChart.vue          — weekly activity area chart
  ├─ FreshnessChart.vue         — spec freshness bar chart (fresh vs stale)
  ├─ CycleTimeChart.vue         — lifecycle stage waterfall/funnel
  └─ FeatureUsageBar.vue        — horizontal bars: % repos with each feature
```

### 5.3 Data Fetching

`AnalyticsView.vue` fetches `/analytics/health` on mount to populate the hero and pillars instantly. Chart components below the fold lazy-load their data using IntersectionObserver — they call their respective endpoints only when scrolled into view.

New API client at `frontend/src/api/analytics.ts`:

```typescript
export function fetchHealth(org: string, team?: string, days?: number): Promise<HealthResponse>
export function fetchMomentum(org: string, team?: string, days?: number): Promise<MomentumResponse>
export function fetchFreshness(org: string, team?: string, days?: number): Promise<FreshnessResponse>
export function fetchTimeToShip(org: string, team?: string, days?: number): Promise<TimeToShipResponse>
export function fetchFeatureUsage(org: string): Promise<FeatureUsageResponse>
```

### 5.4 Charting

Use Chart.js via `vue-chartjs` for all visualizations:
- **MomentumChart**: stacked area chart, one series per event type, grouped by week
- **FreshnessChart**: horizontal bar chart, specs sorted by freshness score, colored green/yellow/red
- **CycleTimeChart**: horizontal waterfall showing median days per lifecycle stage
- **FeatureUsageBar**: horizontal bars showing "X of Y repos" for each CANON.yaml feature

### 5.5 EM vs Admin View

Same route and components for both roles. The `AnalyticsFilterBar` team picker:
- **Admins**: shows "All teams" (default) plus individual team options
- **Non-admins**: same team picker, but no access to Feature Usage section (requires `specs:admin`). Future User & Role Management spec will add user-to-team assignment for auto-scoping.
- Team selection is passed as query param to all API calls

### 5.6 Empty and Loading States

- While health data loads: skeleton placeholder matching hero + pillar layout
- Charts show `LoadingSpinner.vue` (existing at `components/common/LoadingSpinner.vue`) while fetching
- Insufficient data (< 7 days): `EmptyState.vue` (existing at `components/common/EmptyState.vue`) with message explaining what data is needed
- PostHog not configured (`POSTHOG_PERSONAL_API_KEY` unset): `EmptyState` directing admin to configure PostHog integration

### Acceptance Criteria

- [x] New route `/app/:org/analytics` renders `AnalyticsView.vue`
<!-- canon:realized-in:audit file:frontend/src/router/index.ts:64-65 -->
- [x] "Analytics" link added to `AppNav.vue` main navigation
<!-- canon:realized-in:audit file:frontend/src/components/layout/AppNav.vue:33-36 -->
- [ ] `HealthScoreHero` displays score (0–100), progress bar, label, and 30-day sparkline
- [x] `PillarRow` shows three `PillarCard` components with score, directional arrow, and summary
<!-- canon:realized-in:audit file:frontend/src/components/analytics/PillarRow.vue file:frontend/src/components/analytics/PillarCard.vue -->
- [x] `AnalyticsFilterBar` supports team picker and time range selector (7d/30d/90d)
<!-- canon:realized-in:audit file:frontend/src/components/analytics/AnalyticsFilterBar.vue -->
- [x] Non-admin users see the same team picker but cannot access Feature Usage section
<!-- canon:realized-in:audit file:frontend/src/views/AnalyticsView.vue:22,44 -->
- [ ] `MomentumChart` renders weekly activity as stacked area chart
- [x] `FreshnessChart` renders per-spec freshness as horizontal bar chart
<!-- canon:realized-in:audit file:frontend/src/components/analytics/FreshnessChart.vue -->
- [x] `CycleTimeChart` renders lifecycle stages as waterfall chart
<!-- canon:realized-in:audit file:frontend/src/components/analytics/CycleTimeChart.vue -->
- [x] `FeatureUsageBar` renders CANON.yaml feature adoption as horizontal bars
<!-- canon:realized-in:audit file:frontend/src/components/analytics/FeatureUsageBar.vue -->
- [x] Charts lazy-load data when scrolled into view (IntersectionObserver)
<!-- canon:realized-in:audit file:frontend/src/components/analytics/MomentumChart.vue:28 file:frontend/src/components/analytics/FreshnessChart.vue:26 file:frontend/src/components/analytics/CycleTimeChart.vue:27 file:frontend/src/components/analytics/FeatureUsageBar.vue:27 -->
- [x] Health score and pillars load on page mount (not lazy)
<!-- canon:realized-in:audit file:frontend/src/views/AnalyticsView.vue:24-27 -->
- [ ] Loading state shows skeleton placeholders
- [x] Insufficient data state shows explanatory empty state
<!-- canon:realized-in:audit file:frontend/src/views/AnalyticsView.vue:51-52 -->
- [x] Chart.js / vue-chartjs used for all chart components (already in `frontend/package.json`)
<!-- canon:realized-in:audit file:frontend/src/components/analytics/MomentumChart.vue:15 file:frontend/src/components/analytics/FreshnessChart.vue:13 -->
- [x] All components follow existing Vue 3 Composition API patterns
<!-- canon:realized-in:audit file:frontend/src/views/AnalyticsView.vue:1 -->

## Open Questions

1. **PostHog personal API key management**: The query API requires a personal API key, not the project API key. Should this be a single org-wide key stored as an env var, or should each admin authenticate with their own PostHog credentials? Recommendation: single org-wide key via `POSTHOG_PERSONAL_API_KEY` env var — simpler, and analytics data is already org-scoped.

2. **Historical backfill**: New events (ticket_created, spec_detected, etc.) won't have historical data. Should we backfill from existing `coverage_snapshot` and `agent_events` DB tables, or accept that the dashboard starts from "day one" of the new events? Recommendation: start fresh — backfill is complex and the dashboard is forward-looking by design (momentum and time-to-ship are inherently time-relative).

3. **PostHog rate limits**: HogQL queries against PostHog's API have rate limits. With 6 endpoints potentially queried simultaneously on page load, should we implement a server-side batch query that fetches all data in fewer PostHog API calls? Recommendation: start with individual queries + aggressive caching; batch only if rate limits become an issue.

4. **Self-hosted PostHog**: Enterprise customers self-hosting Canon may not have PostHog configured. Should the analytics dashboard degrade gracefully (show "configure PostHog" message) or should we support an alternative backend (e.g., query from coverage_snapshot DB table for basic metrics)? Recommendation: graceful degradation with a fallback to coverage-only metrics from the existing DB snapshots.
