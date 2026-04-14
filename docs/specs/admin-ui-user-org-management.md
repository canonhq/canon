---
title: "Admin UI: User & Organization Management"
status: in-progress
owner: ng
team: canon
ticket_project: canonhq/canon-private
review_status: draft
tags: [admin, ui, auth0, platform, cloud]
depends_on: [admin-actions, multi-org-personal-accounts, infra-enablement-billing-email]
created: "2026-04-11"
updated: "2026-04-14"
---

# Admin UI: User & Organization Management

Expand the super-admin UI (PR #485 baseline) from a mostly-read surface into a
complete day-two management console for users and organizations. Absorbs the
impersonation work from `admin-actions.md` and fills the remaining CRUD gaps
that currently force support to drop into `psql` or the Auth0 dashboard.

## 1. Background

<!-- canon:system:1 status:done -->

The super-admin UI currently supports a limited set of write operations:

- **Orgs**: `list`, `get` (with Auth0 members), `reindex`, `suspend`, `reactivate`
- **Users**: `list`, `get` (with Auth0 enrichment), `update_role`, `deactivate`, `reactivate`

Anything beyond that — fixing a failed Auth0 provisioning, resending an
invitation, revoking a single API key without nuking the whole account,
editing an org display name, or honoring a GDPR delete — requires a backend
engineer with database and Auth0 Management API access. That is the wrong
escalation path for routine cloud support work, and it blocks Canon from being
operated by non-engineers.

The **`admin-actions.md`** spec already covers impersonation, user
deactivation, and org suspension. Deactivation and suspension have shipped.
This spec supersedes the impersonation portion of `admin-actions.md` and
extends it with the full CRUD set. `admin-actions.md` should be marked
`superseded-by: admin-ui-user-org-management` once this lands.

**Current Auth0 provider surface** (`src/canon/auth/providers/auth0.py`):
`get_user`, `list_users`, `list_organizations`, `get_org_members`,
`get_user_orgs`, `get_organization_by_name`, `create_organization`,
`enable_org_connections`, `disable_org_connections`,
`get_connection_by_name`. Missing from the Management API surface we need:
`update_user`, `delete_user`, `update_organization`, `delete_organization`,
`add_org_member`, `remove_org_member`, `create_invitation`,
`create_password_change_ticket`, `create_email_verification_ticket`.

## 2. P0 — Core Org & User CRUD

<!-- canon:system:2 status:done -->

The P0 set unblocks routine cloud support without requiring P1/P2 scope.
Everything in this section is `SUPER_ADMIN`-only, gated by the existing
`require_super_admin` dependency, logs an audit event on success, and follows
the confirm-before-destructive pattern already used by suspend/deactivate.

### 2.1 Org Metadata Edit
<!-- canon:section:org-metadata-edit status:done -->

The current `AdminOrgDetail.vue` shows `display_name` pulled from Auth0 but
provides no way to fix it when it drifts or was never set. Add an edit flow
that updates both Auth0 (`PATCH /api/v2/organizations/{id}`) and any Canon-side
metadata we add (a local `notes` field for support handoff, primary contact
email/name).

#### Acceptance Criteria

- [ ] New `organizations_meta` table keyed by `org_login` with columns
      `primary_contact_email`, `primary_contact_name`, `support_notes`,
      `updated_at`, `updated_by_sub` (Alembic migration)
- [ ] `PATCH /api/admin/orgs/{org}` accepts `display_name`, `primary_contact_email`,
      `primary_contact_name`, `support_notes`; routes `display_name` to Auth0
      via a new `Auth0Provider.update_organization` method and the rest to
      `organizations_meta`
- [ ] `AdminOrgDetail.vue` renders current metadata in the existing detail panel
      and exposes an "Edit details" button that opens an inline form
- [ ] Edit form validates email format and caps `support_notes` at 2000 chars
- [ ] Auth0 display_name cache (`auth0:orgs`) is invalidated after a successful
      edit so the change is visible on the list view within the next request
- [ ] Audit event `org.metadata_updated` logs a field-level diff with
      `{field: {old, new}}` and redacts nothing (admin trail)
- [ ] Edit button is disabled for suspended orgs with a tooltip explaining why

### 2.2 Auth0 Provisioning Repair
<!-- canon:section:auth0-provisioning-repair status:done -->

`multi-org-personal-accounts.md` §2 describes the failure mode where an
installation is registered but `_provision_auth0_org` failed, leaving
`oidc_org_id` unset. Today the only recovery is a manual `psql` update plus a
one-off Auth0 API call. Expose a "Repair Auth0 provisioning" action on
`AdminOrgDetail.vue` that re-runs the idempotent provisioning path.

#### Acceptance Criteria

- [ ] `POST /api/admin/orgs/{org}/repair-auth0` re-runs `_provision_auth0_org`
      with the original installation payload (looked up from
      `gh_installations`) and writes `oidc_org_id` on success
- [ ] Endpoint is idempotent: calling it on an org that already has a valid
      `oidc_org_id` returns 200 with `{status: "already_provisioned"}` and
      logs no audit event
- [ ] On failure returns 422 with the Auth0 error detail; a partial repair
      (org created but `enable_org_connections` failed) logs
      `org.auth0_partial_repair` so the next attempt can pick up where it
      left off
- [ ] `AdminOrgDetail.vue` shows a "Repair Auth0 provisioning" button in the
      Actions panel only when `oidc_org_id` is null or empty
- [ ] Audit event `org.auth0_repair` logs the repaired `oidc_org_id` and the
      actor sub
- [ ] Cloud mode only — returns 404 in self-hosted mode
- [ ] Integration test verifies a synthetic install payload with a
      provisioning failure followed by a repair succeeds and sets
      `oidc_org_id`

### 2.3 User Invitation & Password Reset Tickets
<!-- canon:section:user-tickets status:done -->

Support most frequently asks: "please resend the invite" and "this user can't
reset their password." Both are one-API-call operations against the Auth0
Management API that today require a backend engineer.

#### Acceptance Criteria

- [ ] `POST /api/admin/users/{id}/resend-invite` calls
      `Auth0Provider.create_invitation` against the user's current
      `oidc_org_id` and returns the invitation URL
- [ ] `POST /api/admin/users/{id}/password-reset` calls
      `Auth0Provider.create_password_change_ticket` and returns the ticket URL
      with a TTL of 24h
- [ ] Both endpoints return 400 if the user has no `oidc_sub` (i.e. has never
      logged in) — the invite path is different for pre-provisioned users
- [ ] Both endpoints return 400 for deactivated users
- [ ] `AdminUserDetail.vue` "Account Actions" panel exposes "Resend invite" and
      "Send password reset" buttons with toast notifications on success showing
      the generated link with a copy-to-clipboard helper
- [ ] Generated URLs are never logged server-side (only the fact that a
      ticket was generated); audit events log `user.invite_sent` and
      `user.password_reset_sent` with no URL in the detail payload
- [ ] Cloud mode only — returns 404 in self-hosted mode

### 2.4 Per-User Session & API Key Management
<!-- canon:section:user-sessions-keys status:done -->

`deactivate_user` nukes every session and API key atomically. Sometimes we
need a finer knife — revoke one leaked API key, sign out one stolen session
— without forcing a full reactivate afterward. The `session_store` and
`user_store` already expose per-row lookups and deletes; expose them.

#### Acceptance Criteria

- [ ] `GET /api/admin/users/{id}/sessions` returns active sessions with
      `id`, `created_at`, `last_seen_at`, `ip_address`, `user_agent`
- [ ] `GET /api/admin/users/{id}/api-keys` returns active API keys with
      `id`, `name`, `prefix`, `created_at`, `last_used_at` (never the secret)
- [ ] `DELETE /api/admin/users/{id}/sessions/{session_id}` revokes a single
      session
- [ ] `DELETE /api/admin/users/{id}/api-keys/{key_id}` revokes a single
      API key
- [ ] `AdminUserDetail.vue` renders a "Sessions" and an "API Keys" panel, each
      listing rows with an inline revoke button
- [ ] Audit events `user.session_revoked` and `user.api_key_revoked` log the
      row id and metadata; the user's own sub is never logged in the detail
- [ ] Panel rows show a relative-time "last active" column
- [ ] Cannot revoke the admin's own current session (returns 400)

### 2.5 GDPR User Delete
<!-- canon:section:user-gdpr-delete status:done -->

Hard-delete that removes the user from Canon's database **and** Auth0.
Non-reversible, typed-confirmation gated, audit-logged with the full user
snapshot taken *before* the delete so we can answer "why was this user
deleted" in the audit trail even after the row is gone.

#### Acceptance Criteria

- [ ] `DELETE /api/admin/users/{id}` removes the user from Canon and from
      Auth0 (`Auth0Provider.delete_user`), atomically: if Auth0 deletion fails
      the DB delete rolls back
- [ ] Endpoint requires a `confirm` body field equal to the user's login /
      email; otherwise returns 400
- [ ] Cannot delete yourself (400) or another `super_admin` (400)
- [ ] All sessions, API keys, audit actor references, and realization rows
      authored by the user are handled: sessions/keys are hard-deleted,
      audit actor references become `actor_id = null` with
      `actor_sub_snapshot` preserving the prior identity
- [ ] Audit event `user.deleted` logs the full pre-delete `UserSummary` in the
      detail payload (including email, login, oidc_sub, role, org_login,
      created_at) so the deletion reason can be reconstructed
- [ ] `AdminUserDetail.vue` exposes a "Delete user" button in a separate
      red-bordered "Danger Zone" section with a typed-confirmation dialog
- [ ] Cloud mode only — returns 404 in self-hosted mode
- [ ] Integration test covers: delete succeeds, delete with wrong confirm
      fails, delete of self fails, delete of super_admin fails, delete when
      Auth0 is unreachable rolls back the DB change

## 3. P1 — Membership, Profile, Impersonation

<!-- canon:system:3 status:in-progress -->

### 3.1 Org Member Add / Remove (Auth0)
<!-- canon:section:org-membership status:done -->

Expose Auth0 organization membership management so sales-assisted onboarding
can add a customer's founders to an org without the customer running through
the signup flow. This is **Auth0 org membership**, not Canon's `users.role`
column — the two are independent layers and this spec keeps them that way.

#### Acceptance Criteria

- [ ] New `Auth0Provider.add_org_member(org_id, user_id)` and
      `remove_org_member(org_id, user_id)` methods (Management API
      `POST/DELETE /organizations/{id}/members`)
- [ ] `POST /api/admin/orgs/{org}/members` accepts either `{user_id}` (an
      existing Auth0 user) or `{email}` (look up or create-then-invite)
- [ ] `DELETE /api/admin/orgs/{org}/members/{user_id}` removes a member
- [ ] Removing a member also clears any Canon session scoped to
      `(user_id, org_login)` so the removal is immediate
- [ ] Cannot remove the last member if the org has active subscriptions
      (returns 400)
- [ ] `AdminOrgDetail.vue` "Auth0 Members" section gains an "Add member"
      button (opens a modal with email lookup) and a per-row "Remove" button
      with a confirmation dialog
- [ ] Adding a member invalidates the `auth0:org_members:{oidc_org_id}` cache
- [ ] Audit events `org.member_added` and `org.member_removed` with the
      target user_id, email, and actor sub

### 3.2 User Profile Edit (Auth0 Management)
<!-- canon:section:user-profile-edit status:todo -->

Support commonly asks to fix a typo in a name or update an email after
corporate rebrand. Both go through the Auth0 Management API `PATCH /users/{id}`
endpoint. Canon's local `users` table mirrors `name` and `email` so both
stores need to update atomically.

#### Acceptance Criteria

- [ ] New `Auth0Provider.update_user(user_id, **fields)` method
      (Management API `PATCH /api/v2/users/{id}`)
- [ ] `PATCH /api/admin/users/{id}` accepts `name`, `email`, and `picture`;
      updates Auth0 first then mirrors to the Canon `users` table
- [ ] Email changes trigger a verification ticket (reusing §2.3) and the user
      is flagged `email_verified: false` until they confirm — the endpoint
      returns the new verification URL in the response
- [ ] Cannot edit another super_admin's profile (returns 400)
- [ ] `AdminUserDetail.vue` profile fields become inline-editable with a save
      button; the form shows the current Auth0 values and a diff hint
- [ ] Auth0 user cache `auth0:users:{sub}` is invalidated on success
- [ ] Audit event `user.profile_updated` logs the field-level diff

### 3.3 Impersonation (Absorbed from admin-actions.md)
<!-- canon:section:impersonation status:todo -->

A `SUPER_ADMIN` can view the app as any non-admin user for debugging purposes.
Impersonation is read-only — all write operations are blocked during the
session. **Absorbed verbatim from `admin-actions.md` §2.1**; that section
should be marked `superseded-by: admin-ui-user-org-management#impersonation`
when this spec advances past draft.

#### Acceptance Criteria

- [ ] `POST /api/admin/users/{id}/impersonate` starts a 30-minute read-only
      impersonation session
- [ ] `POST /api/admin/impersonate/stop` ends impersonation and redirects to
      admin
- [ ] Auth middleware resolves requests as the target user during
      impersonation (correct org context, tenant isolation)
- [ ] All non-GET requests to non-admin routes return 403 during impersonation
- [ ] Impersonation auto-expires after 30 minutes and cannot be extended
- [ ] Cannot impersonate another `SUPER_ADMIN` (returns 400)
- [ ] Cannot impersonate a deactivated user (returns 400)
- [ ] Cloud mode only — returns 404 in self-hosted mode
- [ ] Audit events `user.impersonate_started` and `user.impersonate_stopped`
      logged with admin identity and target user
- [ ] Persistent amber warning banner shown across all pages during
      impersonation with countdown timer and exit button
- [ ] "View as User" button on `AdminUserDetail.vue`, disabled for
      `SUPER_ADMIN` and deactivated users
- [ ] Impersonation session does not grant access to
      `/api/admin/*` routes (admin always resolves as the real admin there)

## 4. P2 — Bulk, Lifecycle, Compliance

<!-- canon:system:4 status:todo -->

Lower-frequency, higher-blast-radius, or dependent on other in-flight work.
Specified here so we have a clear place to land them without re-opening the
spec.

### 4.1 Org Create / Archive / Delete
<!-- canon:section:org-lifecycle status:todo -->

Create an org from the admin UI for sales-assisted onboarding. Archive a
long-idle org (soft — preserves audit history, blocks all writes, hides from
default list views). Hard delete for GDPR (cloud only, typed-confirmation).

#### Acceptance Criteria

- [ ] `POST /api/admin/orgs` creates a Canon org + Auth0 org + empty
      `gh_installations` row with status `pending_install`
- [ ] `POST /api/admin/orgs/{org}/archive` sets `gh_installations.status =
      'archived'` (extends the enum); archived orgs are filtered out of
      `list_orgs` unless `?include_archived=true`
- [ ] `DELETE /api/admin/orgs/{org}` hard-deletes the org, uninstalls the
      GitHub App (best-effort), deletes the Auth0 org, and removes all
      cascading data (specs, realizations, sessions for members)
- [ ] Typed-confirmation required on archive (org login) and on delete
      (org login + the string "DELETE")
- [ ] Audit events `org.created`, `org.archived`, `org.deleted`
- [ ] Cron filters (sync, stale, coverage) skip archived orgs in addition to
      the existing `status = 'active'` filter

### 4.2 Bulk Actions & CSV Export
<!-- canon:section:bulk-csv status:todo -->

#### Acceptance Criteria

- [ ] `AdminUsers.vue` and `AdminOrgs.vue` list pages gain a row checkbox and
      a bulk action bar (deactivate/reactivate, archive for orgs)
- [ ] `GET /api/admin/users.csv` and `/api/admin/orgs.csv` stream a CSV
      export of the current filter set (respects `search`, `role`, `org`)
- [ ] Bulk operations are executed in chunks of 10 with per-row audit events
      and a final summary toast showing successes and failures
- [ ] CSV includes all `UserSummary` / `OrgSummary` fields plus the Auth0
      enrichment where cached; missing enrichment is written as empty cells

### 4.3 User Lifecycle Operations
<!-- canon:section:user-lifecycle status:todo -->

Depends on `multi-org-personal-accounts` landing first, because these
operations assume a user can belong to multiple orgs.

#### Acceptance Criteria

- [ ] `POST /api/admin/users/merge` merges two users with the same email but
      different `oidc_sub` — moves sessions, API keys, audit actor references,
      and realization authorship to the kept user; deletes the losing user
- [ ] `POST /api/admin/users/{id}/move` moves a user between orgs
      (session-scoped, not DB-column since `users.org_login` does not exist —
      see `store.py` list_users note)
- [ ] `POST /api/admin/users` creates a user manually for pre-provisioning,
      optionally sending an invite in the same call
- [ ] All three operations are typed-confirmation gated and audit-logged
- [ ] Cloud mode only

## 5. Design

<!-- canon:system:5 status:draft -->

### 5.1 Backend Layering

All new endpoints live under `src/canon/admin/routes.py` and follow the
existing shape:

```
@router.<verb>("/path")
async def handler(
    ...,
    request: Request,
    user: CurrentUser = Depends(require_super_admin),
) -> dict:
    admin_store = getattr(request.app.state, "admin_store", None)
    if admin_store is None:
        raise HTTPException(status_code=503, detail="Database not available")

    existing = await admin_store.get_*(...)
    if existing is None:
        raise HTTPException(status_code=404, detail="Not found")

    # Guard rails (self-action, super_admin, deactivated, etc.)

    result = await admin_store.<operation>(...)

    # Side effects: Auth0 calls, cache invalidations, session clears

    audit_store = getattr(request.app.state, "audit_store", None)
    if audit_store is not None:
        try:
            await audit_store.log(
                event_type="...",
                resource_type="...",
                resource_id=...,
                actor_id=None,
                org=existing.get("org_login"),
                detail={..., "actor": user.sub},
                ip_address=_client_ip(request),
            )
        except Exception:
            logger.warning("Audit log failed", exc_info=True)

    return <response_model>.model_dump()
```

`AdminStore` gains CRUD methods that return the updated row so the endpoint
can build the response model without a second fetch. The Auth0 provider gains
Management API wrappers that all funnel through the existing `_get_mgmt_token`
helper.

### 5.2 Auth0 Provider Extensions

New methods on `Auth0Provider` (all thin wrappers around the Management API):

| Method | Management API endpoint | Used by |
|---|---|---|
| `update_organization(org_id, **fields)` | `PATCH /api/v2/organizations/{id}` | 2.1 |
| `update_user(user_id, **fields)` | `PATCH /api/v2/users/{id}` | 3.2 |
| `delete_user(user_id)` | `DELETE /api/v2/users/{id}` | 2.5 |
| `delete_organization(org_id)` | `DELETE /api/v2/organizations/{id}` | 4.1 |
| `add_org_member(org_id, user_id)` | `POST /api/v2/organizations/{id}/members` | 3.1 |
| `remove_org_member(org_id, user_id)` | `DELETE /api/v2/organizations/{id}/members/{user_id}` | 3.1 |
| `create_invitation(org_id, inviter, invitee_email)` | `POST /api/v2/organizations/{id}/invitations` | 2.3, 3.1 |
| `create_password_change_ticket(user_id)` | `POST /api/v2/tickets/password-change` | 2.3 |
| `create_email_verification_ticket(user_id)` | `POST /api/v2/tickets/email-verification` | 2.3, 3.2 |

Each method raises a `ProviderError` on non-2xx and leaves retry/backoff to
the caller (Canon's existing pattern). Management API rate limits are handled
by the existing cache layer plus explicit cache invalidation after mutations.

### 5.3 Session & API Key Per-Row Revocation

`session_store` already has `revoke_all_sessions(user_id)`; add
`list_sessions(user_id)` and `revoke_session(session_id)`. Same for
`user_store` API keys. The existing single-row delete paths already exist for
the user-facing session/key UI — the admin endpoints reuse them with the
`user_id` mismatch check replaced by the super_admin check.

### 5.4 Frontend Composition

The admin detail views (`AdminUserDetail.vue`, `AdminOrgDetail.vue`) already
use a panel-stack layout. Each new feature lands as its own panel component
under `frontend/src/components/admin/`:

```
components/admin/
  AdminStatusBadge.vue         (exists)
  KPICard.vue                  (exists)
  IndexingDashboard.vue        (exists)
  OrgMetadataPanel.vue         (new — 2.1)
  OrgActionsPanel.vue          (new — consolidates suspend/reactivate/repair/archive/delete)
  OrgMembersPanel.vue          (new — 3.1, replaces inline member list)
  UserProfilePanel.vue         (new — 3.2)
  UserActionsPanel.vue         (new — consolidates deactivate/reactivate/delete/invite/reset/impersonate)
  UserSessionsPanel.vue        (new — 2.4 sessions)
  UserApiKeysPanel.vue         (new — 2.4 api keys)
  DangerZone.vue               (new — shared red-bordered wrapper for destructive actions)
  TypedConfirmDialog.vue       (new — shared typed-confirmation dialog for GDPR-grade deletes)
```

Shared dialog components avoid duplicating the confirm flows across panels.
The `DangerZone` wrapper enforces consistent visual treatment and requires a
`confirmText` prop that maps to the typed-confirmation dialog.

### 5.5 Audit Event Taxonomy

New event types (all `event_type` strings land under the existing
`audit_events` table):

```
org.metadata_updated
org.auth0_repair
org.auth0_partial_repair
org.member_added
org.member_removed
org.created
org.archived
org.deleted
user.profile_updated
user.invite_sent
user.password_reset_sent
user.session_revoked
user.api_key_revoked
user.deleted
user.impersonate_started
user.impersonate_stopped
users.merged
user.moved
user.created
```

All events log the actor sub in the `detail` JSON and use the existing
`resource_type` + `resource_id` columns for indexing.

### 5.6 Cache Invalidation Strategy

The existing `AdminStore` caches `auth0:orgs`, `auth0:org_members:{id}`, and
`auth0:users:{sub}` with TTLs of 3600s / 600s / 600s. Mutations must
explicitly invalidate the affected keys rather than waiting for TTL:

| Mutation | Invalidate |
|---|---|
| Org metadata edit | `auth0:orgs` |
| Org member add/remove | `auth0:org_members:{oidc_org_id}` |
| User profile edit | `auth0:users:{sub}` |
| User delete | `auth0:users:{sub}` |
| Org delete | `auth0:orgs`, `auth0:org_members:{oidc_org_id}` |

Add a `cache.delete(key)` helper if it doesn't already exist.

### 5.7 Tenant & Role Guardrails

Every new destructive endpoint must enforce:

- **No self-action** — admin cannot delete/deactivate/impersonate themselves
- **No cross-super_admin action** — super_admins can never act destructively
  on each other (prevents lockout and forces escalation out-of-band)
- **Cloud-only gating** via `_require_cloud(request)` where the action has no
  self-hosted meaning (invites, tickets, impersonation)
- **Audit before response** — the response is built after the audit log
  attempt so a failure there still returns a 200 but the warning lands in
  the logs (matches existing pattern)

## 6. Rollout Plan

<!-- canon:system:6 status:draft -->

### Phase 1 — P0 Core CRUD

Ship §2 in a single PR stack (metadata edit → provisioning repair → user
tickets → sessions/keys → GDPR delete). Each section is independently
deployable behind the existing `SUPER_ADMIN` gate, so a partial stack is
safe to merge. Target: dogfood on production for two weeks before P1.

### Phase 2 — P1 Membership & Profile

Ship §3 once P0 has bake time. §3.3 (impersonation) is the highest-risk item
in this spec and lands last in Phase 2 with a feature flag
(`ADMIN_IMPERSONATION_ENABLED`) defaulted off for the first week.

### Phase 3 — P2 Bulk & Lifecycle

Ship §4 opportunistically once `multi-org-personal-accounts` lands. §4.3 is
blocked on that spec; §4.1 and §4.2 can ship independently.

### Success Criteria

- Zero `psql` escalations for routine support operations over a 30-day
  window after P0 ships (measured via support ticket tags)
- Impersonation used at least twice by support without an incident
- Audit log shows 100% coverage of admin actions (no "someone updated this
  org but we can't tell who")
- GDPR delete path has been exercised once in production (synthetic user)
  to prove the atomic rollback works

### Dependencies & Blockers

- `infra-enablement-billing-email.md` must land the Auth0 M2M credentials in
  prod before **any** Management API call from the admin UI will work; this
  spec assumes `AUTH0_M2M_CLIENT_ID` / `AUTH0_M2M_CLIENT_SECRET` are
  available via Doppler → K8s secret → env
- `multi-org-personal-accounts.md` blocks §4.3 (merge / move); §2.2
  (provisioning repair) is complementary and should coordinate on the
  idempotent provisioning helper
- `admin-actions.md` is superseded by this spec; mark it so once §3.3 lands

## 7. Open Questions

- Should the `organizations_meta` table be per-`org_login` or per-installation_id?
  Installation_id is more correct (orgs can reinstall) but `org_login` matches
  every other admin surface. Leaning `org_login` with a note that reinstall
  preserves metadata.
- `create_invitation` on Auth0 requires an `inviter` user — do we use the
  acting super_admin's `oidc_sub` or a service account? Leaning actor for
  traceability.
- Should GDPR delete retain a hash of the email for duplicate-detection so a
  deleted user can't silently re-register and bypass some future ban? This is
  a policy question — flagging for legal review before implementation.
- Is "Danger Zone" the right visual metaphor for the Vue surface, or should
  we follow `AlertDialog` from the existing shadcn-style patterns on the
  marketing site? (Frontend lead call.)
- Do we want the admin UI to show a warning when Auth0 M2M credentials are
  not configured (self-hosted mode or misconfigured cloud), rather than
  silently returning 404s? Leaning yes — a one-line banner in `AdminLayout.vue`.
