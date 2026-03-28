---
title: "Integration Testing"
status: done
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

<!-- canon:system:1 status:done -->

All existing tests are unit tests that mock external dependencies (GitHub API, Anthropic SDK, database). While comprehensive (965+ tests), they cannot catch issues like incorrect FastAPI route wiring, middleware ordering, serialization mismatches between the app and real GitHub payloads, or database query bugs.

**Related:** [#95](https://github.com/canonhq/canon/issues/95)

## 2. Webhook Handler Integration Tests

<!-- canon:system:2 status:done -->

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

- [x] Integration test suite using `httpx.AsyncClient` with the real FastAPI app
<!-- canon:realized-in:PR#118 file:tests/integration/conftest.py -->
<!-- canon:realized-in:PR#118 file:tests/integration/test_webhook.py -->
- [x] Tests for push, PR, and issue_comment webhook handlers
- [x] Tests verify the full request → handler → response chain (not just handler functions)
- [x] Webhook signature verification tested with real HMAC payloads
- [x] Tests use recorded GitHub webhook payloads as fixtures
- [x] External API calls mocked at the HTTP level (httpx mock, not service mock)
- [x] Integration tests run in CI alongside unit tests
<!-- canon:realized-in:PR#118 file:.github/workflows/ci.yml -->

<!-- canon:ticket:github:401 -->
## 3. GitHub API Client Integration Tests

<!-- canon:system:3 status:done -->

Test the GitHub API client (`github/client.py`) against a sandboxed environment to verify JWT generation, API call formatting, and response parsing.

### Acceptance Criteria

- [x] GitHub API client tested with realistic response fixtures
<!-- canon:realized-in: file:tests/integration/test_github_client.py:TestRealisticResponseFixtures -->
- [x] JWT generation and header formatting verified end-to-end
<!-- canon:realized-in: file:tests/integration/test_github_client.py:TestJWTGenerationAndAuthHeaders -->
- [x] Error handling tested for common GitHub API failures (rate limiting, 404, 500)
<!-- canon:realized-in: file:tests/integration/test_github_client.py:TestErrorHandling -->
- [x] Pagination handling tested with multi-page response fixtures
<!-- canon:realized-in: file:tests/integration/test_github_client.py:TestPagination -->

## 4. Resolved Questions

- **HTTP transport mocking vs dedicated test app:** Using `respx` to mock at the HTTP transport level, giving realistic fixture-based testing without requiring a live GitHub App.
- **Pytest marker:** Integration tests use `@pytest.mark.integration` and are deselected by default via `addopts = "-m 'not integration'"` in pyproject.toml.
- **Coverage vs speed:** 23 integration tests run in ~0.6s — fast enough to run alongside unit tests in CI when explicitly selected.
