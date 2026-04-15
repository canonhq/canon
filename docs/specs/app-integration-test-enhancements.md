---
title: "App Integration Test Enhancements"
status: in_progress
owner: ng
team: canon
ticket_project: canonhq/canon-private
created: 2026-04-14
updated: 2026-04-14
tags: [testing, integration, e2e, web, api]
---

# App Integration Test Enhancements

Expand integration and e2e test coverage across the Canon web application, closing the gap between unit tests (which mock at the service layer) and production behavior (which flows through middleware, auth, routing, and real service interactions).

## 1. Background

<!-- canon:system:1 status:done -->

Canon has ~1,800 unit tests and 63 integration tests. The unit tests achieve broad module coverage but mock at the function/service level, meaning they cannot catch:

- **Middleware ordering bugs** — auth middleware not running before route handlers
- **Serialization mismatches** — Pydantic model ↔ JSON response drift
- **Route wiring errors** — endpoints registered with wrong methods, prefixes, or dependencies
- **Cross-cutting concern failures** — rate limiting, caching, CORS interacting badly
- **Auth chain gaps** — permission checks passing in isolation but failing when composed

The existing `integration-testing.md` (done) covers webhooks and GitHub client. The `enhanced-platform-testing.md` (draft) covers config matrix, auth flows, Helm, Docker, OSS, and DB migrations. This spec addresses the remaining surface: the web application's HTTP API and the critical user journeys that span multiple subsystems.

### Related specs

- `integration-testing.md` — done; webhook + GitHub client integration tests
- `enhanced-platform-testing.md` — draft; config matrix, auth, Helm, Docker, OSS, migrations

## 2. Web App Route Integration Tests

<!-- canon:system:2 status:done -->

Test the web application routes through the real FastAPI stack using `httpx.AsyncClient` with `ASGITransport`. Every test exercises the full middleware chain (auth, rate limiting, caching, request logging) rather than calling handler functions directly.

### Acceptance Criteria

- [x] Integration tests for all `/app/*` dashboard routes (7 routes minimum)
<!-- canon:realized-in: file:tests/integration/test_web_routes.py -->
- [x] Tests verify HTML responses contain expected content (not just 200 status)
<!-- canon:realized-in: file:tests/integration/test_web_routes.py:TestMarketingPages -->
- [x] Tests verify unauthenticated requests redirect to `/auth/login`
<!-- canon:realized-in: file:tests/integration/test_web_routes.py:TestDashboardAuthEnforcement -->
- [x] Tests verify permission-gated routes return 403 for insufficient permissions
<!-- canon:realized-in: file:tests/integration/test_session_edge_cases.py:TestPermissionFallback -->
- [ ] Editor route tests verify GitHub API interaction through the full stack
- [x] API route tests verify JSON response schemas match Pydantic models
<!-- canon:realized-in: file:tests/integration/test_profile_settings.py:TestProfileRoute -->
- [x] Static/marketing routes return 200 with expected content
<!-- canon:realized-in: file:tests/integration/test_web_routes.py:TestMarketingPages -->
- [x] All tests use the real FastAPI app via `ASGITransport`

## 3. Admin Panel Integration Tests

<!-- canon:system:3 status:done -->

Test the admin panel routes which require `admin` role and exercise complex multi-store operations.

### Acceptance Criteria

- [x] Integration tests for at least 10 admin routes covering CRUD operations
<!-- canon:realized-in: file:tests/integration/test_admin_routes.py -->
- [x] Admin auth enforcement verified: redirect, 403, and success cases for each route
<!-- canon:realized-in: file:tests/integration/test_admin_routes.py:TestAdminAuthEnforcement -->
- [ ] Org suspend/reactivate flow tested end-to-end (state transitions verified)
- [ ] User deactivation tested: sessions revoked, API keys invalidated
- [ ] Audit log entries created for admin actions (verified via store query)
- [x] Tests use realistic mock stores (not empty mocks) with seed data
<!-- canon:realized-in: file:tests/integration/test_admin_routes.py -->

## 4. Billing & Webhook Integration Tests

<!-- canon:system:4 status:done -->

Test the billing routes and external webhook handlers through the full FastAPI stack.

### Acceptance Criteria

- [x] Billing route tests verify Stripe client interactions through the full stack
<!-- canon:realized-in: file:tests/integration/test_billing_routes.py:TestBillingRoutes -->
- [ ] BYOK key encryption/decryption tested end-to-end (store → encrypt → retrieve → decrypt)
- [x] Jira webhook tested: valid signature → processed, invalid → 401
<!-- canon:realized-in: file:tests/integration/test_billing_routes.py:TestJiraWebhook -->
- [x] Linear webhook tested: valid signature → processed, invalid → 401
<!-- canon:realized-in: file:tests/integration/test_billing_routes.py:TestLinearWebhook -->
- [x] Asana webhook tested: handshake challenge → correct response
<!-- canon:realized-in: file:tests/integration/test_billing_routes.py:TestAsanaWebhook -->
- [x] Unconfigured webhook endpoints return 503 with clear error message
<!-- canon:realized-in: file:tests/integration/test_billing_routes.py:TestUnconfiguredWebhooks -->
- [ ] Stripe webhook signature verification tested with real HMAC computation
- [ ] Stripe event handlers tested for subscription lifecycle (create, update, cancel)

