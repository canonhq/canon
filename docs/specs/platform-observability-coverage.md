---
title: "Platform Observability Coverage"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-03-20
updated: 2026-03-20
tags: [observability, posthog, instrumentation, infrastructure, kubernetes, monitoring]
---

# Platform Observability Coverage

Close observability blind spots across the full Canon stack — application instrumentation gaps, Kubernetes job visibility, infrastructure health, and external integration monitoring.

## 1. Background

<!-- canon:system:1 status:done -->

Canon's core request path is well-instrumented (HTTP requests, webhooks, agent calls, auth, rate limiting). But production incidents like the `channel_binding` TypeError revealed that significant parts of the platform operate in the dark. The app caught the error, logged a warning, and continued without a database — on every pod restart — for an unknown period. The OTel log export eventually surfaced it as a raw log in PostHog, but there was no alert, no discrete event, and no dashboard panel for it.

**What's instrumented today (good):**
- HTTP requests (`request_completed`), webhooks (`webhook_received`), agent calls (`agent_call_completed`)
- Auth denials, rate limiting, health check failures
- Global exception handler + PostHog autocapture
- OTel log export (WARNING+) to PostHog

**What's not instrumented (this spec):**
- Application startup/initialization failures
- 4 of 5 CronJobs (only `weekly_digest` uses `@tracked_cron`)
- GitHub API calls (rate limits, errors, latency)
- Ticket sync adapters (Jira, Linear, GitHub Issues)
- Search/embedding operations (indexing, query latency)
- Database connection pool health
- Billing/Stripe webhook processing
- SSE streaming route errors
- Kubernetes-level events (OOM kills, pod evictions, CronJob failures)

**Related specs:**
- `observability.md` (done) — PostHog exception capture foundation
- `sre-alerting-monitoring.md` (in_progress) — alert rules, SRE dashboard, Slack notifications
- This spec focuses on the *data collection* gaps that feed those systems

## 2. Application Startup & Initialization Events

<!-- canon:system:2 status:todo -->

The `lifespan` function in `main.py` initializes DB pool, embedding client, search index, Stripe, and OIDC. Failures are caught with a broad `except Exception` and logged as warnings, but no discrete PostHog event is emitted. This means startup failures are only visible by scanning raw logs.

### 2.1 Startup Failure Event

Emit a `startup_component_failed` event when any initialization component fails:

| Property | Type | Description |
|----------|------|-------------|
| `component` | string | `database`, `embedding`, `search_index`, `stripe`, `oidc` |
| `error_type` | string | Exception class name |
| `error_message` | string | Exception message |
| `degraded` | bool | `true` if app continues without this component |

### 2.2 Startup Success Event

Emit a `startup_completed` event on successful initialization:

| Property | Type | Description |
|----------|------|-------------|
| `components_healthy` | list[str] | Components that initialized successfully |
| `components_degraded` | list[str] | Components that failed but app continued |
| `startup_duration_ms` | int | Total lifespan startup time |

### Acceptance Criteria

- [ ] `startup_component_failed` event emitted for each component that fails during lifespan startup
- [ ] `startup_completed` event emitted after all initialization attempts, with healthy/degraded component lists
- [ ] Events include exception type and message for failed components
- [ ] The `channel_binding` bug scenario would produce a `startup_component_failed` event with `component=database`

## 3. CronJob Instrumentation

<!-- canon:system:3 status:todo -->

Five CronJobs are defined in the Helm chart. Only `weekly_digest` uses the `@tracked_cron` decorator. The other four run unobserved — if they fail silently, PostHog shows nothing.

### 3.1 CronJobs to Instrument

| CronJob | Helm Template | Module | Schedule | Current Status |
|---------|--------------|--------|----------|----------------|
| Reverse ticket sync | `cronjob.yaml` | `canon.cron.sync_status` | `*/15 * * * *` | No tracking |
| Coverage snapshot | `cronjob-coverage-snapshot.yaml` | `canon.cron.coverage_snapshot` | `0 5 * * *` | No tracking |
| Search reindex | `cronjob-reindex.yaml` | `canon.search.reindex` | `0 2 * * *` | No tracking |
| Stale check | `cronjob-stale-check.yaml` | `canon.cron.stale_check` | `0 6 * * *` | No tracking |
| Weekly digest | `cronjob-weekly-digest.yaml` | `canon.cron.weekly_digest` | `0 9 * * 1` | `@tracked_cron` |

### 3.2 Implementation

Add `@tracked_cron` decorator (or equivalent `analytics.track("cron_job_executed", ...)` calls) to each uninstrumented cron module. The decorator already handles timing, success/failure, and error message capture.

For `canon.search.reindex`, which may not be a simple function wrapper, add explicit tracking at the entry point.

### Acceptance Criteria

