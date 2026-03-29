---
title: "Auth0 Tenant Migration: gv-os → canonhq"
type: spec
status: draft
owner: ng
team: platform
review_status: draft
tags: [auth, infrastructure, auth0, migration]
depends_on: [auth-hardening]
created: 2026-03-28
updated: 2026-03-28
---

# Auth0 Tenant Migration: gv-os → canonhq

Migrate Canon's Auth0 configuration from the shared `gv-os.us.auth0.com` tenant to the dedicated `canonhq.us.auth0.com` tenant, and enable Auth0 Organizations features for Canon's multi-tenant B2B SaaS model.

## 1. Background

<!-- canon:system:1 status:draft -->

Canon currently authenticates against `gv-os.us.auth0.com`, a shared Gerner Ventures tenant that also hosts other experiments. This creates several problems:

- **Blast radius**: Auth0 configuration changes for other projects can break Canon's login flow
- **Connection pollution**: The gv-os tenant has connections (e.g. `restrict_signups` action) scoped to GV org membership, not Canon customers
- **Branding**: Login pages show GV branding, not Canon branding
- **Billing**: Auth0 usage is aggregated across all GV experiments, making Canon's costs opaque
- **Organization isolation**: Canon's multi-org features are constrained by the shared tenant's configuration

A dedicated `canonhq` tenant has been created (US-5 region, Production environment, Friendly Name: CanonHQ). This spec covers the Terraform changes needed to provision all Auth0 resources in the new tenant and the cutover procedure.

### Current Terraform Auth0 Module

The existing module at `infra/modules/auth0/` defines:
- 4 clients: Canon (web), Canon Dev (localhost), Canon CLI (device auth), Canon M2M (backend)
- API Resource Server: `https://canonhq.co/api` with RBAC scopes
- 3 roles: Viewer, Editor, Admin with permission mappings
- 1 organization: `canonhq` with GitHub + DB connections
- 1 post-login action: `canon-default-role` (auto-assign Editor + GitHub token passthrough)
- 1 test user: `hello+canon@njgerner.com`

The module currently uses `data` sources for connections (`github`, `Username-Password-Authentication`) — these assume the connections already exist in the tenant. The new tenant requires these to be managed resources.

## 2. Bootstrap: Terraform Provider Credentials

<!-- canon:system:2 status:draft -->

Chicken-and-egg problem: Terraform needs an M2M app to authenticate with the Auth0 Management API, but Terraform is what creates M2M apps. Solution: manually create a bootstrap M2M app in the canonhq tenant.

### Manual Steps (one-time, before `terraform apply`)

1. In the canonhq Auth0 dashboard, create an M2M application named "Terraform"
2. Authorize it for the Auth0 Management API (`https://canonhq.us.auth0.com/api/v2/`) with full scopes
3. Store the client ID and secret in Doppler as `TF_VAR_auth0_tf_client_id` and `TF_VAR_auth0_tf_client_secret`

### Acceptance Criteria

- [ ] "Terraform" M2M app exists in the canonhq tenant with Management API access
- [ ] Credentials stored in Doppler under `canon/prd` as `TF_VAR_auth0_tf_client_id` and `TF_VAR_auth0_tf_client_secret`
- [ ] `terraform init && terraform plan` succeeds against the canonhq tenant with no errors

## 3. Terraform Domain & Variable Updates

<!-- canon:system:3 status:draft -->

Update all references from `gv-os.us.auth0.com` to `canonhq.us.auth0.com`.

### Changes

| File | Change |
|------|--------|
| `infra/terraform.tfvars` | `auth0_domain = "canonhq.us.auth0.com"` |
| `infra/variables.tf` | Update `auth0_domain` description to reference canonhq |
| `infra/modules/auth0/variables.tf` | Update description |

### Acceptance Criteria

- [ ] `auth0_domain` in `terraform.tfvars` set to `canonhq.us.auth0.com`
- [ ] All variable descriptions reference canonhq, not gv-os
- [ ] Auth0 provider block in `infra/main.tf` works with the new domain (no code change needed — it already reads from `var.auth0_domain`)

## 4. Connection Management (data → resource)

<!-- canon:system:4 status:draft -->

The gv-os tenant had pre-existing connections. The canonhq tenant has only the default `Username-Password-Authentication` connection. The `github` social connection must be created as a managed Terraform resource.

### 4.1 Username-Password-Authentication

Auth0 creates this connection by default in every new tenant. Keep the `data` source — it already exists.

### 4.2 GitHub Social Connection

Create a new GitHub OAuth App for the canonhq tenant and manage the connection via Terraform.

**GitHub OAuth App setup** (manual, one-time):
1. Create OAuth App at `https://github.com/settings/developers` (or under the canonhq org)
2. Homepage URL: `https://canonhq.co`
3. Authorization callback URL: `https://canonhq.us.auth0.com/login/callback`
4. Store client ID and secret in Doppler as `TF_VAR_github_oauth_client_id` and `TF_VAR_github_oauth_client_secret`

