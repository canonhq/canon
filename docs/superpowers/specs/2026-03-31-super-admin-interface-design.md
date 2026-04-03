# Super Admin Interface

Platform-level administration interface for Canon, providing cross-org visibility and management for the Canon team (cloud) and instance-level administration for self-hosted deployers.

## Background

Canon has org-scoped admin features (settings, analytics, integrations) at `/app/{org}/settings` and a basic indexing admin page at `/app/admin/indexing`. There is no unified platform-level admin interface for the Canon team to see across all organizations, manage users, monitor system health, or audit platform activity. Self-hosted deployers also lack a comprehensive admin view for their instance.

## Goals

- Give the Canon team full cross-org visibility into the platform (organizations, users, billing, health, integrations, audit, AI ops)
- Give self-hosted deployers the same admin experience scoped to their single instance (minus cloud-specific features)
- Build within the existing Vue 3 + FastAPI application — no separate app or deployment
- Reuse existing data stores — minimize new data collection, surface what we already have
- Follow existing codebase patterns for auth, routing, database access, and Helm deployment

## Non-Goals

- Real-time WebSocket updates (polling is sufficient for v1)
- Write operations on integrations (read-only view for v1)
- MFA enforcement for super admins (future enhancement)
- Custom role builder (fixed role hierarchy is sufficient)
- Audit log partitioning (defer to v2 if needed at scale)

---

## Architecture

### Approach: Dedicated Admin Module

New `src/canon/admin/` backend module with a `/api/admin/` route prefix, gated by a `SUPER_ADMIN` role. The Vue frontend gets a parallel `/app/admin/` section. This follows Canon's existing pattern of domain modules (`sync/`, `billing/`, `github/`).

The admin store composes existing stores (`UserStore`, `InstallationRegistry`, `AgentStore`, etc.) with cross-org query capabilities that bypass normal tenant isolation.

### Deployment Mode Feature Gating

A `DEPLOYMENT_MODE` environment variable (`cloud` | `self_hosted` | `development`) controls which features are available. The frontend fetches `GET /api/admin/config` on mount to learn the mode and conditionally renders sections.

| Capability | Cloud | Self-Hosted |
|---|---|---|
| Cross-org view | Yes (many orgs) | N/A (one org) |
| User management | All orgs | Their org |
| Billing/Stripe | Yes | Hidden |
| System health | Platform-wide | Instance-wide |
| Integrations | All orgs (read-only) | Their org (read-only) |
| Audit logs | Platform-wide | Instance-wide |
| AI operations | Cost tracking, metering | BYOK visibility |

### Three-Column Layout

1. **Icon rail** (48px) — always visible, section icons. Cloud-only sections hidden in self-hosted mode.
2. **Context panel** (~220px, collapsible) — entity list with search/filter for the active section. Collapses on dashboard overview.
3. **Detail pane** (remaining width) — selected entity detail, or section overview when nothing selected.

Breadcrumb header: `Canon Admin > Section > Entity` with deployment mode badge.

---

## Role Model

### SUPER_ADMIN Role

Extend the existing role hierarchy:

```
VIEWER -> EDITOR -> ADMIN -> SUPER_ADMIN
```

- New `SUPER_ADMIN` value in the `Role` enum
- New `PLATFORM_MANAGE` permission that grants access to `/api/admin/*` routes
- `SUPER_ADMIN` inherits all `ADMIN` permissions plus `PLATFORM_MANAGE`
- In cloud: assigned to Canon team members via Auth0 roles or DB flag
- In self-hosted: the first user (instance creator) gets `SUPER_ADMIN` automatically; can grant to others

Single role, capabilities filtered by deployment mode. No need for separate `PLATFORM_ADMIN` vs `INSTANCE_ADMIN` roles — the environment determines available features, not the role.

### Middleware

