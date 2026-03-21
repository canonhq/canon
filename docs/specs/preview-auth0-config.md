---
title: "Preview Environment Auth0 Configuration"
type: spec
status: in_progress
owner: ng
team: platform
review_status: in_progress
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
   is that `gv-infra/experiments/canon/auth0.tf` uses `pr-*.canonhq.co` as a wildcard
   pattern, but Auth0 only supports full subdomain wildcards (`*.example.com`), not
   partial patterns (`pr-*.example.com`). The fix is to change the wildcard to
   `*.canonhq.co`.

Both issues also affect the production deploy workflow (`deploy.yml`), which is
similarly missing M2M credentials. The infra-enablement spec
(`infra-enablement-billing-email.md`) already identifies the M2M gap for production
but does not cover preview environments or the opaque token issue.

## 2. Add M2M Credentials to Workflow Secrets
<!-- canon:status:done -->

Add `AUTH0_M2M_CLIENT_ID` and `AUTH0_M2M_CLIENT_SECRET` to the `canon-auth0` K8s
secret in both deployment workflows.

### Acceptance Criteria

- [ ] `AUTH0_M2M_CLIENT_ID` and `AUTH0_M2M_CLIENT_SECRET` exist in Doppler `canon/prd`
- [x] `.github/workflows/preview.yml` fetches both M2M secrets from Doppler and includes
  them in the `canon-auth0` secret creation step
- [x] `.github/workflows/deploy.yml` fetches both M2M secrets from Doppler and includes
  them in the `canon-auth0` secret creation step
- [ ] `get_user_orgs()` no longer logs the "not configured" warning in preview
- [x] No changes required to Helm chart — the deployment template reads Auth0 env vars
  directly from the `canon-auth0` K8s secret via `envFrom`

### Implementation Notes

The M2M credentials exist as Terraform outputs in `gv-infra` (`canon_auth0_m2m_client_id`,
`canon_auth0_m2m_client_secret`) but may not yet be propagated to Doppler. Check Doppler
`canon/prd` first; if missing, add them manually or via the infra-enablement spec workflow.

Changes to both workflow files are identical — add two env vars and two `--from-literal`
flags to the `kubectl create secret` command for `canon-auth0`.

## 3. Fix Auth0 Wildcard Callback URLs
<!-- canon:status:done -->

Configure Auth0 so that preview environment callback URLs are recognized, causing
Auth0 to return JWT access tokens instead of opaque ones.

### Root Cause

The existing Auth0 application had `https://pr-*.canonhq.co/auth/callback` as a
wildcard pattern, but Auth0 only supports full subdomain wildcards (`*.example.com`),
not partial patterns (`pr-*.example.com`). This caused Auth0 to not recognize
preview callback URLs, falling back to opaque access tokens.

### Fix

Changed the wildcard pattern from `pr-*.canonhq.co` to `*.canonhq.co` in the
Canon Auth0 application's callbacks, logout URLs, and web origins in
`gv-infra/experiments/canon/auth0.tf`. No separate Auth0 application needed —
the existing production app handles both production and preview URLs.

### Acceptance Criteria

- [x] Auth0 application "Allowed Callback URLs" uses valid wildcard
  `https://*.canonhq.co/auth/callback`
<!-- canon:realized-in: file:gv-infra/experiments/canon/auth0.tf:13-17 -->
- [x] Auth0 application "Allowed Logout URLs" uses `https://*.canonhq.co`
<!-- canon:realized-in: file:gv-infra/experiments/canon/auth0.tf:19-23 -->
- [x] Auth0 application "Allowed Web Origins" uses `https://*.canonhq.co`
<!-- canon:realized-in: file:gv-infra/experiments/canon/auth0.tf:25-29 -->
- [ ] Preview deployments receive JWT access tokens (not opaque) from Auth0
- [ ] RBAC permissions are correctly extracted from the JWT in preview environments
- [ ] The `jwt.DecodeError` warning no longer appears in preview logs

## 4. Verify Helm Chart Compatibility
<!-- canon:status:done -->

Ensure the Helm chart deployment template correctly maps the new M2M env vars from the
`canon-auth0` secret to the application container.

### Acceptance Criteria

- [x] Verify the deployment template uses `envFrom` with the `canon-auth0` secret
  (which automatically exposes all keys as env vars — no template changes needed)
<!-- canon:realized-in: file:chart/canon/templates/deployment.yaml:61-63 -->
- [x] Confirm `values-preview.yaml` does not need changes (preview overrides should
  not affect secret structure)
<!-- canon:realized-in: file:chart/canon/values-preview.yaml (no secrets overrides) -->

## 5. Rollout Plan

1. **Apply Terraform** — Run `terraform apply` in `gv-infra/experiments/canon/` to
   fix the wildcard callback URLs (`pr-*.canonhq.co` → `*.canonhq.co`)
2. **Verify Doppler** — Confirm `AUTH0_M2M_CLIENT_ID` and `AUTH0_M2M_CLIENT_SECRET`
   exist in Doppler `canon/prd` (Terraform outputs already defined in `outputs.tf`)
3. **Merge workflow changes** — Push `preview.yml` and `deploy.yml` M2M additions to main
4. **Test** — Open a PR touching `src/canon/web/` to trigger a preview deploy:
   - No M2M warning in logs
   - JWT access token received (not opaque)
   - Permissions correctly extracted
   - User org membership fetched successfully
5. **Verify production** — Confirm `deploy.yml` M2M changes work on next main push