**Terraform change**: Replace `data "auth0_connection" "github"` with `resource "auth0_connection" "github"`.

### 4.3 Google OAuth Connection (new)

Add a Google OAuth2 social connection for Google login. Gated by `google_oauth_client_id` variable — disabled by default until a Google Cloud OAuth consent screen is configured. Aligns with auth-hardening spec system 2.

### 4.4 Passwordless Email Connection (new)

Add a passwordless email (magic link) connection as a fallback login method. Aligns with auth-hardening spec system 2.

### Acceptance Criteria

- [ ] `data "auth0_connection" "github"` replaced with `resource "auth0_connection" "github"` using OAuth App credentials
- [ ] New variables `github_oauth_client_id` and `github_oauth_client_secret` added to `variables.tf`
- [ ] GitHub OAuth App created with correct callback URL (`https://canonhq.us.auth0.com/login/callback`)
- [ ] GitHub connection enables `read:user` and `read:org` scopes
- [ ] `data "auth0_connection" "username_password"` remains (default connection exists)
- [ ] Google Workspace connection resource added (gated by variable, disabled by default until configured)
- [ ] Passwordless email connection resource added

## 5. Organization Enhancements

<!-- canon:system:5 status:draft -->

Leverage Auth0 Organizations features for Canon's multi-tenant B2B model. The current Terraform already creates a `canonhq` org — this section adds features that make Organizations useful for customer onboarding.

### 5.1 Organization Metadata

Store Canon-specific metadata on Auth0 Organizations to reduce database lookups:

```hcl
resource "auth0_organization" "canonhq" {
  name         = "canonhq"
  display_name = "Canon HQ"

  metadata = {
    subscription_tier = "admin"
    github_owner      = "canonhq"
  }
}
```

### 5.2 Organization Branding

Configure per-org login page branding:

```hcl
branding {
  logo_url = "https://canonhq.co/docs/logo.svg"
  colors = {
    primary         = "#F97316"  # Canon orange
    page_background = "#0F172A"  # Slate 900
  }
}
```

### 5.3 Invitation Support

Enable the Management API scopes needed for programmatic member invitations. Add to the M2M client grant:

```hcl
scopes = [
  # existing scopes...
  "create:organization_invitations",
  "read:organization_invitations",
  "delete:organization_invitations",
  "create:organization_members",
  "read:organization_members",
  "delete:organization_members",
  "read:organization_member_roles",
  "create:organization_member_roles",
  "delete:organization_member_roles",
]
```

### 5.4 Enhanced Member Management Scopes

The current M2M grant has basic org scopes. Expand for full member lifecycle management needed by the Canon backend's `Auth0Provider.get_user_orgs()` and future invitation/member management features.

### Acceptance Criteria

- [ ] `canonhq` organization has `metadata` block with `subscription_tier` and `github_owner`
- [ ] `canonhq` organization has `branding` block with Canon logo and colors
- [ ] M2M client grant includes invitation scopes (`create:organization_invitations`, `read:organization_invitations`, `delete:organization_invitations`)
- [ ] M2M client grant includes member management scopes (`create:organization_members`, `read:organization_members`, `delete:organization_members`)
- [ ] M2M client grant includes member role scopes (`read:organization_member_roles`, `create:organization_member_roles`, `delete:organization_member_roles`)
- [ ] Canon backend can call `POST /api/v2/organizations/{id}/invitations` via M2M token

## 6. Signup Restriction

<!-- canon:system:6 status:draft -->

The gv-os tenant relied on a `restrict_signups` Action in core/ that gated GitHub logins to Gerner-Ventures org members. The canonhq tenant needs its own approach.

### Strategy

Instead of a global restrict-signups action, use **connection-level restrictions**:

1. **GitHub connection**: Set `allowed_organizations` to restrict which GitHub orgs can sign up (or leave open for public sign-up)
2. **Organization-scoped login**: Canon already uses `organization_usage = "allow"` on clients — when a user logs in with an `organization` parameter, Auth0 only allows connections enabled for that org
3. **Post-login action**: The existing `canon-default-role` action handles first-login role assignment — no dependency on gv-os restrict_signups

### Acceptance Criteria

- [ ] No dependency on gv-os `restrict_signups` Action
- [ ] GitHub connection optionally restricts to specific GitHub organizations (configurable via variable)
- [ ] Organization-scoped login correctly limits available connections per org
- [ ] Post-login action functions independently (no cross-tenant M2M calls)

## 7. Action Updates

<!-- canon:system:7 status:draft -->

The `canon-default-role` post-login action needs minor updates for the new tenant.

### Changes

