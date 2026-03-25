---
title: "OIDC Migration: From Auth0 to Open-Source Auth"
status: in-progress
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-03-18
updated: 2026-03-20
tags: [auth, oidc, oss, infrastructure, security]
---

# OIDC Migration: From Auth0 to Open-Source Auth

Replace Canon's Auth0 dependency with a generic OIDC provider abstraction. Cloud stays on Auth0. OSS ships with bring-your-own OIDC support and an optional bundled Zitadel instance for teams without an existing identity provider.

## 1. Background

<!-- canon:system:1 status:done -->

Canon currently authenticates web users via Auth0 Universal Login, validates JWTs against Auth0's JWKS endpoint, and uses Auth0 Organizations for multi-tenant isolation. Auth0 is deeply integrated across ~35 files with ~185 references.

This creates three problems:

- **Self-hosters need Auth0.** Anyone deploying Canon on their own infrastructure must create an Auth0 account, configure an application, set up social connections, and enable device auth grants — all before web login works. Auth0 has a free tier (7,500 MAU) but no Organizations support on free plans.
- **The web platform isn't in OSS.** The `auth/`, `db/`, `main.py`, and `web/` modules are excluded from the OSS export. Self-hosters run closed-source server code. Opening the auth module requires decoupling it from Auth0.
- **CLI device auth couples to the cloud.** The `canon login` device authorization flow proxies through Canon's backend to Auth0. An OSS user running Canon locally has no reason to depend on a cloud auth flow.

### What's already provider-agnostic

Several subsystems require no changes:

- **API keys** (`sw_` prefix, SHA-256 hash) — no OIDC involvement
- **MCP auth** — API key only
- **GitHub OAuth** — separate OAuth flow for web editor repo access
- **Session store** — generic hash-based refresh token rotation
- **Permission model** — `Permission` enum + `require_permission()` dependency
- **Auth middleware** — checks session or Bearer, doesn't care about provider
- **Frontend** — no Auth0 SDK; reads server-injected `window.__CANON__`; one label change needed

### Deployment model split

| | Cloud (canon-private) | OSS |
|---|---|---|
| **Tenancy** | Multi-tenant (Auth0 Organizations) | Single-tenant |
| **Auth provider** | Auth0 (unchanged) | Bring-your-own OIDC or bundled Zitadel |
| **RBAC source** | JWT claims from Auth0 RBAC | Server-side `users.role` → `ROLE_PERMISSIONS` |
| **Org membership** | Auth0 Management API | N/A (one org per deployment) |
| **Device auth** | Auth0 device grant | Provider-dependent (fallback to browser/API-key) |

## 2. Provider Abstraction Layer

<!-- canon:system:2 status:done -->

Introduce an `OIDCProvider` protocol that all auth code programs against. Auth0 becomes one implementation among several.

### 2.1 Provider Protocol

```python
class OIDCProvider(Protocol):
    """Minimal interface for any OIDC-compliant auth provider."""

    async def get_login_url(self, *, redirect_uri: str, state: str,
                            org_hint: str = "") -> str: ...

    async def exchange_code(self, *, code: str,
                            redirect_uri: str) -> TokenSet: ...

    async def refresh_tokens(self, *, refresh_token: str) -> TokenSet: ...

    async def get_jwks_uri(self) -> str: ...

    async def get_logout_url(self, *, return_to: str) -> str | None: ...

    # Optional capabilities — not all providers support these
    async def get_device_code(self) -> DeviceCodeResponse | None: ...
    async def poll_device_token(self, device_code: str) -> TokenSet | Pending: ...
    async def get_user_orgs(self, user_id: str) -> list[OrgInfo]: ...
```

### 2.2 Provider Implementations

| Provider | Scope | Multi-tenant | Device Auth | Management API |
|----------|-------|-------------|-------------|----------------|
| `Auth0Provider` | Cloud only | Yes (Auth0 Organizations) | Yes | Yes (`/api/v2/`) |
| `GenericOIDCProvider` | OSS + Cloud | No (single-tenant) | Optional (discovery-based) | No |
| `ZitadelProvider` | Future cloud | Yes (Zitadel Organizations) | Yes | Yes (gRPC + REST) |

### 2.3 File Structure

```
src/canon/auth/
  providers/
    __init__.py          # Factory: settings → provider instance
    protocol.py          # OIDCProvider protocol + TokenSet/DeviceCodeResponse models
    auth0.py             # Auth0 implementation (cloud-only, excluded from OSS export)
    generic_oidc.py      # Discovery-based OIDC (OSS default)
```

### Acceptance Criteria