- [ ] `sync_status` cron emits `cron_job_executed` event with `job_name=sync_status`
- [ ] `coverage_snapshot` cron emits `cron_job_executed` event with `job_name=coverage_snapshot`
- [ ] `reindex` cron emits `cron_job_executed` event with `job_name=reindex`
- [ ] `stale_check` cron emits `cron_job_executed` event with `job_name=stale_check`
- [ ] All cron events include `success`, `duration_ms`, and `error_message` (on failure)
- [ ] The SRE dashboard "Cron job health" panel (from `sre-alerting-monitoring.md` Section 4) shows data for all 5 jobs

## 4. External Integration Monitoring

<!-- canon:system:4 status:todo -->

Canon calls several external APIs. None are instrumented. An outage or rate limit exhaustion at any of these is invisible.

### 4.1 GitHub API Client

`src/canon/github/client.py` makes API calls for repos, PRs, comments, commits, and file contents. Track:

| Event | Properties |
|-------|-----------|
| `github_api_call` | `method` (GET/POST/PATCH), `endpoint` (e.g. `/repos/{owner}/{repo}/pulls`), `status_code`, `duration_ms`, `rate_limit_remaining`, `rate_limit_reset` |

Rate limit headers (`X-RateLimit-Remaining`, `X-RateLimit-Reset`) should be extracted from every response.

### 4.2 Ticket Sync Adapters

`src/canon/sync/adapters/` contains adapters for Jira, Linear, and GitHub Issues. Track:

| Event | Properties |
|-------|-----------|
| `ticket_sync_operation` | `adapter` (jira/linear/github), `operation` (create/update/fetch), `status_code`, `duration_ms`, `success`, `error_message` |

### 4.3 Embedding & Search

`src/canon/search/` handles Vertex AI embeddings and hybrid search. Track:

| Event | Properties |
|-------|-----------|
| `embedding_request` | `model`, `text_count`, `duration_ms`, `success`, `error_message` |
| `search_query` | `query_type` (vector/bm25/hybrid), `result_count`, `duration_ms` |

### 4.4 Stripe Webhooks

`src/canon/billing/routes.py` processes Stripe webhook events. Track:

| Event | Properties |
|-------|-----------|
| `stripe_webhook_processed` | `event_type` (checkout.session.completed, invoice.paid, etc.), `success`, `duration_ms`, `error_message` |

### Acceptance Criteria

- [ ] GitHub API calls emit `github_api_call` events with status, duration, and rate limit data
- [ ] A PostHog alert can be configured when `rate_limit_remaining` drops below 100
- [ ] Ticket sync operations emit `ticket_sync_operation` events per adapter call
- [ ] Embedding requests emit `embedding_request` events with model and latency
- [ ] Search queries emit `search_query` events with query type and result count
- [ ] Stripe webhook processing emits `stripe_webhook_processed` events
- [ ] Event volume is manageable — GitHub API tracking is sampled or batched if call volume exceeds 1000/hour

## 5. Database Connection Health

<!-- canon:system:5 status:todo -->

The asyncpg connection pool in `src/canon/db/pool.py` has no observability. Pool exhaustion, connection timeouts, and reconnection failures are invisible.

### 5.1 Connection Pool Events

| Event | Properties | Trigger |
|-------|-----------|---------|
| `db_connection_failed` | `error_type`, `error_message`, `component` (pool/migration/query) | Any DB connection failure |
| `db_pool_exhausted` | `pool_size`, `wait_duration_ms` | Connection checkout exceeds timeout |

### 5.2 Periodic Pool Health

Add a lightweight pool health check that runs alongside the existing `/readyz` probe:

| Property | Source |
|----------|--------|
| `pool_size` | `pool.get_size()` |
| `pool_free` | `pool.get_idle_size()` |
| `pool_min` | `pool.get_min_size()` |
| `pool_max` | `pool.get_max_size()` |

This data should be included in the existing `health_check_failed` event when the readiness probe fails, and optionally emitted as a periodic `db_pool_health` event.

### 5.3 URL Parameter Sanitization Logging

When `_sanitise_asyncpg_params` strips libpq-only parameters (like `channel_binding`), emit a one-time info-level log on startup so operators know parameters were modified. This prevents future silent incompatibilities.

### Acceptance Criteria

- [ ] `db_connection_failed` event emitted on pool creation failure, migration failure, or query connection error
- [ ] `health_check_failed` events include pool size and free connection count
- [ ] `_sanitise_asyncpg_params` logs which parameters were stripped (one-time at startup)
- [ ] Database connection failures during lifespan emit both a log AND a discrete PostHog event

## 6. SSE Streaming Error Capture

<!-- canon:system:6 status:todo -->

SSE streaming routes (`/generate`, `/ai-edit`) catch exceptions inside their generator functions because errors occur after HTTP headers are sent. The global exception handler never sees these. Currently these exceptions are logged but not sent to PostHog as events.

### Acceptance Criteria

- [x] SSE streaming route errors call `analytics.capture_exception()` before yielding an error event
<!-- canon:realized-in:PR#496 file:src/canon/agent/analyzer.py -->
- [ ] Streaming errors include route path, user context, and error details
- [ ] Error capture does not break the SSE event stream or connection cleanup

## 7. Kubernetes Infrastructure Observability

<!-- canon:system:7 status:todo -->

