---
title: "Integration Management"
status: draft
owner: ng
team: platform
ticket_project: null
created: 2026-03-31
updated: 2026-03-31
tags: [integrations, settings, oauth, vcs, ticketing]
---

# Integration Management

## Background

Canon integrates with VCS providers (GitHub), ticketing systems (Jira, Linear, GitHub Issues), notification platforms (Slack), and AI services (Anthropic). Today these integrations are configured exclusively through environment variables or CANON.yaml — there is no web UI for users to manage connections.

Users who authenticate via email/password or Google OAuth have **no way to connect their GitHub account** to Canon. The only path to a GitHub identity is logging in with GitHub SSO. Similarly, org admins cannot configure Jira or Linear integrations without server-level env var access.

This spec introduces a unified Settings experience that consolidates integration management, billing, API keys, and notification configuration into a single `/app/:org/settings` route with tabbed navigation.

### Goals

- Let any authenticated user connect their GitHub account regardless of login method
- Let org admins configure VCS and ticketing provider connections via OAuth flows
- Consolidate billing, API keys, and BYOK settings under a unified Settings page
- Update ticket sync adapters to read credentials from DB (with env var fallback)
- Encrypt all stored credentials at rest using the existing AES-256-GCM infrastructure

### Non-Goals

- GitLab/Bitbucket support (future spec)
- Self-hosted Jira Server OAuth (only Jira Cloud OAuth 2.0 3LO)
- Migrating existing env-var deployments — env vars continue to work as fallback
- SCIM provisioning or SSO configuration (remains in Auth0/OIDC provider)

---

## System 1: Unified Settings Page

<!-- canon:system:1 status:draft -->

Replace the current Billing nav item with a Settings page at `/app/:org/settings` using tabbed navigation.

### 1.1 Settings Shell & Navigation

<!-- canon:section:1.1 status:draft -->

The Settings page is a tabbed layout with sub-routes:

| Tab | Route | Permission | Content |
|-----|-------|-----------|---------|
| Integrations | `/settings/integrations` | `specs:read` (view), `org:manage` (configure) | VCS, ticketing, notification connections |
| API Keys | `/settings/api-keys` | `org:manage` | API key CRUD (moved from current location) |
| Billing | `/settings/billing` | `specs:read` | Subscription, seats, AI ops (current BillingView content) |
| AI | `/settings/ai` | `specs:read` (view), `specs:admin` (configure) | BYOK Anthropic key management |

**Acceptance Criteria:**

- [ ] New `SettingsView.vue` with tab navigation renders at `/app/:org/settings`
- [ ] Tabs route to `/settings/integrations`, `/settings/api-keys`, `/settings/billing`, `/settings/ai`
- [ ] Default tab is Integrations when navigating to `/settings`
- [ ] Nav item in `AppNav.vue` changes from "Billing" to "Settings" with gear icon
- [ ] Old `/app/:org/billing` route redirects to `/app/:org/settings/billing`
- [ ] Tab visibility respects permissions — all users see Integrations (read) and Billing; only admins see API Keys and can configure integrations
- [ ] Mobile responsive: tabs collapse to dropdown on small screens

---

## System 2: User-Level VCS Connections

<!-- canon:system:2 status:draft -->

Allow any authenticated user to connect their GitHub account via OAuth, persisting the token to the database instead of only the session.

### 2.1 GitHub OAuth Connection (User-Level)

<!-- canon:section:2.1 status:draft -->

Refactor the existing `/auth/github/*` flow to persist tokens in a new `user_connections` table, making the GitHub identity durable across sessions.

**Database schema — `user_connections`:**

```sql
CREATE TABLE user_connections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,  -- 'github', 'gitlab', 'bitbucket'
    provider_user_id TEXT NOT NULL, -- e.g. GitHub user ID
    provider_login  TEXT NOT NULL,  -- e.g. GitHub username
    encrypted_token BYTEA NOT NULL, -- AES-256-GCM encrypted access token
    refresh_token   BYTEA,          -- encrypted refresh token (if applicable)
    scopes          TEXT[] DEFAULT '{}',
    token_expires_at TIMESTAMPTZ,
    connected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider)
);
CREATE INDEX idx_user_connections_user ON user_connections(user_id);
```