- [x] `OIDCProvider` protocol defined in `auth/providers/protocol.py` with all methods above
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/protocol.py:51-73 -->
- [x] `TokenSet` model includes `access_token`, `id_token`, `refresh_token`, `expires_in`
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/protocol.py:9-16 -->
- [x] `DeviceCodeResponse` model includes `device_code`, `user_code`, `verification_uri`, `interval`, `expires_in`
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/protocol.py:19-28 -->
- [x] Provider factory in `auth/providers/__init__.py` selects implementation based on `settings.auth_provider`
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/__init__.py:12-39 -->
- [x] All auth route handlers use provider protocol, not direct Auth0 calls
<!-- canon:realized-in:PR#386 file:src/canon/auth/routes.py file:src/canon/auth/device_routes.py file:src/canon/auth/refresh_routes.py -->
- [x] Existing Auth0 behavior preserved exactly when `auth_provider = "auth0"`
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/auth0.py -->

## 3. Generic OIDC Provider

<!-- canon:system:3 status:done -->

Implement a discovery-based OIDC provider that works with any compliant identity provider (Okta, Keycloak, Zitadel, Google Workspace, Entra ID, etc.) using the `.well-known/openid-configuration` endpoint.

### 3.1 Discovery-Based Configuration

The provider fetches all endpoints from the issuer's discovery document:

```python
# Only 3 required settings (4 with optional audience)
OIDC_ISSUER=https://your-idp.example.com
OIDC_CLIENT_ID=...
OIDC_CLIENT_SECRET=...
OIDC_AUDIENCE=              # optional, for API-specific tokens
```

Discovered endpoints used:
- `authorization_endpoint` — login redirect
- `token_endpoint` — code exchange, refresh, device token polling
- `jwks_uri` — JWT validation
- `end_session_endpoint` — logout (optional, graceful fallback)
- `device_authorization_endpoint` — CLI device auth (optional)

### 3.2 Single-Tenant Simplifications

For OSS single-tenant deployments:

- **No org isolation.** Middleware skips org path enforcement. All users belong to one implicit org.
- **Server-side RBAC.** Permissions come from `users.role` column mapped via `ROLE_PERMISSIONS`, not JWT claims. The OIDC token only provides identity (`sub`, `email`, `name`).
- **First-user bootstrap.** First user to log in when the users table is empty auto-receives `admin` role. Subsequent users default to `editor`.
- **No Management API.** No org membership discovery needed.

### 3.3 Login Flow

```
User → GET /auth/login
     → 302 to provider's authorization_endpoint
     → Provider authenticates user
     → 302 back to GET /auth/callback?code=...
     → Exchange code at token_endpoint
     → Extract sub/email/name from id_token
     → Upsert user in DB (first user = admin)
     → Set session
     → 302 to /app
```

### 3.4 Device Auth (CLI)

If the provider's discovery document includes `device_authorization_endpoint`:
- `POST /auth/device/code` proxies to the provider's device authorization endpoint
- `POST /auth/device/token` polls the provider's token endpoint with `grant_type=urn:ietf:params:oauth:grant-type:device_code`

If not supported:
- `canon login --api-key <key>` works (API keys are provider-agnostic)
- `canon login --browser` opens authorization code flow with `http://localhost:<port>/callback` redirect (like `gh auth login --web`)

### 3.5 Logout

If provider advertises `end_session_endpoint` in discovery:
- Clear local session, redirect to provider's end_session_endpoint with `post_logout_redirect_uri`

If not:
- Clear local session, redirect to `/`. User stays logged into IDP but is logged out of Canon.

### Acceptance Criteria

- [x] `GenericOIDCProvider` implements `OIDCProvider` protocol using `.well-known/openid-configuration` discovery
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/generic_oidc.py:18-232 -->
- [x] Login works with 3 env vars: `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`
<!-- canon:realized-in:PR#386 file:src/canon/settings.py:104-106 -->
- [x] JWT validation uses discovered `jwks_uri`, not hardcoded domain
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/generic_oidc.py:71 file:src/canon/auth/jwt.py:48 -->
- [x] Refresh tokens work via standard `grant_type=refresh_token` to discovered `token_endpoint`
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/generic_oidc.py:114-135 -->
- [x] Device auth attempted via discovered `device_authorization_endpoint`; returns `None` if endpoint absent
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/generic_oidc.py:153-186 -->
- [x] Logout uses discovered `end_session_endpoint` or falls back to local-only session clear
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/generic_oidc.py:141-151 file:src/canon/auth/routes.py:279-289 -->
- [x] First user to log in receives `admin` role; subsequent users default to `editor`
<!-- canon:realized-in:PR#386 file:src/canon/db/user_store.py:101-116 file:src/canon/auth/routes.py:162-175 -->
- [x] Single-tenant mode: no org path enforcement in middleware, no org resolution in JWT validation
<!-- canon:realized-in:PR#461 file:src/canon/auth/routes.py -->
<!-- canon:realized-in:PR#386 file:src/canon/auth/middleware.py:96-127 file:src/canon/auth/jwt.py:101-140 -->
- [ ] Provider tested against at least Zitadel, Keycloak, and one commercial provider (Okta or Google Workspace)

