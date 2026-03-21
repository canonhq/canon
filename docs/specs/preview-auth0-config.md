---
title: "Preview Environment Auth0 Configuration"
type: spec
status: draft
owner: ng
team: platform
review_status: draft
tags: [preview, auth0, deployment, security]
depends_on:
  - infra-enablement-billing-email
created: "2026-03-20"
updated: "2026-03-20"
---

# Preview Environment Auth0 Configuration

## 1. Background

Preview environments (`canon-preview-N` namespaces) deploy per-PR instances at
`pr-N.canonhq.co`. Two Auth0 configuration gaps were discovered during SRE
alerting work (PR #453):

1. **M2M credentials missing**: `AUTH0_M2M_CLIENT_ID` and `AUTH0_M2M_CLIENT_SECRET`
   are not included in the `canon-auth0` K8s secret created by the preview workflow.
   This means `get_user_orgs()` in `src/canon/auth/providers/auth0.py:162` cannot
   call the Auth0 Management API, and every authenticated request logs a warning.

2. **Opaque access tokens**: Auth0 returns an opaque access token instead of a JWT
   in preview environments. The callback at `src/canon/auth/routes.py:118` fails
   with `jwt.DecodeError: Invalid payload string`. The code handles this gracefully
   (warns and continues), but preview users get no RBAC permissions. The root cause
   is that `pr-N.canonhq.co` callback URLs are not registered in the Auth0
   application configuration.

Both issues also affect the production deploy workflow (`deploy.yml`), which is
similarly missing M2M credentials. The infra-enablement spec
(`infra-enablement-billing-email.md`) already identifies the M2M gap for production
but does not cover preview environments or the opaque token issue.

## 2. Add M2M Credentials to Workflow Secrets
<!-- canon:status:todo -->

Add `AUTH0_M2M_CLIENT_ID` and `AUTH0_M2M_CLIENT_SECRET` to the `canon-auth0` K8s
secret in both deployment workflows.

### Acceptance Criteria

- [ ] `AUTH0_M2M_CLIENT_ID` and `AUTH0_M2M_CLIENT_SECRET` exist in Doppler `canon/prd`
- [ ] `.github/workflows/preview.yml` fetches both M2M secrets from Doppler and includes
  them in the `canon-auth0` secret creation step
- [ ] `.github/workflows/deploy.yml` fetches both M2M secrets from Doppler and includes
  them in the `canon-auth0` secret creation step
- [ ] `get_user_orgs()` no longer logs the "not configured" warning in preview
- [ ] No changes required to Helm chart — the deployment template reads Auth0 env vars
  directly from the `canon-auth0` K8s secret via `envFrom`

### Implementation Notes

The M2M credentials exist as Terraform outputs in `gv-infra` (`canon_auth0_m2m_client_id`,
`canon_auth0_m2m_client_secret`) but may not yet be propagated to Doppler. Check Doppler
`canon/prd` first; if missing, add them manually or via the infra-enablement spec workflow.

Changes to both workflow files are identical — add two env vars and two `--from-literal`
flags to the `kubectl create secret` command for `canon-auth0`.

## 3. Register Preview Callback URLs in Auth0
<!-- canon:status:todo -->

Configure Auth0 so that preview environment callback URLs are recognized, causing
Auth0 to return JWT access tokens instead of opaque ones.

### Acceptance Criteria

- [ ] Auth0 application "Allowed Callback URLs" includes a wildcard or pattern
  matching `https://pr-*.canonhq.co/auth/callback` (Auth0 supports comma-separated
  URLs but not true wildcards — see implementation notes)
- [ ] Auth0 application "Allowed Logout URLs" includes corresponding preview URLs
- [ ] Auth0 application "Allowed Web Origins" includes `https://pr-*.canonhq.co`
- [ ] Preview deployments receive JWT access tokens (not opaque) from Auth0
- [ ] RBAC permissions are correctly extracted from the JWT in preview environments
- [ ] The `jwt.DecodeError` warning no longer appears in preview logs

### Implementation Notes

Auth0 does **not** support true wildcard callback URLs. Two approaches:

**Option A — Dynamic registration (recommended)**: Add `https://pr-{PR_NUM}.canonhq.co/auth/callback`
to the Auth0 application's allowed callbacks during preview deployment, and remove it
during cleanup. This requires Auth0 Management API calls in the preview workflow using
the M2M credentials (which we're adding in section 2). This is the most secure approach
as it limits valid callbacks to active preview environments.

**Option B — Static list**: Pre-register a fixed set of preview callback URLs
(e.g., `pr-1` through `pr-999`). Simple but creates a large surface area and violates
the principle of least privilege.

**Option C — Separate Auth0 application**: Create a dedicated Auth0 application for
previews with a permissive callback URL pattern. Adds operational complexity but cleanly
isolates preview auth from production.

The opaque token issue is specifically caused by the callback URL not being registered.
When Auth0 receives an authorization request from an unrecognized callback URL with a
valid audience, it falls back to returning an opaque token. Registering the callback URL
resolves this without any code changes.

## 4. Verify Helm Chart Compatibility
<!-- canon:status:todo -->

Ensure the Helm chart deployment template correctly maps the new M2M env vars from the
`canon-auth0` secret to the application container.

### Acceptance Criteria

- [ ] Verify the deployment template uses `envFrom` with the `canon-auth0` secret
  (which automatically exposes all keys as env vars — no template changes needed)
- [ ] OR if the template uses explicit `env` entries, add `AUTH0_M2M_CLIENT_ID` and
  `AUTH0_M2M_CLIENT_SECRET` to the deployment template
- [ ] Confirm `values-preview.yaml` does not need changes (preview overrides should
  not affect secret structure)

## 5. Rollout Plan

1. **Verify Doppler** — Confirm M2M credentials exist in `canon/prd`
2. **Update workflows** — Add M2M secrets to `preview.yml` and `deploy.yml`
3. **Register callbacks** — Update Auth0 application with preview callback URLs
4. **Test** — Deploy a preview and verify:
   - No M2M warning in logs
   - JWT access token received (not opaque)
   - Permissions correctly extracted
   - User org membership fetched successfully
5. **Deploy to production** — Push to main to propagate the deploy.yml changes