## 5. MCP Server Integration Tests

<!-- canon:system:5 status:done -->

Test the MCP (Model Context Protocol) server mounted at `/mcp`, verifying tool execution through the HTTP transport layer.

### Acceptance Criteria

- [x] MCP tool listing returns all registered tools via HTTP transport
<!-- canon:realized-in: file:tests/integration/test_mcp.py:TestMcpToolListing -->
- [ ] Search tool tested end-to-end through HTTP (request → search index → response)
- [ ] Read tools (`get_spec`, `get_doc`) tested with realistic fixture data
- [x] Write tools tested with valid auth (API key) → success
<!-- canon:realized-in: file:tests/integration/test_mcp.py:TestMcpAuth::test_valid_api_key_accepted -->
- [x] Write tools tested without auth → 401
<!-- canon:realized-in: file:tests/integration/test_mcp.py:TestMcpAuth::test_missing_auth_rejected -->
- [x] MCP server gracefully handles missing optional dependencies
<!-- canon:realized-in: file:tests/integration/test_mcp.py:TestMcpToolListing -->

## 6. Ticket Sync Adapter Integration Tests

<!-- canon:system:6 status:done -->

Test the ticket sync adapters (Jira, Linear, GitHub Issues) with realistic HTTP-level mocks using `respx`, verifying the full adapter → HTTP → parse cycle rather than mocking at the adapter method level.

### Acceptance Criteria

- [ ] Jira adapter tested with `respx` HTTP-level mocks for create, update, get, search
- [ ] Linear adapter tested with `respx` HTTP-level mocks (GraphQL request/response)
- [x] GitHub Issues adapter tested with `respx` HTTP-level mocks for create, update, get
<!-- canon:realized-in: file:tests/integration/test_sync_adapters.py -->
- [x] Each adapter tested for error responses: 401, 404, 429
<!-- canon:realized-in: file:tests/integration/test_sync_adapters.py:TestGitHubAdapterErrors -->
- [x] Status mapping verified end-to-end: spec status → adapter → external status → adapter → spec status
<!-- canon:realized-in: file:tests/integration/test_sync_adapters.py:TestStatusRoundtrip -->
- [ ] Pagination tested for list/search operations across all adapters

## 7. E2E Workflow Tests

<!-- canon:system:7 status:done -->

Test the critical user journeys that span multiple subsystems. These are the "golden path" scenarios that verify Canon works as an integrated system, not just as isolated components.

### Acceptance Criteria

- [x] Spec-to-ticket flow tested end-to-end (push webhook → ticket creation → comment)
<!-- canon:realized-in: file:tests/integration/test_e2e_flows.py:TestPushWebhookFlow -->
- [x] PR analysis flow tested end-to-end (PR webhook → agent analysis → comment)
<!-- canon:realized-in: file:tests/integration/test_e2e_flows.py:TestPRAnalysisFlow -->
- [ ] Coverage update flow tested end-to-end (push webhook → delta → coverage update)
- [x] Auth-to-dashboard flow tested end-to-end (login → session → dashboard render)
<!-- canon:realized-in: file:tests/integration/test_e2e_flows.py:TestAuthToDashboardFlow -->
- [x] Each flow test mocks only external services (GitHub API, Anthropic, ticket providers) at the HTTP level
- [x] Flow tests verify side effects (store writes, API calls) not just HTTP responses
- [x] Flow tests run in <5 seconds each (no real network I/O)

## 8. Test Infrastructure Enhancements

<!-- canon:system:8 status:done -->

Extend the existing test infrastructure to support the broader integration test surface.

### Acceptance Criteria

- [x] `authed_app_client` fixture provides an authenticated session for any provider mode
<!-- canon:realized-in: file:tests/integration/conftest.py -->
- [x] `admin_app_client` fixture provides admin-level access
<!-- canon:realized-in: file:tests/integration/conftest.py -->
- [x] Seed data fixtures provide realistic org, user, repo, and spec data
<!-- canon:realized-in: file:tests/integration/conftest.py -->
- [x] Response assertion helpers for HTML content, JSON schema, and redirects
<!-- canon:realized-in: file:tests/integration/conftest.py -->
- [x] All new fixtures compose with existing `app_client` from `tests/integration/conftest.py`
- [x] Fixtures documented with docstrings showing usage patterns

## 9. CI Pipeline Integration

<!-- canon:system:9 status:done -->

Ensure all new integration tests run in CI without increasing total pipeline time beyond the 10-minute budget.