1. Remove the `https://specwright.dev/github` transition claim (cleanup — no longer needed)
2. Verify Action secrets reference the new M2M client (Terraform already wires `auth0_client.canon_action_m2m` — this is self-contained)
3. Ensure the action works with the new tenant's GitHub connection

### Acceptance Criteria

- [ ] `specwright.dev/github` custom claim removed from post-login action
- [ ] Action deploys successfully in the canonhq tenant
- [ ] GitHub token passthrough works with the new GitHub social connection
- [ ] Editor role auto-assignment works for first-login users

## 8. Doppler & Deployment Updates

<!-- canon:system:8 status:draft -->

After `terraform apply`, update Doppler secrets and verify the deployment pipeline.

### Secrets to Update in Doppler (`canon/prd`)

| Secret | Source |
|--------|--------|
| `AUTH0_DOMAIN` | `canonhq.us.auth0.com` |
| `AUTH0_CLIENT_ID` | `terraform output auth0_client_id` |
| `AUTH0_CLIENT_SECRET` | `terraform output auth0_client_secret` |
| `AUTH0_AUDIENCE` | `https://canonhq.co/api` (unchanged) |
| `AUTH0_DEVICE_CLIENT_ID` | `terraform output auth0_cli_client_id` |
| `AUTH0_M2M_CLIENT_ID` | `terraform output auth0_m2m_client_id` |
| `AUTH0_M2M_CLIENT_SECRET` | `terraform output auth0_m2m_client_secret` |

### Deployment Pipeline

No changes needed to `.github/workflows/deploy.yml` or `preview.yml` — they already read Auth0 secrets from Doppler and create the `canon-auth0` K8s secret. The new values will flow through automatically.

### Application Code

No changes needed — `Auth0Provider` reads `auth0_domain` from settings and constructs URLs dynamically. JWT validation uses the configured domain for JWKS URI resolution.

### Acceptance Criteria

- [ ] All Auth0 secrets updated in Doppler `canon/prd`
- [ ] Dev secrets updated in Doppler `canon/dev` (using `canon_dev` client)
- [ ] `kubectl get secret canon-auth0 -n canon -o yaml` shows new domain
- [ ] Application starts successfully with new Auth0 configuration
- [ ] Web login flow works end-to-end (GitHub → callback → session)
- [ ] CLI `canon login` device flow works against the new tenant
- [ ] M2M org membership queries work (`Auth0Provider.get_user_orgs()`)

## 9. Cutover Plan

<!-- canon:system:9 status:draft -->

### Phase 1: Terraform (no user impact)

1. Create Terraform M2M app in canonhq dashboard (manual)
2. Create GitHub OAuth App (manual)
3. Store credentials in Doppler
4. Update `terraform.tfvars` domain
5. Update Terraform module (connections, org enhancements, action cleanup)
6. `terraform plan` — verify all resources will be created (not modified)
7. `terraform apply` — provision all Auth0 resources in canonhq tenant
8. Store terraform outputs in Doppler

### Phase 2: Deploy (brief downtime)

1. **Maintenance window**: Announce 5-minute auth maintenance
2. Update Doppler `canon/prd` with new Auth0 credentials
3. Trigger deploy workflow — K8s secret gets recreated with new domain
4. Pods restart with new configuration
5. Verify health checks pass

### Phase 3: Verify

1. Test web login (GitHub provider)
2. Test CLI login (`canon login`)
3. Test M2M org queries
4. Test preview environment auth
5. Monitor Auth0 logs for errors

### Phase 4: Cleanup

1. Remove Canon resources from gv-os tenant (manual or via gv-infra Terraform)
2. Close `enable_shared_services` phasing — set to `true` once all shared services are migrated
3. Update auth-hardening spec infrastructure section to mark tenant migration as done

### Rollback

If issues arise after cutover:
1. Revert Doppler secrets to gv-os credentials
2. Re-deploy — pods restart with old configuration
3. gv-os resources are untouched until Phase 4 cleanup

### Acceptance Criteria

- [ ] Cutover completed with ≤ 5 minutes of auth downtime
- [ ] No user data loss (users re-authenticate; no persistent state in Auth0 beyond what Terraform manages)
- [ ] Rollback procedure tested (Doppler revert → re-deploy)
- [ ] gv-os Canon resources removed after 1-week soak period

## 10. Open Questions

- Should we enable **Auth0 custom domains** (e.g., `auth.canonhq.co`) to avoid exposing the `canonhq.us.auth0.com` domain to users? This requires a CNAME record and an Auth0 paid plan feature.
- Should the GitHub OAuth App live under the `canonhq` GitHub organization or a personal account?
- Do we want to keep the GCP project reference as `gv-os-485900` or create a dedicated GCP project for Canon? (Separate concern, but related infrastructure independence.)
- For the Google Workspace connection — do we need a specific Google Cloud project/OAuth consent screen, or can we use Auth0's built-in Google social connection?
