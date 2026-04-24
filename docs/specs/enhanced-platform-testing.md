---
title: "Enhanced Platform Testing"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon-private
created: 2026-03-19
updated: 2026-03-19
tags: [testing, ci, infrastructure, oidc, oss, helm]
---

# Enhanced Platform Testing

Establish a robust testing ecosystem for Canon's platform that validates all deployment configurations, infrastructure models, and auth provider modes — ensuring conviction that changes work before they hit the public FOSS repo.

<!-- canon:ticket:github:231 -->
## 1. Background

<!-- canon:system:1 status:todo -->

<!-- canon:ticket:github:231 -->
Canon has 1,800+ unit tests with strong coverage of individual modules, but significant gaps in validating how the platform works as an assembled system. With the OIDC provider abstraction (PR #386) introducing a multi-provider auth world and the imminent OSS export of the auth/web/db modules, Canon now has four distinct deployment profiles with different auth configurations, secret shapes, and feature flags — none of which are tested end-to-end in CI.

### Current gaps

| Area | Current State | Risk |
|------|-------------|------|
| **Configuration matrix** | Tests run against one hardcoded config | Provider auto-detection bugs ship silently |
| **Auth integration** | All auth tests mock at function level | Middleware ordering, route wiring, session flow bugs invisible |
| **Helm template rendering** | `helm lint` only | Wrong env var names, missing secret mounts, broken conditionals |
| **Docker smoke tests** | CI builds image but never runs it | Import errors, missing deps, startup crashes caught only in staging |
| **OSS export validation** | Export script runs but output untested | Broken FOSS releases, missing modules, import failures |
| **Database migrations** | Migrations exist but untested | Schema drift, failed upgrades on real Postgres |

### Deployment profiles

| Profile | Auth | Database | Cron | Secrets |
|---------|------|----------|------|---------|
| **Production** | Auth0 (multi-tenant, orgs) | Neon Postgres | All enabled | Doppler → K8s Secrets |
| **Preview** | Auth0 (shared with production) | Shared Neon (read-only convention) | Disabled | Same as production |
| **Dev** | Auth0 (dev tenant) | Dev Neon | Disabled | DevSpace/Doppler |
| **OSS** | Generic OIDC / Zitadel / disabled | Self-hosted Postgres | Configurable | User-managed |

### Related specs

- `oidc-migration.md` — introduces the provider abstraction this testing spec validates
- `integration-testing.md` — partially implemented webhook integration tests; this spec supersedes its scope

<!-- canon:ticket:github:392 -->
## 2. Configuration Matrix Testing

<!-- canon:system:2 status:in_progress -->

<!-- canon:ticket:github:392 -->
Test that the Settings model and provider factory correctly handle all valid (and invalid) configuration combinations. These are fast, in-process tests with no external dependencies.

### 2.1 Settings Auto-Detection

Test the provider auto-detection logic introduced in PR #386:

```
AUTH_PROVIDER="" + Auth0 creds set     → Auth0Provider
AUTH_PROVIDER="" + OIDC creds set      → GenericOIDCProvider
AUTH_PROVIDER="" + no creds            → auth disabled
AUTH_PROVIDER="auth0"                  → Auth0Provider (explicit)
AUTH_PROVIDER="oidc"                   → GenericOIDCProvider (explicit)
AUTH_PROVIDER="unknown"               → ValueError
AUTH_PROVIDER="" + both Auth0 + OIDC   → Auth0Provider wins (backward compat)
```

### 2.2 Settings Property Validation

Test derived properties across configurations:
- `auth_enabled` returns correct value for all provider combinations
- `auth0_enabled` unchanged for backward compatibility
- `stripe_enabled`, `github_oauth_enabled` unaffected by auth changes

### 2.3 Configuration Profiles

Define reusable test fixtures representing each deployment profile:

```python
@pytest.fixture(params=["production", "oss_oidc", "oss_disabled", "dev"])
def config_profile(request) -> Settings:
    """Settings instance matching a real deployment profile."""
    ...
```

### Acceptance Criteria

- [x] Provider factory tested for all 7 auto-detection paths in §2.1
<!-- canon:realized-in:PR#388 file:tests/test_auth/test_config_matrix.py -->
- [ ] `auth_enabled` property tested for Auth0-only, OIDC-only, both, and neither configurations
- [ ] Explicit `auth_provider` override tested (auth0, oidc, unknown → error)
- [ ] Conflicting configuration test: both Auth0 and OIDC settings present, `AUTH_PROVIDER=""` → Auth0 wins
- [x] Reusable `config_profile` fixture created for production, oss_oidc, oss_disabled, and dev profiles
<!-- canon:realized-in:PR#388 file:tests/helpers/profiles.py -->
- [ ] All configuration tests run in <2 seconds (no I/O, no network)

<!-- canon:ticket:github:393 -->
## 3. Auth Integration Tests

<!-- canon:system:3 status:in_progress -->

<!-- canon:ticket:github:393 -->
Test the full authentication request cycle through the real FastAPI app, covering middleware, route handlers, session management, and permission resolution — for each auth provider mode.

### 3.1 Test Infrastructure

Build on the existing `tests/integration/conftest.py` pattern:

```python
@pytest.fixture
async def oidc_app_client() -> httpx.AsyncClient:
    """App client configured with a mock OIDC provider."""
    # Sets up app.state with GenericOIDCProvider + mock HTTP responses
    ...

@pytest.fixture
async def auth0_app_client() -> httpx.AsyncClient:
    """App client configured with Auth0Provider."""
    # Uses existing mock patterns but wired through provider abstraction
    ...

@pytest.fixture
async def noauth_app_client() -> httpx.AsyncClient:
    """App client with auth disabled (anonymous access)."""
    ...
```

### 3.2 Auth Flow Tests

For each provider mode, test the complete request flow:

**Login flow:**
1. `GET /auth/login` → 302 redirect to provider's authorization endpoint
2. `GET /auth/callback?code=...` → exchanges code, creates session, redirects to `/app`
3. Verify session cookie set, user upserted in mock store

**Protected routes:**
1. Unauthenticated `GET /app/` → 302 redirect to `/auth/login`
2. Authenticated `GET /app/` → 200 with user context
3. API key `GET /api/...` with `Authorization: Bearer sw_...` → 200

**Permission resolution:**
1. Auth0 mode: permissions from JWT claims
2. OIDC mode: permissions from `users.role` → `ROLE_PERMISSIONS` mapping
3. First-user bootstrap: first login gets admin role

**Logout flow:**
1. `GET /auth/logout` → clears session, redirects to provider's end_session_endpoint (if available)
2. OIDC without end_session_endpoint → clears session, redirects to `/`

**Device auth flow:**
1. `POST /auth/device/code` → returns device code from provider
2. `POST /auth/device/token` → polls provider for token
3. Provider without device_authorization_endpoint → 501

### 3.3 Middleware Integration

Test middleware ordering and behavior:
- Auth middleware runs before route handlers (not just tested in isolation)
- Org isolation enforced in Auth0 mode, skipped in OIDC single-tenant mode
- Session refresh intercepts expired sessions correctly
- CORS headers set correctly for API endpoints

### Acceptance Criteria

- [x] Auth integration test fixtures for 3 provider modes: auth0, oidc, disabled
<!-- canon:realized-in:PR#388 file:tests/integration/test_auth_integration.py -->
- [x] Login → callback → session flow tested end-to-end through FastAPI for Auth0 and OIDC modes
- [ ] Protected route access tested: unauthenticated redirect, authenticated success, API key bypass
- [ ] Permission resolution tested: JWT claims (Auth0), server-side role (OIDC), fallback (viewer)
- [ ] First-user bootstrap tested: first login → admin, second login → editor
- [ ] Logout tested with and without provider `end_session_endpoint`
- [ ] Device auth tested: supported provider (200), unsupported provider (501)
- [ ] Middleware ordering verified: auth runs before handlers, org isolation conditional on Auth0
- [ ] Token refresh integration tested: expired access token + valid refresh token → new session
- [ ] All integration tests marked with `@pytest.mark.integration`

<!-- canon:ticket:github:394 -->
## 4. Helm Template Rendering Tests

<!-- canon:system:4 status:in_progress -->

<!-- canon:ticket:github:394 -->
Validate that Helm chart templates render correct Kubernetes manifests for each deployment profile. Uses `helm template` to render locally — no cluster required.

### 4.1 Test Approach

Write a pytest test module that shells out to `helm template` with each values overlay and asserts on the rendered YAML:

```python
def test_production_deployment_mounts_auth0_secret():
    """Production values should mount the Auth0 secret."""
    manifests = helm_template("values-production.yaml")
    deployment = find_manifest(manifests, kind="Deployment")
    env_from = deployment["spec"]["template"]["spec"]["containers"][0]["envFrom"]
    secret_names = [e["secretRef"]["name"] for e in env_from if "secretRef" in e]
    assert "canon-auth0" in secret_names

def test_oss_oidc_deployment_mounts_oidc_secret():
    """OSS with OIDC values should mount the OIDC secret."""
    manifests = helm_template("values.yaml", set_values={"secrets.oidc.issuer": "https://idp.example.com", ...})
    ...
```

### 4.2 Test Categories

**Secret mounting:** Verify each deployment profile mounts the correct secrets (Auth0, OIDC, GitHub, Anthropic, Neon, GCP, PostHog).

**Conditional resources:** Verify resources that should/shouldn't exist:
- Production: all CronJobs enabled, ingress enabled
- Preview: all CronJobs disabled, ingress enabled
- OSS default: no auth secrets, no cloud secrets

**Environment variables:** Verify the rendered Deployment has correct env vars for each profile.

**Zitadel subchart:** When `zitadel.enabled=true`, verify the setup Job exists and references the correct secret.

### 4.3 CI Integration

Add a `helm-template-test` job to CI that runs these tests. Faster than `helm lint` since it doesn't need chart dependency resolution.

### Acceptance Criteria

- [x] `helm template` wrapper utility that renders templates with arbitrary values overlays
<!-- canon:realized-in:PR#388 file:tests/helpers/helm.py -->
- [ ] YAML parser that extracts specific manifests by kind/name from rendered output
- [x] Secret mounting tests for production (Auth0), OSS-OIDC, and OSS-disabled profiles
<!-- canon:realized-in:PR#388 file:tests/test_helm/test_template_rendering.py -->
- [ ] CronJob conditional tests: enabled in production, disabled in preview
- [ ] Ingress tests: correct hostname and TLS for production and preview
- [ ] OIDC secret template test: created when `secrets.oidc.issuer` set, absent when empty
- [x] Zitadel setup Job test: exists when `zitadel.enabled=true`, absent when false
<!-- canon:realized-in:PR#390 file:tests/test_helm/test_template_rendering.py -->
- [ ] Environment variable tests: PORT, LOG_LEVEL, ENVIRONMENT set correctly per profile
- [ ] No `helm template` errors for any values combination (production, preview, dev, bare defaults)
- [ ] Tests integrated into CI as a job parallel to existing `helm-lint`

<!-- canon:ticket:github:395 -->
## 5. Docker Smoke Tests

<!-- canon:system:5 status:in_progress -->

<!-- canon:ticket:github:395 -->
Build the Docker image and verify it starts, responds to health checks, and handles basic API requests. Catches import errors, missing dependencies, and startup failures before deployment.

### 5.1 Smoke Test Script

```bash
#!/usr/bin/env bash
# scripts/docker-smoke-test.sh
set -euo pipefail

IMAGE="${1:-canon:ci}"
CONTAINER_NAME="canon-smoke-$$"

# Start with minimal config (no auth, no DB)
docker run -d --name "$CONTAINER_NAME" \
  -p 3099:3000 \
  -e GH_WEBHOOK_SECRET=test \
  -e GH_APP_ID=test \
  -e GH_PRIVATE_KEY=test \
  -e GH_INSTALLATION_ID=test \
  "$IMAGE"

# Wait for health
for i in $(seq 1 30); do
  if curl -sf http://localhost:3099/healthz > /dev/null 2>&1; then
    echo "Health check passed"
    break
  fi
  sleep 1
done

# Basic API assertions
curl -sf http://localhost:3099/healthz | grep -q '"status":"ok"'
curl -sf -o /dev/null -w '%{http_code}' http://localhost:3099/ | grep -q '200'

# Cleanup
docker stop "$CONTAINER_NAME" && docker rm "$CONTAINER_NAME"
```

### 5.2 Auth-Mode Smoke Variants

Run the smoke test in multiple configurations:
1. **No auth** — verify anonymous access works, `/app/` accessible without redirect
2. **Auth enabled (mock)** — verify `/app/` redirects to login, `/healthz` still accessible
3. **OSS image** — build the OSS Dockerfile, verify it starts and responds

### 5.3 CI Integration

Add after the existing `docker build` step in CI:

```yaml
- name: Docker smoke test
  run: scripts/docker-smoke-test.sh canon:ci
```

### Acceptance Criteria

- [x] `scripts/docker-smoke-test.sh` builds and runs the Docker image with minimal config
<!-- canon:realized-in:PR#388 file:scripts/docker-smoke-test.sh -->
- [ ] Health check endpoint (`/healthz`) responds with 200 and `{"status":"ok"}`
- [ ] Root endpoint (`/`) responds with 200
- [ ] Webhook endpoint (`/webhook`) responds with 405 for GET (proves route is wired)
- [ ] Container starts within 30 seconds
- [x] Smoke test runs in CI after Docker build step
<!-- canon:realized-in:PR#388 file:.github/workflows/ci.yml -->
- [ ] Smoke test failure fails the CI pipeline
- [ ] Auth-disabled smoke: `/app/` accessible without auth
- [ ] Container exits cleanly on SIGTERM (graceful shutdown)

<!-- canon:ticket:github:396 -->
## 6. OSS Export Validation

<!-- canon:system:6 status:in_progress -->

<!-- canon:ticket:github:396 -->
Validate that the OSS export script produces a working, self-contained repository that builds, passes tests, and runs.

### 6.1 Export + Build Pipeline

```bash
# 1. Run export
./scripts/export-oss.sh . /tmp/canon-oss

# 2. Verify critical files exist
test -f /tmp/canon-oss/src/canon/auth/providers/protocol.py
test -f /tmp/canon-oss/src/canon/auth/providers/generic_oidc.py
test ! -f /tmp/canon-oss/src/canon/auth/providers/auth0.py  # cloud-only excluded

# 3. Install dependencies
cd /tmp/canon-oss && uv sync --extra dev

# 4. Run linter
uv run ruff check

# 5. Run tests
uv run pytest

# 6. Build Docker image
docker build -t canon-oss:test .

# 7. Smoke test the OSS image
scripts/docker-smoke-test.sh canon-oss:test
```

### 6.2 Import Integrity

Verify that importing the exported modules doesn't fail:

```python
def test_oss_imports():
    """All OSS-exported modules should be importable."""
    import canon.parser
    import canon.config
    import canon.cli
    import canon.sync
    import canon.agent
    # Post-PR#386: auth modules included
    import canon.auth.providers.protocol
    import canon.auth.providers.generic_oidc
    import canon.auth.routes
    import canon.auth.middleware
```

### 6.3 Cloud-Only Exclusion

Verify cloud-only files are absent from the export:

```python
CLOUD_ONLY_FILES = [
    "src/canon/auth/providers/auth0.py",
    "src/canon/auth/management.py",
    "docs/specs/canon-rebrand.md",
    "docs/specs/managed-cloud-pricing.md",
    "docs/specs/auth-hardening.md",
    "chart/canon/values-production.yaml",
    "chart/canon/values-dev.yaml",
]

def test_cloud_only_excluded(oss_export_dir):
    for path in CLOUD_ONLY_FILES:
        assert not (oss_export_dir / path).exists(), f"Cloud-only file leaked: {path}"
```

### 6.4 CI Integration

Add as a new CI job that runs after unit tests pass:

```yaml
oss-validation:
  needs: check
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - run: .github/scripts/export-oss.sh . /tmp/canon-oss
    - run: cd /tmp/canon-oss && uv sync --extra dev && uv run pytest
    - run: cd /tmp/canon-oss && docker build -t canon-oss:ci .
```

### Acceptance Criteria

- [ ] CI job exports OSS, installs deps, runs linter, runs tests — all green
- [x] Auth module files present in export: `providers/protocol.py`, `providers/generic_oidc.py`, `routes.py`, `middleware.py`, `deps.py`, `jwt.py`
<!-- canon:realized-in:PR#388 file:tests/test_oss_export.py -->
<!-- canon:realized-in:PR#509 file:.github/scripts/export-oss.sh -->
- [x] Cloud-only files absent: `providers/auth0.py`, `management.py`
- [ ] OSS tests pass without cloud extras installed (no `authlib` needed for CLI/parser tests)
- [ ] OSS Docker image builds and passes smoke test
- [ ] Import integrity test verifies all exported modules are importable
- [ ] Export validation runs on every PR (catches export breakage early)

<!-- canon:ticket:github:397 -->
## 7. Database Migration Testing

<!-- canon:system:7 status:in_progress -->

<!-- canon:ticket:github:537 -->
Test Alembic migrations against a real PostgreSQL instance to verify they apply cleanly, handle edge cases, and are reversible.

### 7.1 Test Infrastructure

Use a disposable Postgres container for migration tests:

```python
@pytest.fixture(scope="session")
def postgres_url():
    """Start a Postgres container and return the connection URL."""
    # Option A: testcontainers-python
    # Option B: pytest-postgresql
    # Option C: Docker compose service in CI
    ...
```

### 7.2 Migration Tests

**Forward migration chain:**
```python
def test_migrations_apply_cleanly(postgres_url):
    """All migrations apply from empty database to head."""
    alembic_cfg = make_config(postgres_url)
    command.upgrade(alembic_cfg, "head")
    # Verify tables exist
    ...

def test_oidc_rename_migration(postgres_url):
    """0002_oidc_rename correctly renames Auth0 columns."""
    alembic_cfg = make_config(postgres_url)
    command.upgrade(alembic_cfg, "0001")
    # Insert test data with auth0_sub
    ...
    command.upgrade(alembic_cfg, "0002")
    # Verify data is now in oidc_sub column
    ...
```

**Downgrade (if supported):**
```python
def test_oidc_rename_downgrade(postgres_url):
    """0002_oidc_rename can be reversed."""
    alembic_cfg = make_config(postgres_url)
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0001")
    # Verify auth0_sub column is back
    ...
```

**Idempotency:**
```python
def test_baseline_on_existing_schema(postgres_url):
    """Running baseline migration on an already-initialized DB doesn't fail."""
    ...
```

### 7.3 CI Integration

Migration tests require Postgres, so they run in the `integration-test` CI job with a Postgres service container:

```yaml
integration-test:
  services:
    postgres:
      image: postgres:16
      env:
        POSTGRES_DB: canon_test
        POSTGRES_USER: canon
        POSTGRES_PASSWORD: test
      ports:
        - 5432:5432
```

### Acceptance Criteria

- [x] Migration test fixture provides a disposable Postgres instance
<!-- canon:realized-in:PR#388 file:tests/test_db/test_migrations.py -->
- [x] Forward migration test: all migrations apply from empty DB to head without errors
- [ ] OIDC rename migration test: data migrated correctly (`auth0_sub` → `oidc_sub`)
- [ ] Role column migration test: `users.role` column added with default `'editor'`
- [ ] Downgrade test: `0002_oidc_rename` reversible (if downgrade implemented)
- [x] Baseline idempotency: running baseline on existing schema doesn't fail
<!-- canon:realized-in:PR#466 file:src/canon/db/migrations/versions/0002_oidc_rename.py -->
- [ ] Migration tests run in CI with Postgres service container
- [ ] Migration tests marked with `@pytest.mark.integration`

<!-- canon:ticket:github:398 -->
## 8. CI Pipeline Updates

<!-- canon:system:8 status:in_progress -->

<!-- canon:ticket:github:538 -->
Update the GitHub Actions CI pipeline to orchestrate all new test types alongside existing ones, keeping total CI time under 10 minutes.

### 8.1 Updated Job Graph

```
check (lint + unit tests + Docker build)
  ├── integration-test (auth integration + migration tests, needs Postgres)
  ├── helm-template-test (Helm rendering validation)
  ├── oss-validation (export + lint + test + Docker build)
  └── coverage-report (unchanged)
```

### 8.2 New Jobs

**`helm-template-test`** — parallel with integration-test:
```yaml
helm-template-test:
  runs-on: ubuntu-latest
  needs: check
  steps:
    - uses: actions/checkout@v4
    - uses: azure/setup-helm@v4
    - uses: astral-sh/setup-uv@v4
    - run: uv sync --extra dev
    - run: uv run pytest tests/test_helm/ -v
```

**`oss-validation`** — parallel with integration-test:
```yaml
oss-validation:
  runs-on: ubuntu-latest
  needs: check
  steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v4
    - run: .github/scripts/export-oss.sh . /tmp/canon-oss
    - run: cd /tmp/canon-oss && uv sync --extra dev && uv run ruff check && uv run pytest
```

**Docker smoke test** — added to existing `check` job after Docker build:
```yaml
- name: Docker smoke test
  run: scripts/docker-smoke-test.sh canon:ci
```

### 8.3 Integration Test Job Update

Add Postgres service container and migration tests to the existing `integration-test` job.

### Acceptance Criteria

- [x] `helm-template-test` job added to CI, runs parallel to integration-test
- [x] `oss-validation` job added to CI, runs parallel to integration-test
- [ ] Docker smoke test step added after Docker build in `check` job
- [ ] Integration test job has Postgres service container for migration tests
- [ ] All new jobs fail the pipeline on failure (not `continue-on-error`)
- [ ] Total CI time under 10 minutes for a typical PR
- [ ] Coverage report job unchanged (still combines unit + integration)

<!-- canon:ticket:github:399 -->
## 9. Test Utilities and Fixtures

<!-- canon:system:9 status:in_progress -->

<!-- canon:ticket:github:539 -->
Create shared test infrastructure that makes writing configuration-aware tests easy and consistent.

### 9.1 Configuration Profile Fixtures

```python
# tests/conftest.py additions

PROFILES = {
    "production": Settings(
        auth0_domain="test.auth0.com",
        auth0_client_id="test-id",
        auth0_client_secret="test-secret",
        auth0_audience="https://api.canonhq.co",
        auth0_orgs_enabled=True,
        database_url="postgresql://...",
        environment="production",
    ),
    "oss_oidc": Settings(
        oidc_issuer="https://idp.example.com",
        oidc_client_id="canon-app",
        oidc_client_secret="secret",
        environment="production",
    ),
    "oss_disabled": Settings(
        environment="development",
    ),
    "dev": Settings(
        auth0_domain="dev.auth0.com",
        auth0_client_id="dev-id",
        auth0_client_secret="dev-secret",
        environment="development",
    ),
}
```

### 9.2 Mock OIDC Provider

A test helper that simulates an OIDC provider's HTTP responses:

```python
class MockOIDCServer:
    """Simulates an OIDC provider for integration testing."""

    def __init__(self, issuer: str = "https://idp.example.com"):
        self.issuer = issuer

    def discovery_document(self) -> dict: ...
    def jwks(self) -> dict: ...
    def token_response(self, **claims) -> dict: ...
    def id_token(self, sub: str, email: str, **extra) -> str: ...
```

### 9.3 Helm Template Helper

```python
def helm_template(
    *values_files: str,
    set_values: dict[str, str] | None = None,
    chart_dir: str = "chart/canon",
) -> list[dict]:
    """Run helm template and return parsed YAML manifests."""
    ...
```

### Acceptance Criteria

- [ ] `PROFILES` dict with at least 4 deployment configurations in `conftest.py`
- [x] `MockOIDCServer` helper produces valid discovery documents, JWKS, and token responses
<!-- canon:realized-in:PR#388 file:tests/helpers/oidc.py -->
- [ ] `MockOIDCServer` generates real JWTs signed with a test RSA key (not just dicts)
- [x] `helm_template()` helper runs `helm template` and returns parsed YAML manifests
- [ ] `find_manifest(manifests, kind=..., name=...)` helper for extracting specific resources
- [ ] All helpers are importable from `tests/` without external service dependencies
- [ ] Helpers documented with docstrings and usage examples

<!-- canon:ticket:github:400 -->
## 10. Rollout Plan

<!-- canon:system:10 status:todo -->

<!-- canon:ticket:github:540 -->
### Phase 1: Foundation (this PR)

1. Create test utilities and fixtures (§9)
2. Configuration matrix tests (§2)
3. Docker smoke test script + CI integration (§5)

### Phase 2: Auth Integration

4. Auth integration test fixtures and login flow tests (§3)
5. Permission resolution and middleware tests (§3)
6. Update integration-test CI job with Postgres service (§8)

### Phase 3: Infrastructure Validation

7. Helm template rendering tests (§4)
8. Database migration tests (§7)
9. Add helm-template-test CI job (§8)

### Phase 4: OSS Validation

10. OSS export validation tests (§6)
11. Add oss-validation CI job (§8)
12. End-to-end validation: export → build → smoke test

### Phase 5: Polish

13. Update existing `integration-testing.md` spec status (superseded)
14. Coverage targets: aim for integration tests to cover auth + db + web modules
15. Document test infrastructure in `tests/README.md`