### Acceptance Criteria

- [x] New integration test files organized under `tests/integration/`
- [x] All new tests marked with `@pytest.mark.integration`
- [x] Integration tests run in a dedicated CI job parallel to unit tests
<!-- canon:realized-in: file:.github/workflows/ci.yml (existing integration-test job) -->
- [x] Total integration test suite completes in <30 seconds
- [x] No new test dependencies required beyond `httpx`, `respx`, `pytest-asyncio`
- [x] Integration test failures block PR merges

## 10. Onboarding & Tenant Isolation Tests

<!-- canon:system:10 status:done -->

Test new user onboarding flows, tenant isolation enforcement, session edge cases, API key auth, and error resilience — areas not covered by §2–§7 that were identified during implementation.

### Acceptance Criteria

- [x] New user with org → welcome page flow tested
<!-- canon:realized-in: file:tests/integration/test_onboarding_flows.py:TestNewUserWithOrg -->
- [x] New user without org → no-org page flow tested
<!-- canon:realized-in: file:tests/integration/test_onboarding_flows.py:TestNewUserNoOrg -->
- [x] Multi-org picker flow tested (choose-org, valid/invalid selection)
<!-- canon:realized-in: file:tests/integration/test_onboarding_flows.py:TestMultiOrgPicker -->
- [x] Logout → re-login org resolution tested (reproduces production bug)
<!-- canon:realized-in: file:tests/integration/test_onboarding_flows.py:TestLogoutReloginOrgLost -->
- [x] Tenant isolation: org mismatch returns 403 (API) or redirect (browser)
<!-- canon:realized-in: file:tests/integration/test_tenant_isolation.py -->
- [x] Suspended org access blocked at middleware
<!-- canon:realized-in: file:tests/integration/test_tenant_isolation.py:TestSuspendedOrg -->
- [x] Reserved org slugs bypass isolation (no-org, choose-org, setup, admin)
<!-- canon:realized-in: file:tests/integration/test_tenant_isolation.py:TestReservedOrgSlugs -->
- [x] Deactivated user session returns 403
<!-- canon:realized-in: file:tests/integration/test_session_edge_cases.py:TestDeactivatedUserSession -->
- [x] DB failure during auth check fails open (not 500)
<!-- canon:realized-in: file:tests/integration/test_session_edge_cases.py:TestDBFailureDuringAuth -->
- [x] Missing permissions fall back to read-only
<!-- canon:realized-in: file:tests/integration/test_session_edge_cases.py:TestPermissionFallback -->
- [x] API key auth: valid, expired, revoked, unknown, org mismatch, deactivated
<!-- canon:realized-in: file:tests/integration/test_api_key_auth.py -->
- [x] Profile and settings routes tested through auth chain
<!-- canon:realized-in: file:tests/integration/test_profile_settings.py -->
- [x] Error resilience: GitHub failures, missing services, admin store errors, webhook handler exceptions
<!-- canon:realized-in: file:tests/integration/test_error_resilience.py -->

## 11. Bug Fixes

<!-- canon:system:11 status:done -->

Bugs discovered and fixed during integration test implementation.

### 11.1 org_login not resolved from provider org memberships

The auth callback fetches `org_memberships` from the provider but never used them to set `org_login` when all other resolution methods failed. Users landing on `/app/no-org` after logout → re-login despite having valid org memberships.

**Fix:** Use first `org_memberships` entry as fallback for `org_login` in both the callback (`auth/routes.py`) and `dashboard_redirect` (`web/routes.py`).

### 11.2 `"setup"` missing from RESERVED_ORG_SLUGS

The `/app/setup/complete` route (GitHub App post-install redirect) was blocked by the auth middleware's org isolation check because `"setup"` was not in `RESERVED_ORG_SLUGS`.

**Fix:** Added `"setup"` to `RESERVED_ORG_SLUGS` in `auth/middleware.py`.

### Acceptance Criteria

- [x] org_login resolved from org_memberships when JWT and GitHub lookup both fail
<!-- canon:realized-in: file:src/canon/auth/routes.py -->
- [x] dashboard_redirect uses org_memberships as fallback before redirecting to /app/no-org
<!-- canon:realized-in: file:src/canon/web/routes.py -->
- [x] "setup" added to RESERVED_ORG_SLUGS
<!-- canon:realized-in: file:src/canon/auth/middleware.py -->
- [x] All three fixes verified by integration tests
<!-- canon:realized-in: file:tests/integration/test_onboarding_flows.py -->

## 12. Rollout Plan

<!-- canon:system:12 status:done -->

### Phase 1: Infrastructure (§8) ✓
### Phase 2: Web Routes (§2, §3) ✓
### Phase 3: External Integrations (§4, §5, §6) ✓
### Phase 4: E2E Flows (§7) ✓
### Phase 5: Onboarding, Security & Resilience (§10) ✓
### Phase 6: Bug Fixes (§11) ✓
