---
title: "Auth Hardening: Login Options, CLI Auth, E2E AuthZ"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-03-03
tags: [auth, security, cli, platform]
---

# Auth Hardening: Login Options, CLI Auth, E2E AuthZ

Strengthen Canon's authentication and authorization across all surfaces — web, CLI, API — by adding multiple login providers, a CLI-native auth flow, and robust token/session/RBAC infrastructure.

## 1. Background

<!-- specwright:system:1 status:done -->

Canon currently authenticates web users via Auth0 Universal Login with session cookies, supports API keys for service-to-service access, and uses GitHub App JWT for webhook verification. Several gaps exist:

- **Login options**: The web UI redirects directly to Auth0 with no provider choice. Users who prefer GitHub login, Google SSO, or passwordless email have no visible option.
- **CLI auth**: The CLI only checks `gh auth status` for local GitHub CLI — it has no way to authenticate with the Canon platform API. This blocks CLI features like `canon plan`, `canon status`, and `canon sync` from working against remote orgs.
- **Session robustness**: Sessions are server-side cookies with no refresh rotation, no per-device listing, and no remote revocation. The Role enum (VIEWER, EDITOR, ADMIN) exists in code but isn't wired to user assignment.

This spec addresses all three areas in a coordinated effort.

## 2. Login Provider Selection

<!-- specwright:system:2 status:done -->

Replace the direct Auth0 redirect with a login page that offers multiple identity providers. Auth0 "connections" handle the protocol details; the Canon frontend presents the choices.

### 2.1 Supported Providers

| Provider | Auth0 Connection Type | Priority |
|---|---|---|
| GitHub | Social | P0 — most users are developers |
| Google Workspace | Enterprise (OIDC) | P0 — common org SSO |
| Email magic link | Passwordless | P1 — fallback for non-SSO users |
| Microsoft Entra ID | Enterprise (SAML/OIDC) | P2 — enterprise orgs |

### 2.2 Frontend Login Page

A new `/auth/login` page (Vue component) replaces the instant redirect. It shows provider buttons and handles the `?org=<slug>` parameter to scope the login to a specific org.

### Acceptance Criteria

- [ ] Auth0 tenant has GitHub social connection enabled and tested
- [ ] Auth0 tenant has Google Workspace connection enabled and tested
- [ ] Auth0 tenant has passwordless email (magic link) connection enabled
- [ ] Frontend login page renders provider buttons (GitHub, Google, Email)
<!-- specwright:realized-in:PR#108 file:frontend/src/views/LoginView.vue -->
- [ ] Clicking a provider button initiates the correct Auth0 connection flow
<!-- specwright:realized-in:PR#108 file:src/specwright/auth/routes.py -->
- [ ] `?org=<slug>` parameter is preserved through the login flow and used for post-login redirect
- [ ] Auth0 callback correctly resolves identity regardless of provider used
- [ ] Existing session-based auth continues to work (backward compatible)

## 3. CLI Platform Authentication

<!-- specwright:system:3 status:done -->

Add a `canon login` command that authenticates the CLI user with the Canon platform using the OAuth 2.0 Device Authorization Grant (RFC 8628). This is the standard pattern used by `gh`, `az`, and `gcloud` for CLI auth.

### 3.1 Device Authorization Flow

1. CLI calls `POST /auth/device/code` → receives `device_code`, `user_code`, `verification_uri`
2. CLI displays: "Open {verification_uri} and enter code: {user_code}"
3. CLI polls `POST /auth/device/token` until user completes browser approval
4. On success, CLI receives `access_token` + `refresh_token`
5. Tokens stored locally at `~/.config/canon/credentials.json`

### 3.2 Backend Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/auth/device/code` | POST | Issue device code + user code |
| `/auth/device/token` | POST | Poll for token (returns pending/approved/denied) |

These proxy to Auth0's Device Authorization endpoints, keeping client credentials server-side.

### 3.3 CLI Commands

| Command | Description |
|---|---|
| `canon login` | Start device auth flow |
| `canon login --api-key <key>` | Store an API key directly (CI/headless) |
| `canon logout` | Clear stored credentials |
| `canon auth status` | Show current auth state (logged in as, org, expiry) |

### 3.4 Token Storage

Credentials file (`~/.config/canon/credentials.json`):

```json
{
  "method": "oauth",
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": "2026-03-01T00:00:00Z",
  "org": "my-org",
  "email": "user@example.com"
}
```

Or for API key auth:

```json
{
  "method": "api_key",
  "api_key": "sw_...",
  "org": "my-org"
}
```

File permissions: `0600` (owner read/write only).

### 3.5 CLI HTTP Client

All CLI commands that call the platform API use the stored credential:
- OAuth: `Authorization: Bearer <access_token>` with automatic silent refresh when expired
- API key: `Authorization: Bearer <api_key>`

### Acceptance Criteria

