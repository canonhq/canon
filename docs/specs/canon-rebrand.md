---
title: "Canon Rebrand & Experience Unification"
status: draft
owner: ng
team: platform
ticket_project: canonhq/canon
created: 2026-03-04
updated: 2026-03-04
tags: [branding, rebrand, infrastructure, frontend, cli, dx]
---

# Canon Rebrand & Experience Unification

Rebrand Specwright → Canon across all public-facing surfaces. Establish a cohesive product identity before scaling the GitHub App to external users. Canon is a spec-driven development platform — the source of truth for what your org is building.

## 1. Background

Specwright started as an internal experiment at Gerner Ventures. The codebase carries that DNA: the GitHub App slug is `gv-specwright`, the package is `gv-specwright`, the README frames it as a "4-week experiment," and the footer says "an experiment by Gerner Ventures." None of this inspires confidence for external users.

Making the GitHub App public exposed the gap: there is no cohesive brand. The marketing site says one thing, the CLI says another, and the GitHub App description still references "documentation" (the old positioning). Before scaling to external orgs, we need a unified identity that communicates what Canon actually is.

**New identity:**
- **Name**: Canon
- **Tagline**: "The source of truth for what you're building."
- **Namespace**: `canonhq` (GitHub org, PyPI, domain, GitHub App slug)
- **CLI**: `canon`
- **Domain**: `canonhq.co`
- **Voice**: Clean, confident, concise. Product voice. "Early access" not "experiment."

See also: `docs/plans/2026-03-04-canon-rebrand-design.md` for the full design exploration.

## 2. Register Namespace & Foundation

<!-- canon:system:2 status:done -->

Secure all external namespaces before any code changes.

### Acceptance Criteria

- [x] `canonhq` GitHub organization created (under njgerner account)
<!-- canon:realized-in:PR#327 file:.github/scripts/export-oss.sh -->
- [x] `canonhq.co` domain registered
- [x] New `canonhq` GitHub App created (App ID: 3012101) with correct permissions and event subscriptions
- [x] GitHub App has logo uploaded
- [x] `canonhq` PyPI package name reserved (published 0.0.1.dev0 placeholder)
<!-- canon:realized-in:PR#327 file:uv.lock -->

## 3. Visual Identity

<!-- specwright:system:3 status:todo -->

Establish the visual brand for Canon.

### Acceptance Criteria

- [ ] Wordmark designed: "Canon" in Space Grotesk with emerald→cyan gradient
- [ ] App icon designed: geometric mark suitable for GitHub App avatar, favicon, and OG image
- [ ] OG image created at `/static/og-image.png` (currently referenced but missing)
- [ ] Favicon updated
- [ ] CSS custom properties renamed from `--sw-*` / brand tokens to `--canon-*` prefix in `static/brand.css`

## 4. Python Module Rename

<!-- specwright:system:4 status:todo -->

Rename the internal Python module from `specwright` to `canon`.

### Acceptance Criteria

- [ ] `src/specwright/` renamed to `src/canon/`
- [ ] All internal imports updated (`from specwright.X` → `from canon.X`)
- [ ] All test imports updated (`from specwright.X` → `from canon.X`)
- [ ] `pyproject.toml` updated: name=`canonhq`, module path=`src/canon`, entry points updated
- [ ] Dockerfile updated with new module paths
- [ ] All `ruff check` and `pytest` pass after rename
- [ ] No remaining references to `specwright` in Python source (except migration/deprecation shims)

## 5. CLI Rebrand

<!-- specwright:system:5 status:todo -->

Update all CLI user-facing text and entry points.

### Acceptance Criteria

- [ ] CLI entry point renamed: `canon` (pyproject.toml `[project.scripts]`)
- [ ] MCP entry point renamed: `canon-mcp`
- [ ] Help text updated: `canon — Spec-driven development platform`
- [ ] All subcommand help strings reference "Canon" not "Specwright"
- [ ] Default server URL updated to `https://canonhq.co` (with env var override)
- [ ] `canon setup` creates `CANON.yaml` (not `SPECWRIGHT.yaml`)
- [ ] Migration: if `SPECWRIGHT.yaml` exists and `CANON.yaml` does not, prompt user to rename
- [ ] Login flow references Canon branding

## 6. Marketing Website Update

<!-- specwright:system:6 status:todo -->

Update the Vue SPA marketing site with Canon branding and messaging.

### Acceptance Criteria

- [ ] All "Specwright" text references → "Canon" across all Vue components
- [ ] Hero section: updated tagline and description
- [ ] Nav wordmark: "Canon" with updated styling
- [ ] Footer: "Canon" (drop "experiment" language; optionally "by Gerner Ventures" in small print)
- [ ] All GitHub App install URLs point to `github.com/apps/canonhq`
- [ ] OG/Twitter meta tags reference Canon name, tagline, and new OG image
- [ ] Stale Jinja2 fallback `templates/landing.html` removed or updated
- [ ] Welcome page (`templates/welcome.html`) updated with Canon branding
- [ ] Error pages (404, 500) updated with Canon branding
- [ ] Base template (`templates/base.html`) wordmark and footer updated

