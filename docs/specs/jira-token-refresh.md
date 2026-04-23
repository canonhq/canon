---
title: Jira OAuth Token Refresh
status: in-progress
priority: high
created: 2026-04-23
---

# Jira OAuth Token Refresh

## Problem

Jira Cloud OAuth 2.0 (3LO) access tokens expire after 1 hour. Canon stores a
`refresh_token` during the OAuth callback but never uses it — when the access
token expires, all Jira API calls fail with 401 and the integration shows as
`error` in `canon doctor`.

## Design

Two-layer refresh strategy: reactive (adapter-level retry-on-401) and proactive
(cron job to prevent expiry).

### Layer 1 — Reactive refresh in JiraAdapter

When `_request()` receives a 401:

1. Call `_refresh_tokens()` which POSTs to `https://auth.atlassian.com/oauth/token`
   with `grant_type=refresh_token`, the stored refresh token, and the Jira OAuth
   client credentials from settings.
2. On success: update the in-memory token, persist new `access_token` +
   `refresh_token` + `token_refreshed_at` via `IntegrationStore.update_config()`,
   and retry the original request once.
3. On failure: set integration status to `needs_reauth` via the store, raise
   `JiraAuthError` so callers know re-authorization is required.

The adapter needs `org_login`, `IntegrationStore`, and Jira OAuth client
credentials (from Settings) to perform refresh. These are passed through the
factory.

### Layer 2 — Proactive refresh cron job

New `src/canon/cron/refresh_tokens.py`:

- Uses `@tracked_cron("refresh_integration_tokens")` decorator.
- Queries `org_integrations` for active Jira entries.
- Checks `provider_metadata.token_refreshed_at` — if older than 45 minutes
  (Atlassian tokens expire at 60 min), proactively refreshes.
- On success: updates `encrypted_config` with new tokens and
  `provider_metadata.token_refreshed_at`.
- On failure: sets status to `needs_reauth`, logs warning.
- Skips entries already in `needs_reauth` or `error` status.

### Structural changes

**JiraAdapter** gains:
- `_refresh_tokens()` async method
- `_store: IntegrationStore | None` and `_org_login: str` fields
- `_jira_client_id: str` and `_jira_client_secret: str` fields
- One-retry-on-401 logic in `_request()`

**Adapter factory** (`from_org()`):
- Passes `store` and `org_login` when constructing `JiraAdapter`
- Passes `jira_oauth_client_id` and `jira_oauth_client_secret` from settings

**IntegrationStore**:
- Add `set_status()` method (or use existing update path) to transition
  to `needs_reauth` on refresh failure.

### Status transitions

```
active → (refresh succeeds) → active (updated tokens)
active → (refresh fails)    → needs_reauth
needs_reauth → (user re-connects via UI) → active
```

## Acceptance Criteria

- [ ] 401 from Jira triggers automatic token refresh and request retry
- [ ] Refreshed tokens are persisted to DB (encrypted)
- [ ] Failed refresh sets integration status to `needs_reauth`
- [ ] Cron job refreshes tokens before they expire (~45 min threshold)
- [ ] Cron job skips non-active integrations
- [ ] `canon doctor` and `canon integrations list` reflect correct status
- [ ] Tests cover: successful refresh, failed refresh, cron job logic