- [ ] `POST /auth/device/code` returns device_code, user_code, verification_uri, and interval
<!-- specwright:realized-in:PR#108 file:src/specwright/auth/device_routes.py -->
- [ ] `POST /auth/device/token` returns access_token + refresh_token on approval, or pending/expired status
- [ ] `canon login` opens browser (or prints URL), displays user code, and polls for approval
<!-- specwright:realized-in:PR#108 file:src/specwright/cli/login.py -->
- [ ] `canon login --api-key <key>` validates the key against the platform and stores it
- [ ] `canon logout` removes `~/.config/canon/credentials.json`
<!-- specwright:realized-in:PR#108 file:src/specwright/cli/logout.py -->
- [ ] `canon auth status` displays current auth state (method, email/org, token expiry)
<!-- specwright:realized-in:PR#108 file:src/specwright/cli/auth_cmd.py -->
- [ ] Credentials file is created with `0600` permissions
<!-- specwright:realized-in:PR#108 file:src/specwright/cli/_credentials.py -->
- [ ] CLI HTTP client automatically refreshes expired OAuth tokens using refresh_token
<!-- specwright:realized-in:PR#108 file:src/specwright/cli/_platform.py -->
- [ ] CLI HTTP client falls back to API key when OAuth token is unavailable
- [ ] Auth0 tenant has Device Authorization Grant enabled for the Canon application

## 4. Token Refresh and Session Management

<!-- specwright:system:4 status:done -->

Replace sticky session cookies with a proper token lifecycle: short-lived access tokens, rotating refresh tokens, and per-device session tracking.

### 4.1 Token Lifecycle

| Token | Lifetime | Storage | Rotation |
|---|---|---|---|
| Access token | 15 minutes | Web: frontend memory (never persisted); CLI: `credentials.json` | Re-issued via refresh |
| Refresh token | 7 days | Web: httpOnly secure cookie; CLI: `credentials.json` | Rotated on every use |
| Session record | 30 days max | Server-side DB | Revocable |

### 4.2 Refresh Endpoint

`POST /auth/refresh` — accepts the refresh token cookie, validates it, rotates it, and returns a new access token in the response body.

### 4.3 Frontend Token Handling

The Vue API client (`api/client.ts`) intercepts 401 responses, calls `/auth/refresh`, retries the original request with the new access token, and redirects to login only if refresh also fails.

### 4.4 Session Table

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,        -- opaque session ID
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_login       TEXT NOT NULL,
    device_label    TEXT NOT NULL DEFAULT '', -- "Chrome on macOS", "canon-cli"
    refresh_hash    TEXT NOT NULL,            -- HMAC-SHA256 of current refresh token (keyed with APP_SECRET_KEY)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ              -- null = active
);
```

### 4.5 Session Management UI

Settings page (`/app/{org}/settings/sessions`) lists active sessions with device label, last used, and a "Revoke" button. Revoking a session invalidates its refresh token.

### Acceptance Criteria

- [ ] `POST /auth/refresh` issues new access token and rotates refresh token
<!-- specwright:realized-in:PR#108 file:src/specwright/auth/refresh_routes.py -->
- [ ] Refresh token is stored as httpOnly secure cookie (not accessible to JS)
- [ ] Access token is held in memory only (not localStorage, not cookie)
- [ ] Frontend API client automatically retries requests after 401 → refresh
<!-- specwright:realized-in:PR#108 file:frontend/src/api/client.ts -->
- [ ] Frontend redirects to login only when refresh fails (refresh token expired/revoked)
- [ ] Sessions table tracks per-device sessions with device_label and last_used_at
<!-- specwright:realized-in:PR#108 file:src/specwright/db/schema_users.sql -->
- [ ] Settings UI lists active sessions with device label, created date, and last used
- [ ] "Revoke" button invalidates a session's refresh token immediately
- [ ] "Revoke all other sessions" button invalidates all sessions except the current one
- [ ] Expired sessions are cleaned up by a background task (reuse existing key cleanup pattern)
<!-- specwright:realized-in:PR#108 file:src/specwright/cron/cleanup_sessions.py -->

<!-- specwright:ticket:github:259 -->
<!-- specwright:ticket:github:283 -->
## 5. Role-Based Access Control Wiring

<!-- specwright:system:5 status:todo -->

Wire the existing Role enum (VIEWER, EDITOR, ADMIN) to user records and enforce role-based permission assignment. Currently, permissions come from Auth0 access token claims — this adds a server-side layer that the Auth0 claims seed but that can be overridden by org admins.

### 5.1 User-Org Role Assignment

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_role TEXT NOT NULL DEFAULT 'viewer';

CREATE TABLE org_members (
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_login   TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'viewer',  -- viewer, editor, admin
    assigned_by BIGINT REFERENCES users(id),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, org_login)
);
```

### 5.2 Permission Resolution

1. Auth0 token claims provide initial permissions
2. Server-side `org_members.role` overrides if present
3. `ROLE_PERMISSIONS` mapping (already exists in `permissions.py`) converts role → permission set
4. `get_current_user()` merges both sources

### 5.3 Admin UI

Settings page (`/app/{org}/settings/members`) allows admins to:
- View all org members with their roles
- Change a member's role (viewer/editor/admin)
- Remove a member from the org

### Acceptance Criteria