New `require_super_admin` FastAPI dependency applied to all `/api/admin/*` routes. Returns 404 for unauthenticated requests (don't reveal admin routes exist), 403 for authenticated non-super-admins.

---

## Route Structure

```
/app/admin/                    -> Dashboard overview (default landing)
/app/admin/orgs                -> Organizations list + detail
/app/admin/orgs/:org           -> Org detail view
/app/admin/users               -> Users list + detail
/app/admin/users/:id           -> User detail view
/app/admin/billing             -> Subscriptions + usage (cloud only)
/app/admin/health              -> System health summary
/app/admin/integrations        -> Integration connections (read-only)
/app/admin/audit               -> Audit event log
/app/admin/ai                  -> AI operations + costs
```

---

## Capability Sections

### 1. Dashboard Overview (`/app/admin/`)

Full-width landing page (no context panel). Single `GET /api/admin/dashboard` endpoint.

**Top row — KPI cards:**
- Organizations (count, new this month) — or "Repositories" in self-hosted
- Active Users (count, active today)
- Specs Tracked (total, coverage %)
- System Status (operational / degraded / down)

**Middle row — two panels:**
- Recent Activity Feed — last 20 platform events, filterable by type, links to detail views
- Health Summary — traffic-light grid for subsystems (Indexing, Sync, Webhooks, Search, AI Ops)

**Bottom row — two charts:**
- Coverage Trend (line chart, 30 days) — from `coverage_snapshots` table
- AI Ops Usage (bar chart, daily) — from `ai_op_usage` table

### 2. Organizations (`/app/admin/orgs`)

**Context panel:** Org list with status badges (active/trial/suspended). Search, sort by activity/created/users.

**Detail pane:**
- Header: org name, plan, created date, GitHub installation status
- Stats: users, repos, specs, coverage %, AI ops this month
- Repos tab: connected repos, last indexed, spec count
- Activity tab: recent events scoped to org
- Actions: trigger reindex, navigate to org view (`/app/{org}/`), suspend/reactivate (cloud only)

**Endpoints:** `GET /api/admin/orgs`, `GET /api/admin/orgs/{org}`, `POST /api/admin/orgs/{org}/reindex`

**Data sources:** `gh_installations`, `users`, `coverage_snapshots`

### 3. Users (`/app/admin/users`)

**Context panel:** All users (cross-org in cloud, single org in self-hosted). Search by name/email, filter by role/org/last active.

**Detail pane:**
- Header: avatar, name, email, Auth0 subject ID
- Info: org, role, last login, created date
- API Keys tab: user's keys with last used, expiry, scopes (read-only)
- Activity tab: recent actions from audit log
- Actions: change role, deactivate, impersonate (cloud only — creates 30-min session, logged in audit)

**Endpoints:** `GET /api/admin/users`, `GET /api/admin/users/{id}`, `PATCH /api/admin/users/{id}`, `POST /api/admin/users/{id}/impersonate`

**Data sources:** `users`, `api_keys`, `audit_events`

**Impersonation safety:** Time-limited session (30 min), `impersonated_by` field on session, all actions tagged in audit log, banner shows "Impersonating {user}" with exit button.

### 4. Billing (`/app/admin/billing`) — Cloud Only

**Context panel:** Subscription list. Filter by plan (Starter/Pro/Enterprise), status (active/past due/cancelled).

**Detail pane:**
- Subscription: org, plan, billing cycle, seat count, MRR
- Usage: AI ops used vs included, overage
- Stripe link: direct link to Stripe customer dashboard
- Invoice history from Stripe API

**Endpoints:** `GET /api/admin/billing`, `GET /api/admin/billing/{org}`

**Data sources:** `subscriptions`, `ai_op_usage`, Stripe API

Hidden entirely in self-hosted mode via feature gate.

### 5. System Health (`/app/admin/health`)

**Context panel:** Subsystem list with traffic-light status badges.

**Subsystem detail panes:**
- **Indexing** — active/queued/failed jobs, per-repo status, last run. From `index_jobs`.
- **Sync Engine** — recent sync ops, success/failure counts, stale tickets. From `sync_state`.
- **Webhooks** — delivery log, processing time, failures.
- **Search** — index size, last reindex, query latency.
- **AI Ops** — model usage breakdown, error rate, avg latency.
- **Cron Jobs** — scheduled jobs, last run status, next scheduled.

**Endpoints:** `GET /api/admin/health`, `GET /api/admin/health/{subsystem}`

### 6. Integrations (`/app/admin/integrations`) — Read Only

**Context panel:** All integrations across orgs. Filter by type (Jira/Linear/GitHub/Asana), status (connected/expired/error).

**Detail pane:**
- Integration details: org, type, connected by, connected date
- Connection status: token expiry, last successful API call
- Error log: recent failures

**Endpoints:** `GET /api/admin/integrations`

**Data sources:** `integrations`, `user_connections`

No write actions in v1.

### 7. Audit Log (`/app/admin/audit`)

**Context panel:** Replaced with filters bar (date range, event type, actor, org).

**Detail pane:** Scrolling event table — timestamp, actor, org, event type, detail, IP. Click row to expand full JSON.

**Event types:** user login, role change, impersonation start/end, spec status change, reindex trigger, integration connect/disconnect, API key create/revoke, setting change, sync operation.

**Endpoints:** `GET /api/admin/audit` (paginated, filterable)

**New table required:** `audit_events` (see Database Changes below).

**Instrumentation:** All admin write endpoints emit audit events via a consistent pattern.

### 8. AI Operations (`/app/admin/ai`)

**Context panel:** Org list sorted by AI usage, ops count and cost per org.

**Detail pane:**
- Usage chart: daily ops over 30 days (per org or aggregate)
- Model breakdown: models used, token counts, estimated cost
- Error log: failed AI calls
- Plan limits: ops included vs used, overage (cloud only)

**Endpoints:** `GET /api/admin/ai`, `GET /api/admin/ai/{org}`

**Data sources:** `ai_op_usage`

Self-hosted: no plan limits, shows raw usage and BYOK status.

---

## Database Changes

### New Table: `audit_events`

New Alembic migration following existing pattern.

```sql
CREATE TABLE audit_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id        BIGINT REFERENCES users(id),
    org             TEXT,
    event_type      TEXT NOT NULL,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT NOT NULL,
    detail          JSONB,
    ip_address      INET
);

CREATE INDEX idx_audit_org_time ON audit_events (org, created_at DESC);
CREATE INDEX idx_audit_actor ON audit_events (actor_id);
CREATE INDEX idx_audit_resource ON audit_events (resource_type, resource_id);
CREATE INDEX idx_audit_event_type ON audit_events (event_type);
```

No other tables need modification. All other data (orgs, users, billing, health, integrations, AI ops) is read from existing tables.

---

## Backend Module Structure

```
src/canon/admin/
  __init__.py
  routes.py          # FastAPI router, all /api/admin/* endpoints
  middleware.py       # require_super_admin dependency
  models.py           # Admin-specific Pydantic response models
  store.py            # Cross-org query layer (composes existing stores)
  config.py           # Deployment mode detection, feature gates
  audit.py            # AuditStore for audit_events table
```

### Middleware Pattern

```python
async def require_super_admin(request: Request) -> CurrentUser:
    user = get_current_user(request)
    if user is None:
        raise HTTPException(404)  # Don't reveal admin routes
    if user.role != Role.SUPER_ADMIN:
        raise HTTPException(403, "Insufficient permissions")
    return user
```

### Audit Instrumentation Pattern

```python
async def change_user_role(user_id, new_role, current_user, audit_store):
    old_role = await user_store.get_role(user_id)
    await user_store.update_role(user_id, new_role)
    await audit_store.log(
        actor=current_user,
        event_type="user.role_changed",
        resource_type="user",
        resource_id=str(user_id),
        detail={"old_role": old_role, "new_role": new_role},
    )
```

### Admin Config Endpoint

```python
@router.get("/api/admin/config")
async def get_admin_config(settings: Settings):
    return {
        "mode": settings.deployment_mode,
        "features": {
            "billing": settings.deployment_mode == "cloud",
            "cross_org": settings.deployment_mode == "cloud",
            "impersonation": settings.deployment_mode == "cloud",
        },
    }
```

---

## Frontend Structure

### Vue Views

```
frontend/src/views/admin/
  AdminLayout.vue           # Three-column shell
  AdminDashboard.vue        # Landing overview
  AdminOrgs.vue             # Organizations section
  AdminOrgDetail.vue        # Org detail pane
  AdminUsers.vue            # Users section
  AdminUserDetail.vue       # User detail pane
  AdminBilling.vue          # Billing (cloud only)
  AdminHealth.vue           # System health
  AdminHealthDetail.vue     # Subsystem detail
  AdminIntegrations.vue     # Integrations read view
  AdminAudit.vue            # Audit log + filters
  AdminAI.vue               # AI operations
```

### Shared Components

```
frontend/src/components/admin/
  IconRail.vue              # Section icon navigation
  ContextPanel.vue          # Entity list with search/filter
  KPICard.vue               # Stat card (reusable)
  StatusBadge.vue           # Traffic light indicator
  ActivityFeed.vue          # Event stream component
  AuditTable.vue            # Filterable event table
```

### State Management

Pinia store (`frontend/src/stores/admin.ts`) holding:
- Active section and selected entity
- Admin config (deployment mode, feature flags)
- Filter state per section

### Code Splitting

All admin views lazy-loaded via dynamic imports. Admin code is never included in the regular user bundle.

### Route Guard

Vue Router `beforeEach` checks user role before allowing `/app/admin/*`. Non-super-admins redirected to their org dashboard.

### Feature Gating

On `AdminLayout` mount, fetch `GET /api/admin/config`. Store in Pinia. Components use `v-if="features.billing"` to conditionally render cloud-only sections. Icon rail hides cloud-only icons in self-hosted mode.

### Polling

30-second interval for dashboard overview, 60 seconds for detail views. Follows existing frontend polling patterns. No WebSocket for v1.

---

## Infrastructure Changes

### Settings (`src/canon/settings.py`)

New environment variables:
- `DEPLOYMENT_MODE`: `cloud` | `self_hosted` | `development` (default: `development`)
- `ADMIN_AUDIT_RETENTION_DAYS`: integer (default: 90)

### Helm Chart

**ConfigMap additions** (`values.yaml`):
```yaml
config:
  deploymentMode: "development"
  adminAuditRetentionDays: "90"
```

**Production override** (`values-production.yaml`):
```yaml
config:
  deploymentMode: "cloud"
  adminAuditRetentionDays: "180"
```

**New CronJob** — audit log retention:
- Template: `chart/canon/templates/cronjob-audit-retention.yaml`
- Schedule: daily 3am UTC
- Entry: `python -m canon.cron.audit_retention`
- Deletes audit events older than `ADMIN_AUDIT_RETENTION_DAYS`
- Optional, gated by `auditRetentionCronJob.enabled` in values

No new secrets needed. No Terraform changes (infra is in `gv-infra` repo). No new K8s resources beyond the CronJob.

### CI/CD

No workflow changes needed. The existing `deploy.yml` pipeline (lint, test, Docker build, Helm upgrade) handles the new module automatically.

---

## Error Handling

- Admin API errors return `{ "error": string, "detail": string }` structured JSON
- Frontend: toast notifications for action failures, inline error states for data loading failures
- Admin endpoints that don't apply to the current deployment mode return 404 (not 403)

## Security Considerations

- Admin routes return 404 to unauthenticated users (don't reveal routes exist)
- Impersonation creates time-limited session (30 min) with full audit trail
- All admin write actions logged to `audit_events`
- Existing rate limiting middleware applies to admin routes
- Future: MFA enforcement for SUPER_ADMIN role (not in v1)
- Future: IP allowlist for admin panel in self-hosted (not in v1)

## Testing

- Unit tests for admin middleware (role enforcement, 404 vs 403 behavior)
- Unit tests for admin store (cross-org queries, feature gating)
- Unit tests for audit logging (event emission, retention)
- Vue component tests for feature gating (cloud vs self-hosted rendering)
- Integration tests for admin API endpoints (auth, pagination, filters)