## 7. MCP Server & Claude Code Skills

<!-- specwright:system:7 status:todo -->

Update the MCP server identity and all Claude Code skill definitions.

### Acceptance Criteria

- [ ] MCP server name: `canon`
- [ ] MCP server description updated with Canon messaging
- [ ] All Claude Code skill names renamed: `sw:*` → `canon:*`
- [ ] All skill descriptions reference "Canon" not "Specwright"
- [ ] Plugin directory/package references updated
- [ ] Skills install correctly via `canon setup`

## 8. Helm Chart & Deployment

<!-- specwright:system:8 status:todo -->

Update the Helm chart and deployment configuration.

### Acceptance Criteria

- [ ] Helm chart name: `canon`
- [ ] Chart.yaml: updated name, description, keywords
- [ ] `values.yaml` / `values-production.yaml`: updated image references, hostnames
- [ ] Ingress configured for `canonhq.co` with TLS
- [ ] `specwright.gernerventures.com` redirects to `canonhq.co`
- [ ] Docker image registry path updated (or aliased)
- [ ] All Helm templates reference correct service/app names

## 9. Documentation & README

<!-- specwright:system:9 status:todo -->

Rewrite public-facing documentation with Canon identity.

### Acceptance Criteria

- [ ] README.md rewritten as product README (not experiment brief): what it is, how to install, quick start, link to docs
- [ ] `docs/self-hosting.md` updated with Canon references
- [ ] `docs/vision.md` updated (or archived if superseded)
- [ ] CLAUDE.md updated with Canon project description
- [ ] All spec files' `ticket_project` fields updated if repo moves to `canonhq/canon`
- [ ] `github-app-manifest.json` updated for new app

## 10. Config File Migration

<!-- specwright:system:10 status:todo -->

Ensure smooth transition for existing users who have `SPECWRIGHT.yaml` files.

### Acceptance Criteria

- [ ] Config parser checks for `CANON.yaml` first, falls back to `SPECWRIGHT.yaml`
- [ ] `canon setup` creates `CANON.yaml`
- [ ] When `SPECWRIGHT.yaml` is detected without `CANON.yaml`, CLI prints migration notice with rename command
- [ ] All internal references to config filename use a constant (not hardcoded strings)
- [ ] Spec status comments migrate: `<!-- specwright:system:N -->` → `<!-- canon:system:N -->` (with backwards-compatible parsing)

## 11. GitHub App Migration

<!-- specwright:system:11 status:todo -->

Migrate existing installations from old `gv-specwright` app to new `canonhq` app.

### Acceptance Criteria

- [ ] New `canonhq` app tested on `njgerner` personal account
- [ ] New app installed on `Gerner-Ventures` org
- [ ] Webhook endpoint accepts events from both old and new app during transition
- [ ] Old `gv-specwright` app description updated with deprecation notice pointing to `canonhq`
- [ ] Migration documented: users install new app, remove old app

## 12. Rollout Plan

<!-- specwright:system:12 status:todo -->

Phased rollout to minimize disruption.

**Phase 1 — Foundation** (sections 2, 3):
Register namespaces, design visual identity. No code changes, no user impact.

**Phase 2 — Code rebrand** (sections 4, 5, 6, 7, 9, 10):
Single large PR (or branch) with all rename changes. Internal only until merged and deployed.

**Phase 3 — Infrastructure rebrand** (sections 8, 13, 14):
Update gv-infra Terraform (DNS, Auth0, GCP, Doppler, K8s, PostHog), transfer repo to `canonhq/canon`, deploy to `canonhq.co`, configure redirects, publish to PyPI. Coordinate Terraform apply with app deployment.

**Phase 4 — App migration** (section 11):
Create new GitHub App, test, migrate installations, deprecate old app.

### Acceptance Criteria

- [ ] Phase 1 completed and verified before Phase 2 begins
- [ ] Phase 2 changes pass full test suite before merge
- [ ] Phase 3 infrastructure verified: Terraform applied cleanly, `canonhq.co` serves correctly, old domain redirects
- [ ] Phase 4 migration tested on personal account before org-wide rollout

## 13. Repo Transfer

<!-- specwright:system:13 status:todo -->

Transfer the repository from `Gerner-Ventures/gv-exp-specwright` to `canonhq/canon`.

### Acceptance Criteria