## 4. Settings Refactor

<!-- canon:system:4 status:done -->

Add generic OIDC settings alongside existing Auth0 settings for backward compatibility during migration.

### 4.1 New Settings

```python
# Generic OIDC (OSS)
auth_provider: str = ""           # "oidc", "auth0", "zitadel", or "" (disabled)
oidc_issuer: str = ""             # https://your-idp.example.com
oidc_client_id: str = ""
oidc_client_secret: str = ""
oidc_audience: str = ""           # optional
oidc_scopes: str = "openid email profile"
```

### 4.2 Backward Compatibility

When `auth_provider` is empty:
- If `auth0_domain` + `auth0_client_id` + `auth0_client_secret` are set → use `Auth0Provider` (existing behavior)
- If `oidc_issuer` + `oidc_client_id` + `oidc_client_secret` are set → use `GenericOIDCProvider`
- If neither → auth disabled (dev mode, anonymous access)

The `auth0_*` settings remain functional. No breaking change for existing deployments.

### 4.3 Auth Enabled Property

```python
@property
def auth_enabled(self) -> bool:
    """True if any auth provider is configured."""
    return self.auth0_enabled or bool(
        self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret
    )
```

### Acceptance Criteria

- [x] New `auth_provider`, `oidc_issuer`, `oidc_client_id`, `oidc_client_secret`, `oidc_audience`, `oidc_scopes` settings added
<!-- canon:realized-in:PR#386 file:src/canon/settings.py:103-108 -->
- [x] `auth_enabled` property returns True for either Auth0 or generic OIDC configuration
<!-- canon:realized-in:PR#386 file:src/canon/settings.py:79-81 -->
- [x] Existing `auth0_*` settings continue to work without changes
<!-- canon:realized-in:PR#386 file:src/canon/settings.py:55-62 -->
<!-- canon:realized-in:PR#461 file:chart/canon/values.yaml -->
- [x] Provider auto-detection: Auth0 settings → Auth0Provider; OIDC settings → GenericOIDCProvider
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/__init__.py:20-27 -->
- [x] Explicit `auth_provider` setting overrides auto-detection
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/__init__.py:18 -->

## 5. Database Migration

<!-- canon:system:5 status:done -->

Rename Auth0-specific column names to generic OIDC terminology.

### 5.1 Schema Changes

```sql
-- users table: rename subject identifier
ALTER TABLE users RENAME COLUMN auth0_sub TO oidc_sub;

-- gh_installations table: rename org identifier
ALTER TABLE gh_installations RENAME COLUMN auth0_org_id TO oidc_org_id;
DROP INDEX IF EXISTS idx_gh_installations_auth0_org_id;
CREATE INDEX idx_gh_installations_oidc_org_id ON gh_installations(oidc_org_id) WHERE oidc_org_id != '';

-- users table: add role for server-side RBAC (single-tenant)
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'editor';
```

### 5.2 Code Updates

All references to `auth0_sub` in Python code rename to `oidc_sub`:
- `user_store.py`: `upsert_user()`, `get_user_by_sub()`, SQL queries
- `session_store.py`: join queries referencing `u.auth0_sub`
- `registry.py`: `set_auth0_org_id()` → `set_oidc_org_id()`, `get_installation_by_auth0_org()` → `get_installation_by_oidc_org()`
- `migrations/versions/0001_baseline.py`: update baseline schema

### 5.3 Data Migration

No data transformation needed. The `sub` claim is an opaque string (`auth0|abc123`, `google-oauth2|456`, etc.) that Canon stores and matches but never parses. Any OIDC provider's `sub` claim works as-is in the renamed column.

### Acceptance Criteria

