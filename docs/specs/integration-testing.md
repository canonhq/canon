---
title: "Integration Testing"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-02-26
tags: [testing, integration, ci]
---

# Integration Testing

Add integration tests that verify end-to-end behavior through the actual FastAPI application and against real (sandboxed) services, complementing the existing unit test suite.

## 1. Background

<!-- specwright:system:1 status:done -->

All existing tests are unit tests that mock external dependencies (GitHub API, Anthropic SDK, database). While comprehensive (965+ tests), they cannot catch issues like incorrect FastAPI route wiring, middleware ordering, serialization mismatches between the app and real GitHub payloads, or database query bugs.

**Related:** [#95](https://github.com/canonhq/canon/issues/95)

## 2. Webhook Handler Integration Tests

<!-- specwright:system:2 status:done -->
<!-- specwright:ticket:github:95 -->

Test webhook handlers through the full FastAPI request/response cycle using `httpx.AsyncClient` with the real app instance.

### 2.1 Test Categories

- **Push events:** Verify spec change detection, ticket sync triggering, and comment posting through the full handler chain
- **PR events:** Verify PR analysis flow from webhook receipt through Claude analysis to GitHub comment creation
- **Issue comment events:** Verify command parsing and response through the full handler
- **Signature verification:** Verify HMAC validation with real webhook payloads

### 2.2 Test Infrastructure

- Use `httpx.AsyncClient(app=app)` for in-process HTTP testing
- Use recorded/fixtures GitHub webhook payloads (sanitized from real events)
- Mock only external network calls (GitHub API, Anthropic) at the HTTP level (not at the service layer)

### Acceptance Criteria

- [ ] Integration test suite using `httpx.AsyncClient` with the real FastAPI app
<!-- specwright:realized-in:PR#118 file:tests/integration/conftest.py -->
<!-- specwright:realized-in:PR#118 file:tests/integration/test_webhook.py -->
- [ ] Tests for push, PR, and issue_comment webhook handlers
- [ ] Tests verify the full request → handler → response chain (not just handler functions)
- [ ] Webhook signature verification tested with real HMAC payloads
- [ ] Tests use recorded GitHub webhook payloads as fixtures
- [ ] External API calls mocked at the HTTP level (httpx mock, not service mock)
- [ ] Integration tests run in CI alongside unit tests
<!-- specwright:realized-in:PR#118 file:.github/workflows/ci.yml -->

## 3. GitHub API Client Integration Tests

<!-- canon:system:3 status:in_progress -->
<!-- specwright:ticket:github:95 -->

Test the GitHub API client (`github/client.py`) against a sandboxed environment to verify JWT generation, API call formatting, and response parsing.

### Acceptance Criteria

- [ ] GitHub API client tested with realistic response fixtures
- [ ] JWT generation and header formatting verified end-to-end
- [ ] Error handling tested for common GitHub API failures (rate limiting, 404, 500)
- [ ] Pagination handling tested with multi-page response fixtures

## 4. Open Questions

- Should we use a dedicated test GitHub App installation for integration tests, or mock at the HTTP transport level?
- Should integration tests have their own pytest marker (`@pytest.mark.integration`) for selective execution?
- What's the right balance between integration test coverage and test suite speed?