Kubernetes-level events (OOM kills, pod evictions, CronJob failures, node pressure) are invisible to PostHog. These events happen outside the application and can't be caught by in-process instrumentation.

### 7.1 Recommended Approach

Rather than building custom K8s event forwarding, leverage the existing OTel pipeline:

1. **K8s Events Exporter**: Deploy a lightweight exporter (e.g., `kubernetes-event-exporter` or OpenTelemetry Collector with `k8s_events` receiver) that forwards K8s events to PostHog's OTLP endpoint
2. **Scope**: Filter to the `canon` namespace only — pod lifecycle events, CronJob completion/failure, OOM kills, evictions
3. **Alternative**: If a full exporter is too heavy, add a simple CronJob that runs `kubectl get events -n canon --field-selector reason=OOMKilled,reason=Evicted` and posts to PostHog

### 7.2 Resource Limit Visibility

Current production limits (512Mi memory) are tight. An OOM kill leaves no trace in PostHog. At minimum:

- Document the expected memory footprint per component
- Add a note in the Helm values about monitoring for OOM kills externally
- Consider adding `GOMAXPROCS` / `GOMEMLIMIT` equivalent Python memory guards that log before OOM

### 7.3 Production Hardening

These items improve reliability alongside observability:

| Item | Current | Recommended |
|------|---------|-------------|
| HPA | Disabled | Enable with min=2, max=4, target CPU 70% |
| PDB | Disabled | Enable with `minAvailable: 1` |
| CronJob history | K8s default (3 success, 1 fail) | Set `successfulJobsHistoryLimit: 3`, `failedJobsHistoryLimit: 5` |

### Acceptance Criteria

- [ ] K8s events in the `canon` namespace (OOM, eviction, CronJob failure) are forwarded to PostHog
- [ ] OR: Documentation of manual monitoring approach with `kubectl` commands for K8s events
- [ ] HPA enabled in production values with min=2, max=4
- [ ] PDB enabled in production values with `minAvailable: 1`
- [ ] CronJob history limits set to retain last 5 failed job pods for debugging

## 8. Terraform & IaC Observability

<!-- canon:system:8 status:todo -->

Canon's infrastructure is managed in `gv-infra/experiments/canon/`. The Terraform config provisions Auth0, GCP Vertex AI, DNS, Stripe, and PostHog — but no infrastructure-level monitoring.

### 8.1 Database Connection String Validation

The Neon database URL includes libpq-specific parameters (`channel_binding`, `sslmode`) that vary by provider. There's no IaC-level validation that the connection string is compatible with asyncpg.

**Recommendation**: Add a CI health check (GitHub Action or Helm test) that validates the DATABASE_URL can connect successfully before deploying. This catches connection parameter incompatibilities before they reach production.

### 8.2 GCP Budget Alerting

A $25/month Vertex AI budget exists in Terraform with 50%/75%/100% thresholds, but alerts only go to GCP billing — not to Slack or PostHog. Route budget alerts to the same `#canon-alerts` channel.

### 8.3 Terraform Drift Detection

No automated drift detection exists. If someone modifies Auth0, DNS, or PostHog config manually, Terraform state diverges silently.

**Recommendation**: Add a scheduled `terraform plan` in CI that alerts on drift.

### Acceptance Criteria

- [ ] CI includes a DB connection validation step that catches parameter incompatibilities (like `channel_binding`)
- [ ] GCP budget alerts route to Slack `#canon-alerts` (via Pub/Sub → Cloud Function → Slack or equivalent)
- [ ] OR: GCP budget alerts documented as manual monitoring gap with mitigation steps
- [ ] Terraform drift detection runs on schedule and alerts on unexpected changes

## 9. Rollout Plan

<!-- canon:system:9 status:todo -->

**Phase 1 — Quick wins (Sections 2, 3)**
- Add startup failure/success events in `main.py` lifespan
- Add `@tracked_cron` to the 4 uninstrumented CronJobs
- Low risk, high signal. These are the blindest spots.

**Phase 2 — Integration monitoring (Section 4)**
- Instrument GitHub API client, ticket sync adapters, embedding/search
- Higher code change surface but uses existing `analytics.track()` pattern

**Phase 3 — Infrastructure health (Sections 5, 6)**
- DB pool health events, SSE streaming error capture
- URL parameter sanitization logging

**Phase 4 — K8s & IaC (Sections 7, 8)**
- Enable HPA and PDB in production
- K8s event forwarding (if justified by incident frequency)
- CI connection validation, drift detection

### Acceptance Criteria

- [ ] Phase 1 ships independently and produces visible data in PostHog within 24 hours
- [ ] Each phase is a separate PR that can be reviewed and deployed independently
- [ ] No phase introduces more than 1ms latency overhead on the request hot path

## 10. Open Questions

- Should we sample high-volume events (GitHub API calls, search queries) or track all?
- Is a K8s event exporter worth the operational overhead, or is `kubectl` sufficient?
- Should DB pool health be a periodic event or only emitted on failures?
- What's the right memory limit for production — is 512Mi sufficient under load testing?