- [x] New migration renames `auth0_sub` → `oidc_sub` in users table
<!-- canon:realized-in:PR#386 file:src/canon/db/migrations/versions/0002_oidc_rename.py:21-28 -->
- [x] New migration renames `auth0_org_id` → `oidc_org_id` in gh_installations table with updated index
<!-- canon:realized-in:PR#386 file:src/canon/db/migrations/versions/0002_oidc_rename.py:29-41 -->
- [x] `users.role` column added with default `'editor'`
<!-- canon:realized-in:PR#386 file:src/canon/db/migrations/versions/0002_oidc_rename.py:42 file:src/canon/db/migrations/versions/0001_baseline.py:179 -->
- [x] All Python code updated to use new column names
<!-- canon:realized-in:PR#386 file:src/canon/db/user_store.py:48-81 file:src/canon/auth/routes.py:152 file:src/canon/auth/device_routes.py:142 -->
- [x] `registry.py` methods renamed: `set_oidc_org_id()`, `get_installation_by_oidc_org()`
<!-- canon:realized-in:PR#386 file:src/canon/db/registry.py:151-167 -->
- [x] Baseline migration updated for new installs
<!-- canon:realized-in:PR#386 file:src/canon/db/migrations/versions/0001_baseline.py:68-91,172-183 -->
- [x] Existing data migrates cleanly (no transformation, just column rename)
<!-- canon:realized-in:PR#466 file:src/canon/db/migrations/versions/0002_oidc_rename.py -->

## 6. Auth Module Refactor

<!-- canon:system:6 status:done -->

Refactor the 7 Auth0-coupled files to use the provider abstraction.

### 6.1 File-by-File Changes

| File | Lines | Change |
|------|-------|--------|
| `oauth.py` | 27 | Replace `oauth.register(name="auth0", ...)` with provider-configured registration |
| `routes.py` | 222 | Login: use `provider.get_login_url()`. Callback: use `provider.exchange_code()`, drop org claim parsing for single-tenant. Logout: use `provider.get_logout_url()`. |
| `jwt.py` | 110 | JWKS URL from `provider.get_jwks_uri()` instead of hardcoded domain. Remove `resolve_org_login()` for single-tenant; keep behind multi-tenant guard for cloud. |
| `device_routes.py` | 196 | Use `provider.get_device_code()` and `provider.poll_device_token()`. Return 501 if provider returns `None`. |
| `refresh_routes.py` | 163 | Use `provider.refresh_tokens()` instead of hardcoded Auth0 token endpoint. |
| `middleware.py` | 130 | Org isolation block (lines 96-127) guarded by `auth0_orgs_enabled` already. No change for single-tenant. |
| `deps.py` | 170 | Permission resolution: if single-tenant, use `users.role` → `ROLE_PERMISSIONS` instead of JWT claims. |
| `management.py` | 81 | Move to `providers/auth0.py` as internal helper. Not exposed via protocol. Excluded from OSS export. |

### 6.2 RBAC Resolution

```python
async def _resolve_permissions(user_record: dict, claims: dict, settings: Settings) -> frozenset[Permission]:
    if settings.auth0_orgs_enabled:
        # Cloud: permissions from Auth0 RBAC claims
        return frozenset(Permission(p) for p in claims.get("permissions", []))
    elif user_record and user_record.get("role"):
        # OSS: permissions from server-side role
        return ROLE_PERMISSIONS[Role(user_record["role"])]
    else:
        # Fallback: viewer permissions
        return ROLE_PERMISSIONS[Role.VIEWER]
```

### Acceptance Criteria

- [x] `oauth.py` registers provider using discovery URL from settings, not hardcoded Auth0 domain
<!-- canon:realized-in:PR#386 file:src/canon/auth/oauth.py:12-43 -->
- [x] `routes.py` login endpoint uses `provider.get_login_url()`
<!-- canon:realized-in:PR#386 file:src/canon/auth/routes.py:38-77 (via authlib authorize_redirect abstraction) -->
- [x] `routes.py` callback endpoint uses `provider.exchange_code()` and extracts claims generically
<!-- canon:realized-in:PR#386 file:src/canon/auth/routes.py:80-192 (via authlib authorize_access_token abstraction) -->
- [x] `routes.py` logout endpoint uses `provider.get_logout_url()` with fallback
<!-- canon:realized-in:PR#386 file:src/canon/auth/routes.py:268-292 -->
- [x] `jwt.py` fetches JWKS from `provider.get_jwks_uri()`
<!-- canon:realized-in:PR#386 file:src/canon/auth/jwt.py:143-156 file:src/canon/auth/deps.py:167-170 -->
- [x] `jwt.py` org resolution skipped when `auth0_orgs_enabled` is False
<!-- canon:realized-in:PR#386 file:src/canon/auth/jwt.py:101-140 -->
- [x] `device_routes.py` uses provider methods; returns 501 if device auth unsupported
<!-- canon:realized-in:PR#386 file:src/canon/auth/device_routes.py:37-91 -->
- [x] `refresh_routes.py` uses `provider.refresh_tokens()`
<!-- canon:realized-in:PR#386 file:src/canon/auth/refresh_routes.py:64-73 -->
- [x] `deps.py` resolves permissions from `users.role` when not using Auth0 RBAC
<!-- canon:realized-in:PR#386 file:src/canon/auth/deps.py:122-158 file:src/canon/auth/permissions.py:34-38 -->
- [x] `management.py` moved into `providers/auth0.py`; not imported in generic path
<!-- canon:realized-in:PR#386 file:src/canon/auth/providers/auth0.py:160-205 -->
- [x] All existing tests pass with Auth0 configuration (backward compatible)
<!-- canon:realized-in:PR#386 file:tests/test_auth/test_providers/test_auth0.py -->

