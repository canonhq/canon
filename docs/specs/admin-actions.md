---
title: "Admin Actions: Impersonation, User Deactivation, Org Suspension"
type: spec
status: planned
owner: ng
team: canon
review_status: draft
tags: [admin, security, platform]
depends_on: []
created: "2026-04-03"
updated: "2026-04-03"
---

# Admin Actions: Impersonation, User Deactivation, Org Suspension

## 1. Background

The super admin interface (PR #485) provides read visibility into the Canon platform — orgs, users, billing, health, integrations, audit logs, and AI ops. This spec adds the missing write operations: view-only user impersonation for debugging, user deactivation with immediate session/key revocation, and org suspension with full webhook/sync freeze.

All three features are restricted to the `SUPER_ADMIN` role, logged in the audit trail, and reversible. This is part A of a three-part admin enhancement series (B: Monitoring & Audit, C: Asset Management).

## 2. Requirements

### 2.1 User Impersonation (View-Only)
<!-- canon:section:impersonation status:todo -->

A SUPER_ADMIN can view the app as any non-admin user for debugging purposes. Impersonation is read-only — all write operations are blocked during the session.

#### Acceptance Criteria

- [ ] `POST /api/admin/users/{id}/impersonate` starts a 30-minute read-only impersonation session
- [ ] `POST /api/admin/impersonate/stop` ends impersonation and redirects to admin
- [ ] Auth middleware resolves requests as the target user during impersonation (correct org context, tenant isolation)
- [ ] All non-GET requests to non-admin routes return 403 during impersonation
- [ ] Impersonation auto-expires after 30 minutes and cannot be extended
- [ ] Cannot impersonate another SUPER_ADMIN (returns 400)
- [ ] Cannot impersonate a deactivated user (returns 400)
- [ ] Cloud mode only — returns 404 in self-hosted mode
- [ ] Audit events logged for impersonation start and stop with admin identity
- [ ] Persistent amber warning banner shown across all pages during impersonation with countdown timer and exit button
- [ ] "View as User" button on AdminUserDetail.vue, disabled for SUPER_ADMIN and deactivated users

### 2.2 User Deactivation
<!-- canon:section:user-deactivation status:todo -->

A SUPER_ADMIN can deactivate a user, immediately revoking all sessions and API keys. Reactivation restores login but does not restore revoked keys.

#### Acceptance Criteria

- [ ] New `status` column on `users` table (values: `active`, `deactivated`, default: `active`) via Alembic migration
- [ ] `POST /api/admin/users/{id}/deactivate` sets status, deletes all sessions, revokes all API keys
- [ ] `POST /api/admin/users/{id}/reactivate` sets status back to `active` (does NOT restore revoked API keys)
- [ ] Deactivated users cannot log in — web requests redirect to `/deactivated`, API requests return 403
- [ ] Cannot deactivate yourself (returns 400)
- [ ] Cannot deactivate another SUPER_ADMIN (returns 400)
- [ ] Audit events logged for deactivation and reactivation with counts of revoked sessions/keys
- [ ] "Deactivate" button (red, with confirmation dialog) on AdminUserDetail.vue when active
- [ ] "Reactivate" button (green) on AdminUserDetail.vue when deactivated
- [ ] Status badge (active/deactivated) shown on AdminUsers.vue list
- [ ] New `/deactivated` landing page explaining account is disabled with sign-out link

### 2.3 Org Suspend/Reactivate
<!-- canon:section:org-suspension status:todo -->

A SUPER_ADMIN can suspend an org, causing a full freeze — login blocked, webhooks rejected, sync and indexing stopped. Reactivation restores normal operation.

#### Acceptance Criteria

- [ ] `POST /api/admin/orgs/{org}/suspend` sets `gh_installations.status = 'suspended'` and clears all sessions for the org's users
- [ ] `POST /api/admin/orgs/{org}/reactivate` sets status back to `active`
- [ ] Suspended org webhooks are acknowledged (200) but not processed
- [ ] Suspended org users fail org resolution on login (existing `get_active_installation` filter handles this)
- [ ] Cron jobs (sync, stale check, coverage, reindex) skip suspended orgs (existing `WHERE status = 'active'` filter handles this)
- [ ] Audit events logged for suspension and reactivation
- [ ] "Suspend" button (red, with confirmation dialog) on AdminOrgDetail.vue when active
- [ ] "Reactivate" button (green) on AdminOrgDetail.vue when suspended
- [ ] Status badge (active/suspended) shown on AdminOrgs.vue list

## 3. Design

### Session-Based Impersonation

Impersonation state is stored in the admin's existing session as `session["impersonating"]` containing the target user's ID, sub, org_login, start time, and expiry. The auth middleware checks this state after resolving the admin's identity and swaps the request context to the target user with a `read_only` flag. A separate write-blocking middleware rejects non-GET requests when `read_only` is set. The impersonation banner is rendered by `App.vue` based on `window.__CANON__` session data.

### User Status Column

A new `status` column on the `users` table (default `'active'`) gates login at the auth middleware layer. Deactivation is a three-step atomic operation: set status, delete sessions, revoke API keys. The auth middleware checks status after resolving the user and before route handling.

### Org Suspension via Existing Status

The `gh_installations.status` column already supports `active` and `deleted`. Adding `suspended` as a value leverages existing infrastructure — registry lookups, cron job filters, and webhook handlers all already filter on `status = 'active'`. The only new code needed is the webhook early-return guard for explicit `suspended` status handling.

### Shared Patterns

All three features follow the same pattern:
- SUPER_ADMIN-only endpoint with safety constraints (no self-action, no mutual admin lockout)
- Immediate effect (sessions cleared, status changed)
- Audit event with action detail
- Frontend confirmation dialog before destructive action
- Reversible (reactivate/stop)

## 4. Rollout Plan

### Phase 1: User Deactivation
Simplest feature — new column, two endpoints, status badge. Low risk, high value for user management.

### Phase 2: Org Suspension
Leverages existing status infrastructure. Medium complexity due to webhook guard and session clearing.

### Phase 3: Impersonation
Most complex — auth middleware changes, write blocking, session state management, frontend banner. Highest testing burden.

### Success Criteria
- All three actions visible in audit log with correct actor/target
- Deactivated user confirmed unable to log in or use API keys
- Suspended org confirmed: webhooks rejected, cron jobs skipped, login blocked
- Impersonation confirmed: view-only, auto-expires, write operations blocked