- [ ] `org_members` table created with user_id, org_login, role, assigned_by
- [ ] `get_current_user()` resolves role from `org_members` table when available
- [ ] Role → permission mapping uses existing `ROLE_PERMISSIONS` from `permissions.py`
- [ ] Auth0 claims are used as seed when a user first logs in (no existing org_member row)
- [ ] Org admins can view, change, and remove member roles via settings UI
- [ ] Non-admin users cannot access member management endpoints (403)
- [ ] Role changes take effect on next token refresh (not immediately mid-session) — this means a demoted user may retain elevated access for up to 15 minutes (one access token lifetime). This is a deliberate trade-off for JWT statelessness; immediate revocation would require token introspection on every request.

<!-- specwright:ticket:github:260 -->
<!-- specwright:ticket:github:284 -->
## 6. Auth Audit Logging

<!-- specwright:system:6 status:todo -->

Log all authentication and authorization events to a structured audit trail for security review and compliance.

### 6.1 Events to Log

| Event | Data |
|---|---|
| `auth.login` | user_sub, provider, org, ip, user_agent |
| `auth.logout` | user_sub, org |
| `auth.login_failed` | provider, error, ip, user_agent |
| `auth.token_refreshed` | user_sub, session_id |
| `auth.session_revoked` | user_sub, session_id, revoked_by |
| `auth.api_key_created` | user_sub, key_id, org, scopes |
| `auth.api_key_revoked` | user_sub, key_id, org, revoked_by |
| `auth.role_changed` | target_user, org, old_role, new_role, changed_by |
| `auth.permission_denied` | user_sub, permission, resource, org |

### 6.2 Implementation

Emit events via Python `logging` to a structured JSON logger. Optionally forward to PostHog (already integrated) for dashboarding.

### Acceptance Criteria

- [ ] All events in §6.1 are emitted as structured JSON log entries
- [ ] Log entries include timestamp, event type, actor, and relevant metadata
- [ ] `auth.permission_denied` events include the denied permission and target resource
- [ ] Events are queryable via standard log aggregation (structured JSON format)
- [ ] Login events capture IP address and user agent for security review

## 7. Infrastructure Changes

<!-- specwright:system:7 status:done -->

Auth0 tenant and deployment configuration changes required to support the above features.

### 7.1 Auth0 Tenant Configuration (gv-infra)

- Enable GitHub social connection
- Enable Google Workspace enterprise connection
- Enable passwordless email connection
- Enable Device Authorization Grant for the Canon application
- Configure refresh token rotation policy (7-day absolute, rotate on use)
- Configure MFA policy (optional, org-level)

### 7.2 Deployment Changes

- New environment variables: `AUTH0_AUDIENCE` (required for JWT validation), `AUTH0_DEVICE_CLIENT_ID` (if separate from web client)
- Deploy workflow: `AUTH0_AUDIENCE` added to K8s secret creation in `.github/workflows/deploy.yml`
- Helm chart: `audience` and `deviceClientId` added to `values.yaml` and `templates/secret.yaml`
- New DB migration: `sessions` table, `org_members` table
- Helm chart: add session cleanup CronJob (reuse pattern from `sync_status.py`)

### Acceptance Criteria

- [ ] Auth0 GitHub social connection configured and tested in staging
- [ ] Auth0 Google Workspace connection configured and tested in staging
- [ ] Auth0 passwordless email connection configured and tested in staging
- [x] Auth0 Device Authorization Grant enabled and tested with CLI
- [ ] Auth0 refresh token rotation policy configured (7-day, rotate-on-use)
- [ ] DB migrations for `sessions` and `org_members` tables applied
- [ ] Helm chart updated with session cleanup CronJob
- [x] All new environment variables documented and added to Doppler

<!-- specwright:ticket:github:261 -->
<!-- specwright:ticket:github:285 -->
## 8. Rollout Plan

<!-- specwright:system:8 status:in_progress -->

### Phase 1: Foundation (CLI auth + token refresh)
- Implement device auth endpoints and CLI `login`/`logout`/`auth status`
- Implement token refresh endpoint and frontend interceptor
- Deploy behind feature flag — existing session auth continues to work

### Phase 2: Login providers
- Configure Auth0 connections (GitHub, Google, email)
- Build frontend login page with provider buttons
- Test e2e with each provider

### Phase 3: RBAC + sessions
- Add `org_members` and `sessions` tables
- Wire role resolution into `get_current_user()`
- Build session management and member management UIs

### Phase 4: Audit + hardening
- Add audit logging for all auth events
- Session cleanup CronJob
- Security review and penetration test

## 9. Open Questions

- Should the CLI support platform-specific secure credential storage (macOS Keychain, Windows Credential Manager) or is `~/.config/canon/credentials.json` with `0600` permissions sufficient for v1?
- Do we need SAML support for Microsoft Entra ID, or is OIDC sufficient? (Auth0 supports both.)
- Should MFA enforcement be in scope for this spec or a follow-up?
- What's the migration path for existing session-cookie users when we switch to token-based auth? (Phase 1 should support both simultaneously.)