**Acceptance Criteria:**

- [ ] `user_connections` table created via migration
- [ ] `UserConnectionStore` class follows existing DAO pattern (`async with pool.acquire()`)
- [ ] GitHub OAuth callback persists encrypted token to `user_connections` instead of session-only
- [ ] GitHub token also set in session for backward compatibility with editor
- [ ] `GET /app/{org}/api/settings/connections` returns list of user's connections (provider, login, scopes, connected_at — never the token)
- [ ] `DELETE /app/{org}/api/settings/connections/github` disconnects GitHub (deletes row, clears session)
- [ ] Connection card in Integrations tab shows GitHub status: connected username + avatar, or "Connect" button
- [ ] Connect button initiates OAuth flow; on callback, redirects back to Settings/Integrations tab
- [ ] Token encryption uses existing `encrypt_api_key` / `decrypt_api_key` from `canon.billing.encryption`
- [ ] Profile endpoint (`/api/profile`) includes `connections: [{provider, login, connected_at}]`

### 2.2 GitHub Token Refresh

<!-- canon:section:2.2 status:draft -->

GitHub OAuth tokens for GitHub Apps can expire. Handle token refresh gracefully.

**Acceptance Criteria:**

- [ ] If GitHub OAuth app is configured with token expiration, store and use refresh token
- [ ] On 401 from GitHub API, attempt token refresh before failing
- [ ] If refresh fails, mark connection as `needs_reauth` and surface in UI
- [ ] Connection card shows warning badge when reauth is needed

---

## System 3: Org-Level Ticketing Provider Connections

<!-- canon:system:3 status:draft -->

Allow org admins to connect ticketing providers via OAuth flows, storing credentials encrypted in the database.

### 3.1 Jira Cloud OAuth 2.0 (3LO)

<!-- canon:section:3.1 status:draft -->

Implement Atlassian OAuth 2.0 three-legged OAuth for Jira Cloud connections.

**OAuth flow:**
1. Admin clicks "Connect Jira" → redirect to `https://auth.atlassian.com/authorize`
2. Scopes: `read:jira-work`, `write:jira-work`, `read:jira-user`
3. Callback exchanges code for access + refresh tokens
4. Fetch accessible resources (`/oauth/token/accessible-resources`) to get cloud ID
5. Store encrypted tokens + cloud ID + site name in `org_integrations`

**Database schema — `org_integrations`:**

```sql
CREATE TABLE org_integrations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_login       TEXT NOT NULL,
    provider        TEXT NOT NULL,  -- 'jira', 'linear', 'slack', 'github_issues'
    display_name    TEXT NOT NULL,  -- e.g. "Acme Corp Jira", user-chosen label
    encrypted_config BYTEA NOT NULL, -- AES-256-GCM encrypted JSON blob
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'needs_reauth', 'error', 'disabled')),
    provider_metadata JSONB DEFAULT '{}', -- non-sensitive metadata (site name, cloud ID, etc.)
    connected_by    BIGINT REFERENCES users(id),
    connected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_login, provider, id)
);
CREATE INDEX idx_org_integrations_org ON org_integrations(org_login);
CREATE INDEX idx_org_integrations_provider ON org_integrations(org_login, provider);
```

The `encrypted_config` JSON blob structure varies per provider:

```json
// Jira
{
  "access_token": "...",
  "refresh_token": "...",
  "cloud_id": "...",
  "site_url": "https://acme.atlassian.net",
  "token_expires_at": "2026-04-01T00:00:00Z"
}

// Linear
{
  "access_token": "...",
  "workspace_id": "...",
  "workspace_name": "Acme"
}
```

**Acceptance Criteria:**

- [ ] `org_integrations` table created via migration
- [ ] `IntegrationStore` class with `upsert_integration()`, `get_integration()`, `list_integrations()`, `delete_integration()`, `update_status()`
- [ ] `POST /app/{org}/api/settings/integrations/jira/connect` initiates Jira OAuth 2.0 3LO flow
- [ ] `/auth/integrations/jira/callback` exchanges code, fetches accessible resources, stores encrypted config
- [ ] Jira connection card shows site name, connected-by user, status badge
- [ ] "Disconnect" button removes integration (with confirmation dialog)
- [ ] "Test Connection" button verifies token validity by calling Jira API
- [ ] On token expiry, automatic refresh via Atlassian refresh token endpoint
- [ ] If refresh fails, status transitions to `needs_reauth` with UI warning
- [ ] Only `org:manage` permission can connect/disconnect/test