## 7. Helm Chart Updates

<!-- canon:system:7 status:done -->

Add generic OIDC configuration to the Helm chart alongside existing Auth0 values.

### 7.1 New Values

```yaml
secrets:
  ## @section OIDC secrets (alternative to Auth0 — for generic OIDC providers)
  ## @param secrets.oidc.issuer OIDC provider issuer URL
  ## @param secrets.oidc.clientId OIDC application client ID
  ## @param secrets.oidc.clientSecret OIDC application client secret
  ## @param secrets.oidc.audience OIDC API audience (optional)
  ## @param secrets.oidc.existingSecret Use existing secret
  oidc:
    issuer: ""
    clientId: ""
    clientSecret: ""
    audience: ""
    existingSecret: ""

  ## Existing auth0 section remains for backward compatibility
  auth0:
    domain: ""
    clientId: ""
    # ...
```

### 7.2 Secret Template

New `secret-oidc.yaml` template:

```yaml
{{- if and .Values.secrets.oidc.issuer (not .Values.secrets.oidc.existingSecret) }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "canon.oidcSecretName" . }}
stringData:
  OIDC_ISSUER: {{ .Values.secrets.oidc.issuer | quote }}
  OIDC_CLIENT_ID: {{ .Values.secrets.oidc.clientId | quote }}
  OIDC_CLIENT_SECRET: {{ .Values.secrets.oidc.clientSecret | quote }}
  {{- if .Values.secrets.oidc.audience }}
  OIDC_AUDIENCE: {{ .Values.secrets.oidc.audience | quote }}
  {{- end }}
{{- end }}
```

### 7.3 Deployment Update

Conditionally mount OIDC secret in deployment template, same pattern as Auth0:

```yaml
{{- if or .Values.secrets.oidc.issuer .Values.secrets.oidc.existingSecret }}
  - secretRef:
      name: {{ include "canon.oidcSecretName" . }}
{{- end }}
```

### Acceptance Criteria

- [x] `values.yaml` has `secrets.oidc.*` section with issuer, clientId, clientSecret, audience, existingSecret
<!-- canon:realized-in:PR#386 file:chart/canon/values.yaml:87-98 -->
- [x] `templates/secret-oidc.yaml` creates OIDC K8s Secret conditionally
<!-- canon:realized-in:PR#386 file:chart/canon/templates/secret-oidc.yaml:1-16 -->
- [x] `templates/_helpers.tpl` has `canon.oidcSecretName` helper
<!-- canon:realized-in:PR#386 file:chart/canon/templates/_helpers.tpl:130-138 -->
- [x] `templates/deployment.yaml` mounts OIDC secret when configured
<!-- canon:realized-in:PR#386 file:chart/canon/templates/deployment.yaml:65-68 -->
- [x] Existing `secrets.auth0.*` section unchanged (backward compatible)
<!-- canon:realized-in:PR#386 file:chart/canon/values.yaml:72-85 -->
- [x] Both Auth0 and OIDC secrets can coexist (cloud uses Auth0, preview could use OIDC)
<!-- canon:realized-in:PR#386 file:chart/canon/templates/deployment.yaml:61-68 -->

<!-- canon:ticket:github:405 -->
## 8. Bundled Zitadel (Optional Subchart)

<!-- canon:system:8 status:done -->

Ship Zitadel as an optional Helm subchart for self-hosters who don't have an existing identity provider.

### 8.1 Subchart Configuration

```yaml
# values.yaml
zitadel:
  enabled: false          # deploys Zitadel alongside Canon
  # Upstream Zitadel Helm chart values pass through here
  # See: https://github.com/zitadel/zitadel-charts
```

