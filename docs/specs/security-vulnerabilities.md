---
title: "Security Vulnerabilities: Immediate Fixes"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-02-26
tags: [security, mcp, auth, session]
---

# Security Vulnerabilities: Immediate Fixes

Fix three high-severity vulnerabilities identified in the Canon platform: an unauthenticated MCP endpoint, an authentication bypass when Auth0 is disabled, and a hardcoded session secret fallback.

## 1. Background

<!-- canon:system:1 status:done -->

A security review identified three vulnerabilities that must be resolved before production deployment. These are distinct from the broader [auth hardening](auth-hardening.md) work — they are immediate fixes for existing code paths, not new feature development.

**Related:** [#97](https://github.com/canonhq/canon/issues/97), [#98](https://github.com/canonhq/canon/issues/98), [#99](https://github.com/canonhq/canon/issues/99)

<!-- canon:ticket:github:409 -->
## 2. Secure Unauthenticated MCP Endpoint

<!-- canon:system:2 status:todo -->

**Severity: HIGH**

The MCP endpoint at `/mcp` provides read/write access to all connected GitHub repositories when no API key or database is configured. Unconfigured deployments expose full repository access without authentication.

**Fix:** Require authentication on the MCP endpoint regardless of configuration state. When no API key or database is configured, the endpoint should return 503 (service unavailable), not grant anonymous access.

### Acceptance Criteria

- [ ] MCP endpoint requires authentication (API key or session) for all requests
- [ ] Unconfigured deployments return 503 on `/mcp` instead of granting anonymous access
- [ ] Existing authenticated MCP access continues to work
- [ ] MCP endpoint returns appropriate error messages for auth failures

<!-- canon:ticket:github:410 -->
## 3. Fix Authentication Bypass When Auth0 Is Disabled

<!-- canon:system:3 status:todo -->

**Severity: HIGH**

When Auth0 is not configured, all users receive anonymous access with full admin permissions. Any unconfigured deployment grants complete access to all functionality.

**Files:** `src/specwright/auth/middleware.py`, `src/specwright/auth/deps.py`

**Fix:** When Auth0 is not configured, restrict access to read-only or deny access entirely. Do not grant admin permissions to anonymous users.

### Acceptance Criteria

- [ ] Unconfigured Auth0 does not grant admin permissions to anonymous users
- [ ] Unconfigured deployments restrict access to read-only or health-check endpoints only
- [ ] Auth middleware logs a warning when Auth0 is not configured
- [ ] Development mode can optionally bypass auth with an explicit `DEV_AUTH_BYPASS=true` env var (never set in production)

<!-- canon:ticket:github:411 -->
## 4. Remove Hardcoded Session Secret Fallback

<!-- canon:system:4 status:todo -->

**Severity: HIGH**

The `SessionMiddleware` falls back to the hardcoded value `"dev-not-secret"` when Auth0 is not configured. This enables session forgery since the secret is publicly known in source code.

**File:** `src/specwright/main.py`

**Fix:** Remove the hardcoded fallback. Require `APP_SECRET_KEY` environment variable. Application should fail to start if the secret is missing.

### Acceptance Criteria

- [ ] Hardcoded session secret fallback `"dev-not-secret"` removed
- [ ] `APP_SECRET_KEY` environment variable required for session middleware
- [ ] Application fails to start with a clear error if `APP_SECRET_KEY` is missing
- [ ] Development setup instructions updated to include generating a local secret

## 5. Open Questions

- Should we add a startup health check that validates all required security configuration is present?
- Should development mode use a deterministic (but not production) secret for local testing convenience?