### 3.2 Linear OAuth 2.0

<!-- canon:section:3.2 status:draft -->

Implement Linear OAuth 2.0 for workspace connections.

**OAuth flow:**
1. Admin clicks "Connect Linear" → redirect to `https://linear.app/oauth/authorize`
2. Scopes: `read`, `write`, `issues:create`
3. Callback exchanges code for access token (Linear tokens don't expire)
4. Fetch workspace info and store

**Acceptance Criteria:**

- [ ] `POST /app/{org}/api/settings/integrations/linear/connect` initiates Linear OAuth flow
- [ ] `/auth/integrations/linear/callback` exchanges code, fetches workspace info, stores encrypted config
- [ ] Linear connection card shows workspace name, connected-by user, status
- [ ] "Disconnect" and "Test Connection" buttons work
- [ ] Only `org:manage` permission can manage

### 3.3 GitHub Issues Connection

<!-- canon:section:3.3 status:draft -->

GitHub Issues integration uses the existing GitHub App installation rather than a separate OAuth flow. The Integrations tab surfaces installation status and allows selecting default repos.

**Acceptance Criteria:**

- [ ] GitHub Issues card shows GitHub App installation status from `gh_installations` table
- [ ] If installed: shows org name, repos count, installation date
- [ ] If not installed: shows "Install GitHub App" link pointing to the GitHub App installation URL
- [ ] Admin can select a default repository for ticket creation from the list of installed repos
- [ ] Default repo selection stored in `org_integrations` with provider `github_issues`

---

## System 4: Notification Connections

<!-- canon:system:4 status:draft -->

### 4.1 Slack Connection

<!-- canon:section:4.1 status:draft -->

Surface Slack bot status and configuration in the Integrations tab.

**Acceptance Criteria:**

- [ ] Slack card shows connection status (connected/not configured)
- [ ] If connected: shows workspace name, bot username
- [ ] If not connected: shows setup instructions (bot token + signing secret via env vars for now)
- [ ] Future: Slack OAuth "Add to Slack" button (when Slack app is published — out of scope for v1)
- [ ] Connection status derived from checking if `SLACK_BOT_TOKEN` is set and bot can authenticate

---

## System 5: Adapter Refactor — DB-First Credential Resolution

<!-- canon:system:5 status:draft -->

Update the ticket sync adapter factory to resolve credentials from the database first, falling back to environment variables for backward compatibility.

### 5.1 Factory Credential Resolution Order

<!-- canon:section:5.1 status:draft -->

The adapter factory currently reads credentials exclusively from env vars. Update to:

1. **DB lookup** — query `org_integrations` for the org + provider
2. **Env var fallback** — existing behavior (for self-hosted / env-var deployments)
3. **CANON.yaml auth_profiles** — existing per-repo override behavior

**Acceptance Criteria:**

- [ ] `AdapterFactory.from_org(org_login, pool)` async class method added
- [ ] DB lookup decrypts `encrypted_config` and constructs adapter config
- [ ] If DB has no integration for provider, falls back to env vars (existing behavior unchanged)
- [ ] CANON.yaml `auth_profiles` override both DB and env vars when specified per-repo
- [x] Resolution order is documented in code comments
<!-- canon:realized-in:PR#512 file:src/canon/github/handlers/on_push.py -->
<!-- canon:realized-in:PR#512 file:src/canon/cron/sync_status.py -->
- [ ] Existing `from_config()` and `from_env()` methods preserved for backward compatibility

### 5.2 Jira Adapter — OAuth Token Support

<!-- canon:section:5.2 status:draft -->

The Jira adapter currently only supports API token auth. Add OAuth bearer token support.

**Acceptance Criteria:**

- [ ] `JiraConfig` gains optional `auth_method` field: `"api_token"` (default) or `"oauth"`
- [ ] When `auth_method="oauth"`, use `Authorization: Bearer {access_token}` instead of Basic auth
- [ ] OAuth tokens use `cloud_id` for API base URL: `https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/`
- [ ] Token refresh integrated into request flow (refresh on 401, retry once)
- [ ] Existing API token auth path unchanged

### 5.3 Linear Adapter — OAuth Token Support

<!-- canon:section:5.3 status:draft -->

The Linear adapter uses API keys. OAuth tokens work identically (bearer token), so minimal changes needed.

**Acceptance Criteria:**

- [ ] `LinearConfig` accepts token from either `api_key` field or `access_token` field
- [ ] OAuth-sourced tokens use the same bearer auth header
- [ ] No functional change to API calls

---

## System 6: Credential Security

<!-- canon:system:6 status:draft -->

### 6.1 Encryption at Rest

<!-- canon:section:6.1 status:draft -->

All integration credentials are encrypted using the existing AES-256-GCM infrastructure from `canon.billing.encryption`.

**Acceptance Criteria:**

- [ ] `encrypted_config` in `org_integrations` uses `encrypt_api_key()` from billing.encryption
- [ ] `encrypted_token` in `user_connections` uses the same encryption
- [ ] Encryption key sourced from `ENCRYPTION_KEY` env var (same as BYOK keys)
- [ ] Decryption only happens server-side when constructing adapter configs — tokens never sent to frontend
- [ ] API responses for integration listings never include raw tokens, only status + metadata

### 6.2 Token Rotation & Expiry

<!-- canon:section:6.2 status:draft -->

Proactively handle token expiry for OAuth providers that issue short-lived tokens.

**Acceptance Criteria:**

- [ ] Jira: refresh token used proactively when access token is within 5 minutes of expiry
- [ ] GitHub: refresh token used when token expires (if GitHub App OAuth uses expiring tokens)
- [ ] On refresh, `encrypted_config` updated in DB with new tokens + new `updated_at`
- [ ] Failed refresh transitions integration status to `needs_reauth`
- [ ] Cron job or lazy refresh: at minimum, tokens refreshed on use; optionally a background job

---

## System 7: Integration Status & Health

<!-- canon:system:7 status:draft -->

### 7.1 Connection Health Checks

<!-- canon:section:7.1 status:draft -->

Each integration connection includes a test/health check that verifies the stored credentials still work.

**Acceptance Criteria:**

- [ ] `POST /app/{org}/api/settings/integrations/{provider}/test` endpoint
- [ ] Jira: calls `/rest/api/3/myself` with stored credentials
- [ ] Linear: calls GraphQL `viewer` query
- [ ] GitHub: calls `/user` with stored token
- [ ] Returns `{ok: bool, message: string, latency_ms: number}`
- [ ] UI shows test result inline on the connection card
- [ ] Rate-limited to 1 test per provider per minute

### 7.2 Integration Status in Dashboard

<!-- canon:section:7.2 status:draft -->

Surface integration health in the org dashboard so issues are visible without navigating to Settings.

**Acceptance Criteria:**

- [ ] Dashboard shows integration status summary: "3 connected, 1 needs attention"
- [ ] Clicking the summary navigates to Settings/Integrations
- [ ] `needs_reauth` and `error` status integrations highlighted with warning badge

---

## Rollout Plan

<!-- canon:section:rollout status:draft -->

### Phase 1: Settings Shell + VCS Connections (1-2 weeks)
- System 1 (Settings page with tabs)
- System 2 (GitHub OAuth persistence)
- System 6.1 (encryption for user connections)
- Redirect old Billing route

### Phase 2: Ticketing OAuth Flows (2-3 weeks)
- System 3.1 (Jira Cloud OAuth)
- System 3.2 (Linear OAuth)
- System 3.3 (GitHub Issues card)
- System 6.2 (token rotation)

### Phase 3: Adapter Refactor + Polish (1-2 weeks)
- System 5 (adapter factory reads from DB)
- System 4 (Slack status card)
- System 7 (health checks + dashboard status)

### Migration Strategy
- Env-var configured integrations continue to work unchanged
- DB-configured integrations take precedence when present
- No data migration needed — new tables, new data
- Existing BYOK Anthropic key storage in `anthropic_keys` table unchanged