- [ ] Repo transferred from `Gerner-Ventures/gv-exp-specwright` → `canonhq/canon`
<!-- canon:realized-in:PR#323 file:.github/scripts/export-oss.sh -->
- [ ] GitHub auto-redirect from old URL is active
- [ ] All spec `ticket_project` frontmatter fields updated to `canonhq/canon`
- [ ] CI/CD workflows updated with new repo references
- [ ] Docker image registry path updated (or new registry under `canonhq`)
- [ ] All hardcoded `Gerner-Ventures/gv-exp-specwright` references in code updated
- [ ] PyPI project URLs updated to point to `canonhq/canon`

## 14. Infrastructure Rebrand (gv-infra)

<!-- specwright:system:14 status:todo -->

Update all Specwright infrastructure managed in the `gv-infra` repo under `experiments/specwright/`. This is a cross-repo change that must be coordinated with the app code rebrand.

### 14.1 DNS

Update Route 53 records in `experiments/specwright/dns.tf`:

- [ ] A record `specwright.gernerventures.com` → redirect to `canonhq.co` (or keep as legacy redirect)
- [ ] A record `*.specwright.gernerventures.com` → redirect or remove
- [ ] New hosted zone for `canonhq.co` with A records pointing to DOKS ingress LB
- [ ] Wildcard `*.canonhq.co` for preview deployments

### 14.2 Auth0

Update Auth0 resources in `experiments/specwright/auth0.tf`:

- [ ] Web app client: display name → "Canon", callback/logout/origin URLs → `canonhq.co`
- [ ] API resource server: identifier → `https://canonhq.co/api`, name → "Canon API"
- [ ] Roles renamed: "Specwright Viewer/Editor/Admin" → "Canon Viewer/Editor/Admin"
- [ ] M2M client: name → "Canon Action (M2M)"
- [ ] Post-login action: name → "canon-default-role", custom claim namespace → `https://canonhq.co/` prefix
- [ ] CLI native app client: name → "Canon CLI"
- [ ] Test user email updated (e.g. `hello+canon@njgerner.com`)
- [ ] `core/terraform.tfvars`: action name updated in `experiment_post_login_actions`
- [ ] `core/auth0.tf`: service account allowlist email updated
- [ ] App code updated: custom claim namespace in `auth/routes.py` and `auth/device_routes.py` matches new Auth0 action

### 14.3 GCP Vertex AI

Update GCP resources in `experiments/specwright/gcp.tf`:

- [ ] New service account created (e.g. `canon-embeddings`) — old `account_id` is immutable
- [ ] New SA key generated and stored in Doppler
- [ ] Old SA decommissioned after cutover
- [ ] IAM bindings updated for new SA

### 14.4 Doppler

- [ ] Doppler project renamed or new project created: `specwright` → `canon`
- [ ] All secrets migrated to new project
- [ ] CI/CD workflows updated: `doppler-project: canon`
- [ ] `AUTH0_AUDIENCE` secret value updated to new API identifier

### 14.5 Kubernetes Resources

Update K8s resources in CI/CD workflows (`deploy.yml`, `preview.yml`):

- [ ] Namespace: `specwright` → `canon`
- [ ] Secrets renamed: `specwright-github`, `specwright-anthropic`, `specwright-neon`, `specwright-gcp`, `specwright-auth0`, `specwright-posthog` → `canon-*`
- [ ] Helm release name: `specwright` → `canon`
- [ ] Preview namespace pattern: `specwright-preview-N` → `canon-preview-N`
- [ ] Bot username filter in `claude-code-review.yml`: `gv-specwright[bot]` → `canonhq[bot]`

### 14.6 Docker Registry

- [ ] Image path updated: `registry.digitalocean.com/gv-shared/specwright` → `gv-shared/canon`
- [ ] CI build tag updated in `ci.yml`
- [ ] Preview cleanup command updated in `preview.yml`

### 14.7 PostHog

Update PostHog resources in `experiments/specwright/posthog.tf`:

- [ ] Project name: `specwright` → `canon`
- [ ] Output variable names updated

### 14.8 Terraform State

- [ ] Directory renamed: `experiments/specwright/` → `experiments/canon/`
- [ ] State key migrated: `experiments/specwright/terraform.tfstate` → `experiments/canon/terraform.tfstate`
- [ ] State migration performed via `terraform state mv` or manual S3 object copy

### 14.9 Helm Chart Internal References

Update all Helm template helpers in `chart/specwright/templates/_helpers.tpl`:

- [ ] Chart directory renamed: `chart/specwright/` → `chart/canon/`
- [ ] All Go template function names renamed: `specwright.*` → `canon.*`
- [ ] All template files updated to use new function names
- [ ] `values-production.yaml`: secret names, hostnames, platformUrl updated
- [ ] `values-preview.yaml`: preview URL pattern updated
- [ ] CI helm-lint commands updated with new paths and hostnames

## 15. Open Questions

- Canon Inc. trademark: worth a brief legal review for dev tools class?
- Should we publish a deprecation release of `gv-specwright` on PyPI that prints "this package has moved to canonhq"?
- Timeline for `canonhq.com` acquisition (currently parked by blockchain registrar)?