When `zitadel.enabled: true`:
1. Zitadel Helm subchart deploys in the same namespace
2. A post-install Job auto-configures Zitadel:
   - Creates a Canon project
   - Creates a web application with correct redirect URIs (`/auth/callback`)
   - Creates a device auth application for CLI
   - Writes client credentials to a K8s Secret
3. Canon reads that Secret on startup via `secrets.oidc.existingSecret`

### 8.2 Zitadel Setup Job

```yaml
# templates/job-zitadel-setup.yaml (simplified — see actual template for full RBAC + idempotency)
{{- if and .Values.zitadel.enabled .Values.zitadel.setup }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "canon.fullname" . }}-zitadel-setup
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "10"
spec:
  template:
    spec:
      serviceAccountName: {{ include "canon.fullname" . }}-zitadel-setup
      containers:
        - name: setup
          image: {{ .Values.zitadel.setupImage | default "bitnami/kubectl:latest" }}
          command: ["/bin/sh", "-ec"]
          # Inline script: waits for health, obtains admin token,
          # creates Canon project + web app + device app (idempotent),
          # writes OIDC credentials to K8s Secret
      restartPolicy: OnFailure
{{- end }}
```

### 8.3 Self-Hosting Experience

**With bundled Zitadel (zero external deps):**
```bash
helm install canon chart/canon/ \
  --set zitadel.enabled=true
# Auth just works. Zitadel admin console available at its own ingress.
```

**With existing IDP (bring your own):**
```bash
kubectl create secret generic canon-oidc \
  --from-literal=OIDC_ISSUER=https://your-idp.com \
  --from-literal=OIDC_CLIENT_ID=... \
  --from-literal=OIDC_CLIENT_SECRET=...

helm install canon chart/canon/ \
  --set secrets.oidc.existingSecret=canon-oidc
```

**Without auth (dev/trusted network):**
```bash
helm install canon chart/canon/
# No auth configured — anonymous access with all permissions
```

### 8.4 Zitadel Database

Bundled Zitadel uses its own PostgreSQL instance via the Zitadel subchart's built-in database configuration. Separate from Canon's Postgres to prevent schema conflicts. Self-hosters who want to optimize can point both at the same Postgres server with different databases.

### Acceptance Criteria

