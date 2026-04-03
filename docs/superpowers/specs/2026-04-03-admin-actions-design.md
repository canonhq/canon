# Admin Actions: Impersonation, User Deactivation, Org Suspension

Write operations for the super admin interface — view-only impersonation, user lifecycle management, and org suspension with full freeze.

## Background

The super admin interface (PR #485) provides read visibility into the Canon platform. This spec adds the missing write operations: impersonating users for debugging, deactivating users with session/key revocation, and suspending orgs with full webhook/sync freeze.

All three features are restricted to SUPER_ADMIN role and logged in the audit trail.

## Goals

- Let admins debug user-reported issues by viewing the app as that user (read-only)
- Let admins disable users immediately with full session and API key revocation
- Let admins freeze entire orgs — block login, reject webhooks, stop sync/indexing
- Every action is audited, reversible, and cannot cause admin lockout

## Non-Goals

- Write-access impersonation (view-only only)
- Multi-admin approval workflows (single SUPER_ADMIN is sufficient)
- Self-hosted impersonation (admin already has full visibility in single-org mode)
- Automatic suspension triggers (e.g., billing overdue — future enhancement)

---

## 1. User Impersonation (View-Only)

### Behavior

A SUPER_ADMIN clicks "View as User" on a user's detail page. The backend stores impersonation state in the admin's session. While impersonating, the auth layer resolves requests as the target user but blocks all write operations.

### Backend

**New endpoints:**
- `POST /api/admin/users/{id}/impersonate` — starts impersonation
- `POST /api/admin/impersonate/stop` — ends impersonation

**Session state:** When impersonation starts, the admin's session gains:
```python
session["impersonating"] = {
    "user_id": target_user.id,
    "user_sub": target_user.oidc_sub,
    "org_login": target_user_org_login,
    "started_at": now_iso,
    "expires_at": (now + 30min)_iso,
}
```

**Auth middleware changes:** In `AuthMiddleware.dispatch`, after resolving the session user, check for `session["impersonating"]`:
1. If present and not expired, resolve the request as the target user (swap `org_login` for tenant isolation)
2. Set a `read_only` flag on the request state
3. If expired, clear the impersonation state and continue as the admin

**Write blocking:** A new middleware or dependency checks `request.state.read_only`. Any non-GET request to non-admin routes returns `403 "Read-only impersonation session"`.

**Audit events:**
- `admin.impersonation_started` — actor: admin, resource: target user, detail: `{target_email, org_login}`
- `admin.impersonation_stopped` — actor: admin, resource: target user
- All requests during impersonation include `impersonated_by: admin_sub` in the request context (not as separate audit events — too noisy)

**Constraints:**
- Cloud mode only (gated by `deployment_mode == "cloud"`)
- 30-minute expiry, not extendable (must re-impersonate)
- Cannot impersonate another SUPER_ADMIN
- Cannot impersonate a deactivated user

### Frontend

**AdminUserDetail.vue:**
- "View as User" button — calls `POST /api/admin/users/{id}/impersonate`, then redirects to `/app/{org}/`
- Disabled for SUPER_ADMIN users and deactivated users

**Impersonation banner:** A persistent warning bar across every page during impersonation:
```
Viewing as nick@example.com (canonhq) — 24:32 remaining — [Exit]
```
- Styled as a warning bar (amber background, dark text)
- Countdown timer from 30 minutes
- "Exit" button calls `POST /api/admin/impersonate/stop` and redirects to `/app/admin/users/{id}`

**Implementation:** The banner is rendered in `App.vue` (or a layout-level component) when `session.impersonating` is present. The session state is available via the `window.__CANON__` server-injected data.

---

## 2. User Deactivation

### Behavior

A SUPER_ADMIN clicks "Deactivate" on a user's detail page. The user is immediately locked out — all sessions destroyed, all API keys revoked. Reversible via "Reactivate" (but revoked API keys are not restored).

### Database Change

New Alembic migration — add `status` column to `users` table:
```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
CREATE INDEX IF NOT EXISTS idx_users_status ON users (status);
```

Valid values: `active`, `deactivated`.

### Backend

**New endpoints:**
- `POST /api/admin/users/{id}/deactivate` — sets status, revokes sessions + keys
- `POST /api/admin/users/{id}/reactivate` — sets status back to active

**Deactivation logic:**
1. Set `users.status = 'deactivated'` for the target user
2. Delete all rows from `sessions` where `user_db_id = target_id`
3. Set `revoked_at = now()` on all `api_keys` where `user_id = target_id`
4. Log audit event `user.deactivated` with detail `{email, revoked_sessions_count, revoked_keys_count}`

**Reactivation logic:**
1. Set `users.status = 'active'`
2. Log audit event `user.reactivated`
3. API keys are NOT restored — user creates new ones after reactivation

**Auth middleware changes:** After resolving the user from session/JWT/API key, check the user's `status` in the database. If `deactivated`:
- Web requests: redirect to `/deactivated` (a simple page explaining the account is disabled)
- API requests: return `403 {"detail": "Account deactivated"}`

**Safety constraints:**
- Cannot deactivate yourself (400 "Cannot deactivate your own account")
- Cannot deactivate another SUPER_ADMIN (400 "Cannot deactivate a super admin")

### Frontend

**AdminUserDetail.vue:**
- "Deactivate" button (red) when `status == 'active'` — opens confirmation dialog
- "Reactivate" button (green) when `status == 'deactivated'`
- Confirmation dialog: "Deactivate {email}? This will revoke all active sessions and API keys immediately."

**AdminUsers.vue:**
- Status badge next to each user: `active` (green) / `deactivated` (red)

**Deactivated landing page:**
- New simple page at `/deactivated` — "Your account has been deactivated. Contact your administrator."
- Includes a "Sign out" link

---

## 3. Org Suspend/Reactivate

### Behavior

A SUPER_ADMIN clicks "Suspend" on an org's detail page. Full freeze: users can't log in, webhooks are rejected, sync and indexing stop. Reversible via "Reactivate".

### Database Change

No schema change needed. `gh_installations.status` already exists with values `active` and `deleted`. We add `suspended` as a new valid value.

### Backend

**New endpoints:**
- `POST /api/admin/orgs/{org}/suspend` — sets status to `suspended`, clears sessions
- `POST /api/admin/orgs/{org}/reactivate` — sets status back to `active`

**Suspension logic:**
1. Set `gh_installations.status = 'suspended'` for the org
2. Delete all sessions for users whose resolved org matches this org
3. Log audit event `org.suspended`

**Reactivation logic:**
1. Set `gh_installations.status = 'active'`
2. Log audit event `org.reactivated`

**Webhook rejection:** In the GitHub webhook handlers (push, pull_request, installation, issues), after looking up the installation, check status. If `suspended`, return 200 immediately without processing. This is a single guard added to the common handler entry point.

**Login blocking:** The auth callback resolves the user's org via `registry.get_active_installation()` which already filters `WHERE status = 'active'`. A suspended org naturally fails org resolution, and the user is redirected to the no-org page. No code change needed for this path.

**Cron job exclusion:** Existing cron jobs (sync_status, coverage_snapshot, stale_check, reindex) already query `gh_installations WHERE status = 'active'`. Suspended orgs are automatically excluded.

### Frontend

**AdminOrgDetail.vue:**
- "Suspend" button (red) when `status == 'active'` — opens confirmation dialog
- "Reactivate" button (green) when `status == 'suspended'`
- Confirmation dialog: "Suspend {org}? All users will be logged out. Webhooks, sync, and indexing will stop immediately."

**AdminOrgs.vue:**
- Status badge: `active` (green), `suspended` (red)

---

## Testing

### Impersonation
- Start impersonation returns session state and audit event
- Auth middleware resolves as target user during impersonation
- Write requests blocked with 403 during impersonation
- Expired impersonation auto-clears
- Cannot impersonate SUPER_ADMIN or deactivated user
- Stop impersonation clears session and logs audit

### User Deactivation
- Deactivate sets status, revokes sessions and API keys
- Deactivated user cannot log in (web redirect, API 403)
- Reactivate restores login but not API keys
- Cannot deactivate self or another SUPER_ADMIN

### Org Suspension
- Suspend sets status, clears org sessions
- Suspended org webhooks return 200 but don't process
- Suspended org users fail org resolution on login
- Cron jobs skip suspended orgs
- Reactivate restores normal operation

---

## Security Considerations

- All actions require SUPER_ADMIN role
- All actions logged in `audit_events` with admin identity
- Impersonation is read-only — no write escalation possible
- Deactivation immediately revokes all access tokens
- Org suspension immediately stops all automated processing
- Self-deactivation and mutual SUPER_ADMIN deactivation are blocked