- [x] `Chart.yaml` declares Zitadel as optional dependency (`condition: zitadel.enabled`)
<!-- canon:realized-in:PR#390 file:chart/canon/Chart.yaml -->
- [x] `values.yaml` has `zitadel.enabled: false` with upstream chart values pass-through
<!-- canon:realized-in:PR#386 file:chart/canon/values.yaml:254-262 -->
<!-- canon:realized-in:PR#390 file:chart/canon/values.yaml -->
- [x] Post-install Job creates Zitadel project + web app + device app
<!-- canon:realized-in:PR#390 file:chart/canon/templates/job-zitadel-setup.yaml -->
- [x] Job writes OIDC client credentials to K8s Secret
- [x] Canon auto-discovers credentials via `secrets.oidc.existingSecret`
<!-- canon:realized-in:PR#386 file:chart/canon/templates/_helpers.tpl:130-138 file:chart/canon/templates/deployment.yaml:65-68 -->
- [x] `helm install --set zitadel.enabled=true` produces a working auth setup with no manual configuration
- [x] Zitadel admin console is accessible for user management
- [x] Zitadel uses separate PostgreSQL instance (not Canon's database)

## 9. OSS Export Updates

<!-- canon:system:9 status:done -->

Update `export-oss.sh` to include the auth module (minus cloud-only files) and the web platform.

### 9.1 New Export Allowlist Entries

```bash
# Add to Python source rsync block
--include='auth/__init__.py'
--include='auth/providers/***'
--exclude='auth/providers/auth0.py'     # cloud-only
--include='auth/oauth.py'
--include='auth/routes.py'
--include='auth/jwt.py'
--include='auth/middleware.py'
--include='auth/deps.py'
--include='auth/device_routes.py'
--include='auth/refresh_routes.py'
--include='auth/api_key_routes.py'
--include='auth/github_oauth.py'
--include='auth/github_routes.py'
--include='auth/permissions.py'
--include='auth/models.py'
--exclude='auth/management.py'          # cloud-only (Auth0 Management API)
--include='db/***'
--include='main.py'
--include='web/***'
--include='cron/***'
```

### 9.2 OSS Dockerfile Update

The OSS Dockerfile needs the `[cloud]` extra (or a renamed `[server]` extra) to include `authlib` and `itsdangerous`:

```dockerfile
# Change from:
RUN pip install --no-cache-dir /tmp/*.whl

# To:
RUN pip install --no-cache-dir "/tmp/*.whl[server]"
```

### 9.3 OSS .env.example Update

```bash
# Auth (optional — required for web login)
# Set these to enable authentication with any OIDC provider
OIDC_ISSUER=               # e.g., https://your-keycloak.com/realms/canon
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=
OIDC_AUDIENCE=              # optional, for API-specific tokens
```

### 9.4 Sensitive Spec Exclusion

Add the OIDC migration spec to the export (it contains no proprietary information):
```bash
# This spec is OSS-safe — no Auth0 tenant details or cloud infrastructure secrets
# Do NOT add to the rm -f exclusion list
```

### Acceptance Criteria

- [x] `export-oss.sh` includes `auth/` module (excluding `auth/providers/auth0.py` and `auth/management.py`)
<!-- canon:realized-in:PR#386 file:.github/scripts/export-oss.sh:37-78 -->
- [x] `export-oss.sh` includes `db/`, `main.py`, `web/`, `cron/`
<!-- canon:realized-in:PR#386 file:.github/scripts/export-oss.sh:70-73 -->
- [x] OSS Dockerfile installs with server extra for auth dependencies
<!-- canon:realized-in:PR#390 file:oss/Dockerfile -->
- [x] OSS `.env.example` has OIDC configuration section
<!-- canon:realized-in:PR#386 file:oss/.env.example:10-19 -->
- [x] `auth/providers/auth0.py` and `auth/management.py` confirmed absent from OSS build
<!-- canon:realized-in:PR#386 file:tests/test_oss_export.py:98-106 -->
- [x] OSS build produces working Docker image with auth support
<!-- canon:realized-in:PR#386 file:tests/test_oss_export.py:63-222 -->

<!-- canon:ticket:github:406 -->
## 10. CI/CD Updates

<!-- canon:system:10 status:done -->

Update deployment workflows for the new OIDC configuration. Cloud deployments continue using Auth0 secrets. No breaking change.

### 10.1 Deploy Workflow

The existing `deploy.yml` creates `canon-auth0` secret from Doppler. This stays unchanged. When the cloud eventually adds OIDC secrets to Doppler, a new `canon-oidc` secret creation block would be added alongside (not replacing) the Auth0 block.

### 10.2 OSS CI

The OSS CI workflow (`oss/ci.yml`) needs to test with OIDC configuration in addition to the current auth-disabled tests.

### Acceptance Criteria

- [x] Cloud `deploy.yml` unchanged (Auth0 secrets continue working)
<!-- canon:realized-in:PR#386 file:.github/workflows/deploy.yml:107-113 -->
- [x] Cloud `preview.yml` unchanged
<!-- canon:realized-in:PR#386 file:.github/workflows/preview.yml:84-115 -->
- [x] OSS CI runs tests with both auth-disabled and OIDC-configured modes
<!-- canon:realized-in:PR#390 file:oss/ci.yml -->
- [x] No Doppler configuration changes required for initial rollout

<!-- canon:ticket:github:407 -->
## 11. Documentation Updates

<!-- canon:system:11 status:done -->

Rewrite self-hosting docs for OIDC-first setup with Auth0 as one option among many.

### 11.1 Self-Hosting Guide

Restructure the auth section of `docs/self-hosting.md`:

1. **Option A: Bundled Zitadel** — `--set zitadel.enabled=true` (recommended for teams without IDP)
2. **Option B: Bring your own OIDC** — configure issuer, client_id, client_secret
3. **Option C: Auth0** — existing instructions (kept for users already on Auth0)
4. **Option D: No auth** — dev/trusted-network mode

### 11.2 Provider-Specific Guides

Short setup guides for common providers:
- Zitadel (bundled or external)
- Keycloak
- Okta
- Google Workspace
- Microsoft Entra ID

Each guide covers: create application, configure redirect URIs, note issuer/client_id/client_secret.

### Acceptance Criteria

- [x] `docs/self-hosting.md` auth section rewritten with 4 options (Zitadel, BYOIDC, Auth0, none)
<!-- canon:realized-in:PR#390 file:docs/self-hosting.md -->
- [x] Bundled Zitadel listed as recommended default for new self-hosted deployments
- [x] Provider-specific setup snippets for at least Zitadel, Keycloak, and Okta
- [x] Auth0 instructions preserved for backward compatibility
- [x] `docs-site/` VitePress site updated with matching content

## 12. Frontend Updates

<!-- canon:system:12 status:done -->

Minimal frontend changes — the frontend is already provider-agnostic.

### 12.1 Label Change

```typescript
// frontend/src/components/profile/ProfileCard.vue, line 50
// Change from:
case 'session':
  return 'Auth0 Session'

// To:
case 'session':
  return 'OIDC Session'
```

### 12.2 Login View

The login page (`LoginView.vue`) renders provider buttons (GitHub, Google, Email) and redirects to `/auth/login?connection=...`. For generic OIDC, the login page should show a single "Sign in" button that redirects to `/auth/login` (the OIDC provider handles identity federation). Provider buttons remain when Auth0 is the configured provider.

### Acceptance Criteria

- [x] `ProfileCard.vue` displays "OIDC Session" instead of "Auth0 Session"
<!-- canon:realized-in:PR#386 file:frontend/src/components/profile/ProfileCard.vue:50 -->
- [x] Login view shows single "Sign in" button when using generic OIDC provider
<!-- canon:realized-in:PR#386 file:frontend/src/views/LoginView.vue:30-33 -->
- [x] Login view shows provider-specific buttons when using Auth0 (backward compatible)
<!-- canon:realized-in:PR#386 file:frontend/src/views/LoginView.vue:35-59 -->
- [x] No Auth0 SDK dependencies introduced (currently none, keep it that way)

## 13. Test Updates

<!-- canon:system:13 status:done -->

Update test suite to support both Auth0 and generic OIDC configurations.

### 13.1 Scope

- **14 primary test files** in `test_auth/` — rewrite OAuth mocks to use provider protocol
- **40 secondary test files** — update `auth0_sub` → `oidc_sub` in fixtures and settings
- **Conftest fixtures** — add OIDC-configured settings fixture alongside Auth0 fixture

### 13.2 Approach

Each auth test should run against both provider configurations:
- `@pytest.mark.parametrize("provider", ["auth0", "oidc"])` for tests that should work identically
- Provider-specific tests for Auth0-only features (org isolation, Management API)

### Acceptance Criteria

- [x] All existing auth tests pass with Auth0 configuration (no regression)
<!-- canon:realized-in:PR#386 file:tests/test_auth/test_providers/test_auth0.py -->
- [x] New tests validate generic OIDC flow (login, callback, refresh, logout)
<!-- canon:realized-in:PR#386 file:tests/test_auth/test_providers/test_generic_oidc.py -->
- [x] Test fixtures updated: `auth0_sub` → `oidc_sub`, `auth0_org_id` → `oidc_org_id`
<!-- canon:realized-in:PR#386 file:tests/test_auth/test_providers/test_factory.py -->
- [x] Device auth tests cover both "supported" and "unsupported" provider scenarios
<!-- canon:realized-in:PR#386 file:tests/test_auth/test_providers/test_generic_oidc.py:166-177 -->
- [x] First-user-bootstrap test validates admin role assignment
- [x] Single-tenant RBAC test validates `users.role` → permission resolution

<!-- canon:ticket:github:408 -->
## 14. Rollout Plan

<!-- canon:system:14 status:todo -->

### Phase 1: Provider Abstraction (no behavior change)

1. Create `auth/providers/` with protocol + Auth0 implementation
2. Refactor existing auth code to use provider protocol
3. All tests pass — Auth0 behavior unchanged
4. Merge to main

### Phase 2: Generic OIDC + Settings

1. Implement `GenericOIDCProvider`
2. Add `oidc_*` settings with auto-detection
3. Database migration: `auth0_sub` → `oidc_sub`
4. Update tests
5. Merge to main

### Phase 3: Helm + OSS Export

1. Add `secrets.oidc.*` to Helm chart
2. Update `export-oss.sh` to include auth module
3. Update OSS Dockerfile and `.env.example`
4. Update self-hosting docs
5. Merge to main, trigger OSS export

### Phase 4: Bundled Zitadel

1. Add Zitadel subchart dependency
2. Implement setup Job
3. Test end-to-end: `--set zitadel.enabled=true`
4. Merge to main

### Phase 5: Documentation + Polish

1. Provider-specific setup guides
2. Migration guide for existing Auth0 self-hosters
3. Update vision.md and CHANGELOG.md
4. Announce in release notes

## 15. Open Questions

- Should the `[cloud]` extra in `pyproject.toml` be renamed to `[server]` for OSS clarity, or keep `[cloud]` to avoid breaking existing installs?
- Should the Zitadel setup Job use a purpose-built init container image or `curlimages/curl` with shell scripts?
- What's the migration story for existing self-hosters on Auth0? Do we provide a migration guide, or is "reconfigure with OIDC settings pointing at same Auth0 tenant" sufficient?
- Should `canon login --browser` (authorization code with localhost redirect) be implemented as part of this spec or deferred?
