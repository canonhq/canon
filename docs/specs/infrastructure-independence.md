---
title: Infrastructure Independence
status: in_progress
owner: ng
team: platform
priority: high
tags: [infrastructure, terraform, digitalocean, aws, auth0, stripe, posthog, deployment]
---

# Infrastructure Independence

## Background

Canon's infrastructure is currently managed in the `gv-infra` repo under `experiments/canon/` and `core/`. This creates tight coupling to GV's shared infrastructure: the DOKS cluster (`gv-shared`), container registry, DNS records, Auth0 tenant, and GCP service account are all provisioned and controlled externally. As Canon scales and potentially operates independently, it needs to own its infrastructure end-to-end.

### Current State

| Concern | Where it lives | Canon's control |
|---|---|---|
| DOKS cluster | `gv-infra/core/` | None — shared tenant |
| Container registry (DOCR) | `gv-infra/core/` | Push access only |
| DNS (`canonhq.co`) | `gv-infra/experiments/canon/dns.tf` | None — Route 53 zone |
| cert-manager + nginx-ingress | `gv-infra/core/` | Annotation references |
| Auth0 tenant/apps | `gv-infra/experiments/canon/auth0.tf` | None — 3 clients, RBAC, orgs |
| GCP Vertex AI SA | `gv-infra/experiments/canon/` | None |
| Stripe products/billing | `gv-infra/experiments/canon/stripe.tf` | None — 2 products, portal, webhook |
| PostHog project/flags | `gv-infra/experiments/canon/posthog.tf` | None |
| GitHub App config | GitHub.com settings UI | Manual — not codified |
| Auth0 org provisioning | Manual SQL after Terraform | Manual — blocks SaaS onboarding |
| Doppler secrets | GV Doppler account | Config access |

### Goals

- Canon can be deployed without any dependency on gv-infra
- All infrastructure is codified in this repo via Terraform
- CI/CD workflows reference Canon-owned resources
- Zero-downtime migration from shared to dedicated infrastructure
- Support both Auth0 (managed cloud) and Zitadel (self-hosted)

### Non-Goals

- Migrating off DigitalOcean (staying on DO)
- Migrating off Doppler (keeping current GV Doppler setup)
- Multi-cloud support (DO-first, portability is a future concern)
- Changing the Helm chart structure (it's already well-designed)

---

## 1. Terraform Foundation

<!-- canon:system:1 status:done -->

Set up Terraform project structure and state management in this repo.

### Acceptance Criteria

- [x] `infra/` directory with Terraform modules for each concern
<!-- canon:realized-in:audit file:infra/main.tf -->
<!-- canon:realized-in:PR#480 file:infra/main.tf -->
- [x] Terraform state stored in DigitalOcean Spaces (S3-compatible) or Terraform Cloud. Kubernetes providers use data source lookups instead of module outputs to avoid chicken-and-egg dependency issues during resource imports.
<!-- canon:realized-in:audit file:infra/main.tf:16-27 -->
- [x] `infra/README.md` documenting how to init, plan, apply
<!-- canon:realized-in:audit file:infra/README.md -->
- [x] CI workflow for `terraform plan` on PRs touching `infra/`
<!-- canon:realized-in:audit file:.github/workflows/terraform.yml:18-103 -->
- [x] CI workflow for `terraform apply` on merge to main (with approval gate)
<!-- canon:realized-in:audit file:.github/workflows/terraform.yml:105-143 -->
- [x] Provider versions pinned (digitalocean, aws, auth0, google, stripe, posthog)
<!-- canon:realized-in:audit file:infra/versions.tf -->
- [x] Variables file with environment-specific tfvars (production, staging)
<!-- canon:realized-in:audit file:infra/terraform.tfvars -->

---

## 2. Dedicated DOKS Cluster

<!-- canon:system:2 status:in_progress -->

Provision Canon's own Kubernetes cluster on DigitalOcean. During migration, Canon uses the existing gv-shared cluster and registry to avoid disruption. A dedicated cluster and registry will be provisioned in a future phase.

### Acceptance Criteria

- [x] Terraform module for DOKS cluster (region: nyc1, node pool config)
<!-- canon:realized-in:audit file:infra/modules/doks/main.tf -->
- [x] Node pool sized appropriately (2-3 nodes, s-2vcpu-4gb or similar)
<!-- canon:realized-in:audit file:infra/terraform.tfvars:15-16 -->
- [x] Auto-upgrade enabled for minor K8s versions
<!-- canon:realized-in:audit file:infra/modules/doks/main.tf:34 -->
- [x] Cluster tagged for cost tracking (`project:canon`)
<!-- canon:realized-in:audit file:infra/modules/doks/main.tf:31,38 -->
- [x] kubeconfig output available for CI/CD workflows
<!-- canon:realized-in:audit file:infra/modules/doks/outputs.tf -->
- [ ] Doppler updated with new `DOKS_CLUSTER_NAME` value

---

## 3. Container Registry

<!-- canon:system:3 status:in_progress -->

Set up Canon's own container registry on DigitalOcean.

### Acceptance Criteria

- [x] Terraform resource for DOCR registry (or dedicated subscription)
- [x] Registry credentials available to the DOKS cluster (K8s pull secret)
- [ ] CI/CD workflows updated to push to new registry
- [ ] Doppler updated with new `DOCR_REGISTRY_NAME` value
- [ ] Old images in `gv-shared` registry cleaned up after migration
- [ ] `values-production.yaml` updated with new registry path

---

## 4. DNS Management

<!-- canon:system:4 status:in_progress -->

Move DNS record management for `canonhq.co` into this repo's Terraform. The domain is registered with and hosted on AWS Route 53 (not DigitalOcean DNS).

### Acceptance Criteria

- [x] Terraform AWS provider configured for Route 53 access
<!-- canon:realized-in:audit file:infra/main.tf:61-68 -->
- [ ] Import existing Route 53 hosted zone (`canonhq.co`) into Terraform state
- [x] A record for apex domain pointing to cluster's ingress load balancer IP
<!-- canon:realized-in:audit file:infra/modules/dns/main.tf:25-31 -->
- [x] Wildcard A record `*.canonhq.co` for PR preview environments
<!-- canon:realized-in:audit file:infra/modules/dns/main.tf:33-39 -->
- [ ] MX/TXT records preserved from current configuration
- [x] TTL set to 300s (current value), lower during cutover if needed
<!-- canon:realized-in:audit file:infra/modules/dns/main.tf:30,38 -->
- [x] No references to DigitalOcean DNS — all DNS stays on Route 53
<!-- canon:realized-in:audit file:infra/modules/dns/main.tf -->

---

## 5. Cluster Bootstrap Services

<!-- canon:system:5 status:done -->

Install shared services on the dedicated cluster that were previously provided by gv-infra.

### Acceptance Criteria

- [x] cert-manager installed via Terraform Helm provider
<!-- canon:realized-in:audit file:infra/modules/bootstrap/main.tf:40-51 -->
- [x] ClusterIssuer for LetsEncrypt (production + staging)
<!-- canon:realized-in:audit file:infra/modules/bootstrap/main.tf:55-74 -->
- [x] nginx-ingress controller installed via Terraform Helm provider
<!-- canon:realized-in:audit file:infra/modules/bootstrap/main.tf:25-36 -->
- [x] Ingress controller gets a DigitalOcean Load Balancer with static IP
<!-- canon:realized-in:audit file:infra/modules/bootstrap/main.tf:78-85 -->
- [x] Load Balancer IP used for DNS A record
<!-- canon:realized-in:audit file:infra/main.tf:134 -->
- [ ] Monitoring namespace with basic health checks (optional, can defer)

---

## 6. Auth0 Terraform

<!-- canon:system:6 status:done -->

Move the full Auth0 configuration (~16KB of HCL in `gv-infra/experiments/canon/auth0.tf`) into this repo's Terraform. This is one of the largest modules — it covers 3 application clients, RBAC with 3 roles and 4 permissions, a post-login Action, organization multi-tenancy, and a test user.

### Acceptance Criteria

**Clients:**
- [x] Web application (`regular_web`) with callbacks for `canonhq.co`, `*.canonhq.co`
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:26-54 -->
- [x] Dev application (`regular_web`) with callbacks for `localhost:3000` only
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:63-93 -->
- [x] M2M application (`non_interactive`) for Management API + Canon backend org queries
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:137-167 -->
- [x] CLI application (`native`) with Device Authorization Grant (`urn:ietf:params:oauth:grant-type:device_code`) and rotating refresh tokens
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:97-121 -->
- [x] All clients use RS256 JWT signing
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:51-53,85-87,118-120,144-146 -->

**API & RBAC:**
- [x] Resource server (`https://canonhq.co/api`) with `access_token_authz` dialect
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:171-180 -->
- [x] 4 permissions: `specs:read`, `specs:write`, `specs:admin`, `org:manage`
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:182-204 -->
- [x] 3 roles: Viewer (`specs:read`), Editor (`specs:read` + `specs:write`), Admin (all 4)
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:208-273 -->
- [x] Role-permission assignments match current config
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:225-273 -->

**Post-Login Action:**
- [x] `canon-default-role` Action (Node 18, post-login v3 trigger)
<!-- canon:realized-in:audit file:infra/modules/auth0/action.tf:5-13 -->
- [x] Auto-assigns Editor role on first GitHub login via M2M Management API
<!-- canon:realized-in:audit file:infra/modules/auth0/action.tf:76-94 -->
- [x] Fetches GitHub IdP access token and embeds in `https://canonhq.co/github` ID token claim
<!-- canon:realized-in:audit file:infra/modules/auth0/action.tf:48-73 -->
- [x] Action secrets wired: `AUTH0_DOMAIN`, `M2M_CLIENT_ID`, `M2M_CLIENT_SECRET`, `EDITOR_ROLE_ID`
<!-- canon:realized-in:audit file:infra/modules/auth0/action.tf:103-122 -->

**M2M Grants:**
- [x] M2M client granted: `create:role_members`, `read:users`, `read:user_idp_tokens`, `read:organizations`
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:154-167 -->

**Organizations:**
- [x] Auth0 Organizations enabled for multi-tenant access (org_id in token claims)
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:48-49 -->
- [x] `canonhq` organization created with GitHub + Username-Password connections
<!-- canon:realized-in:audit file:infra/modules/auth0/org.tf:5-25 -->
- [x] GitHub connection: `assign_membership_on_login = true` (safe due to restrict_signups gate)
<!-- canon:realized-in:audit file:infra/modules/auth0/org.tf:18 -->
- [x] Organization usage set to `allow` (login works with or without `?organization=`)
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:48 -->

**Connections:**
- [x] GitHub social connection enabled for all relevant clients
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:20-21 -->
- [x] Username-Password-Authentication database connection enabled
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:125-133 -->

**Test Infrastructure:**
- [x] Test user (`hello+canon@njgerner.com`) with Admin role and org membership
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:277-288 file:infra/modules/auth0/org.tf:28-38 -->
- [ ] Import all existing Auth0 resources without disruption
- [x] Credentials stored in Doppler (already the case)

---

## 7. GCP Vertex AI Terraform

<!-- canon:system:7 status:done -->

Move GCP service account and Vertex AI configuration into this repo's Terraform.

### Acceptance Criteria

- [x] Terraform GCP provider configured
<!-- canon:realized-in:audit file:infra/main.tf:70-75 -->
- [x] Service account for Vertex AI embeddings API
<!-- canon:realized-in:audit file:infra/modules/gcp/main.tf:19-24 -->
- [x] IAM roles: `roles/aiplatform.user` on the project
<!-- canon:realized-in:audit file:infra/modules/gcp/main.tf:26-30 -->
- [x] Service account key generated and stored in Doppler
<!-- canon:realized-in:audit file:infra/modules/gcp/main.tf:32-34 -->
- [x] Project and location configurable via tfvars
<!-- canon:realized-in:audit file:infra/terraform.tfvars:24-25 -->

---

## 8. CI/CD Workflow Updates

<!-- canon:system:8 status:in_progress -->

Update all GitHub Actions workflows to use Canon-owned infrastructure.

### Acceptance Criteria

- [x] `deploy.yml` uses Canon's own DOKS cluster and DOCR
<!-- canon:realized-in:audit file:.github/workflows/deploy.yml:62,70 -->
- [x] `preview.yml` uses Canon's own cluster for preview namespaces
<!-- canon:realized-in:audit file:.github/workflows/preview.yml:58,65 -->
- [ ] `publish.yml` updated if any registry references changed
- [ ] `ci.yml` updated for any Helm lint changes
- [ ] DevSpace config (`devspace.yaml`) updated for new cluster
- [ ] All workflows tested end-to-end after migration
- [x] Rollback plan documented in case of deployment failure
<!-- canon:realized-in:audit file:infra/README.md:170-189 -->

---

## 9. Migration Execution

<!-- canon:system:9 status:in_progress -->

Execute the actual cutover from shared to dedicated infrastructure.

### Acceptance Criteria

- [ ] New cluster running and accessible
- [ ] Application deployed and healthy on new cluster
- [ ] DNS cutover with minimal downtime (< 5 minutes)
- [ ] SSL certificates issued successfully on new cluster
- [ ] All cron jobs running on new cluster
- [ ] Preview environments functional on new cluster
- [ ] Stripe webhook endpoint updated and receiving events
- [ ] PostHog project and feature flags operational
- [ ] Auth0 org auto-provisioning tested with a new GitHub App install
- [ ] GitHub App settings verified against §13 checklist
- [ ] Smoke tests pass post-migration
- [ ] Old cluster resources cleaned up (namespace, secrets, images)
- [ ] gv-infra Canon-specific Terraform marked as deprecated/removed

---

## 10. Stripe Terraform

<!-- canon:system:10 status:done -->

Move Stripe billing infrastructure into this repo's Terraform. Currently in `gv-infra/experiments/canon/stripe.tf` — covers 2 products with 4 price points, a webhook endpoint, and customer portal configuration.

### Acceptance Criteria

- [x] Terraform Stripe provider configured
<!-- canon:realized-in:audit file:infra/main.tf:83-85 file:infra/versions.tf:29-32 -->
- [x] 2 products: Canon Starter ($9/seat/month) and Canon Pro ($19/seat/month)
<!-- canon:realized-in:audit file:infra/modules/stripe/main.tf:16-34 -->
- [x] 4 prices: monthly + annual for each product (~20% annual discount)
<!-- canon:realized-in:audit file:infra/modules/stripe/main.tf:38-108 -->
- [x] Webhook endpoint at `https://canonhq.co/api/webhooks/stripe` with events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`
<!-- canon:realized-in:audit file:infra/modules/stripe/main.tf:112-127 -->
- [x] Customer portal configuration with subscription management (upgrade/downgrade, seat changes, cancellation at period end)
<!-- canon:realized-in:audit file:infra/modules/stripe/main.tf:131-181 -->
- [ ] Import existing Stripe resources (products, prices, webhook, portal) into Terraform state
- [ ] Price IDs output and stored in Doppler (`STRIPE_STARTER_MONTHLY_PRICE_ID`, etc.)
- [x] Portal supports billing cycle switching (monthly↔annual) and tier changes (Starter↔Pro)
<!-- canon:realized-in:audit file:infra/modules/stripe/main.tf:165-178 -->

---

## 11. PostHog Terraform

<!-- canon:system:11 status:done -->

Move PostHog project and feature flags into this repo's Terraform. Currently in `gv-infra/experiments/canon/posthog.tf`.

### Acceptance Criteria

- [x] Terraform PostHog provider configured
<!-- canon:realized-in:audit file:infra/main.tf:87-91 file:infra/versions.tf:33-36 -->
- [x] PostHog project (`canon`, timezone: `America/New_York`)
<!-- canon:realized-in:audit file:infra/modules/posthog/main.tf:14-17 -->
- [x] Feature flag: `enable-public-signup` (gates GitHub install + paid plan CTAs, default OFF in production)
<!-- canon:realized-in:audit file:infra/modules/posthog/main.tf:21-27 -->
- [ ] Import existing PostHog project and feature flags into Terraform state
- [ ] PostHog API key and project ID stored in Doppler

---

## 12. Auth0 Organization Auto-Provisioning

<!-- canon:system:12 status:done -->

The biggest gap blocking true SaaS onboarding. Currently, when a customer installs the Canon GitHub App, an Auth0 Organization must be manually created via Terraform and linked to the installation via manual SQL (`UPDATE gh_installations SET oidc_org_id = ...`). This section automates that entire flow.

### Acceptance Criteria

**On GitHub App install (`installation.created`):**
- [x] `on_installation` handler calls Auth0 Management API to create an Organization (name derived from `org_login`)
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_installation.py:126-147 -->
- [x] Enable GitHub social connection on the new org with `assign_membership_on_login = true`
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_installation.py:141-143 -->
- [x] Enable Username-Password-Authentication connection on the new org
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_installation.py:142 -->
- [x] Store returned `org_id` on the installation record via `registry.set_oidc_org_id()`
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_installation.py:144 -->
- [x] No manual SQL or Terraform apply required for new customers

**Auth0 M2M scope expansion:**
- [x] Add `create:organizations` scope to M2M client grant
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:162 -->
- [x] Add `create:organization_connections` scope to M2M client grant
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:163 -->
- [x] Add `read:connections` scope to M2M client grant (needed to look up connection IDs)
<!-- canon:realized-in:audit file:infra/modules/auth0/main.tf:165 -->
- [x] Update both Terraform config (§6) and live Auth0 tenant

**On GitHub App uninstall (`installation.deleted`):**
- [x] Disable the Auth0 Organization (remove connections, preventing login)
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_installation.py:100-106 -->
- [x] Log the action but don't delete the org (preserves audit trail)
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_installation.py:108 -->

**Error handling:**
- [x] Auth0 API failures don't block the installation webhook response
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_installation.py:93 -->
- [x] Failed provisioning is logged and can be retried manually
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_installation.py:146-147 -->
- [x] Idempotent: re-installing the app for the same org reuses or recreates the Auth0 org
<!-- canon:realized-in:audit file:src/canon/github/handlers/on_installation.py:134-136 -->

---

## 13. GitHub App Configuration

<!-- canon:system:13 status:in_progress -->

The Canon GitHub App is configured manually in the GitHub UI. This section documents the required configuration and verifies it matches production needs. Not Terraform-managed, but must be audited and locked down.

### Acceptance Criteria

**App settings:**
- [ ] Setup URL set to `https://canonhq.co/app/setup/complete`
- [ ] Visibility set to "Any account" (required for SaaS)
- [ ] Homepage URL set to `https://canonhq.co`

**Required webhook events (and no others):**
- [ ] Issue comment
- [ ] Issues
- [ ] Pull request
- [ ] Pull request review
- [ ] Push

**Required permissions:**
- [ ] Contents: Read & Write
- [ ] Issues: Read & Write
- [ ] Pull requests: Read & Write
- [ ] Metadata: Read-only

**Cleanup:**
- [ ] Remove any unnecessary event subscriptions not in the list above
- [ ] Remove any unnecessary permissions not in the list above
- [x] Document the canonical App configuration in `infra/README.md`
<!-- canon:realized-in:audit file:infra/README.md:146-168 -->

---

## Technical Design

### Directory Structure

```
infra/
  main.tf              # Provider config, backend, module calls
  variables.tf         # Input variables
  outputs.tf           # Cluster endpoint, registry URL, LB IP, price IDs
  terraform.tfvars     # Production values (non-secret)
  versions.tf          # Provider version constraints
  modules/
    doks/              # DOKS cluster + node pools
    docr/              # Container registry
    dns/               # Route 53 zone + A/wildcard records
    bootstrap/         # cert-manager, nginx-ingress (Helm releases)
    auth0/             # Auth0 clients, RBAC, orgs, post-login Action
    gcp/               # GCP project, SA, IAM
    stripe/            # Products, prices, webhook, portal
    posthog/           # Project, feature flags
```

### State Management

Terraform state stored in DigitalOcean Spaces (S3-compatible backend):

```hcl
terraform {
  backend "s3" {
    endpoints = { s3 = "https://nyc3.digitaloceanspaces.com" }
    bucket    = "canon-terraform-state"
    key       = "production/terraform.tfstate"
    region    = "us-east-1"  # required but ignored by DO
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
  }
}
```

### Migration Strategy

1. **Parallel deployment** — Stand up new cluster alongside existing
2. **Test on new cluster** — Deploy and verify before DNS cutover
3. **DNS cutover** — Lower TTL, switch A record, monitor
4. **Cleanup** — Remove Canon resources from gv-shared cluster

### Auth Provider Strategy

The Helm chart already supports both Auth0 and Zitadel:
- **Auth0**: Managed cloud deployments, Terraform in `infra/modules/auth0/`
- **Zitadel**: Self-hosted deployments, bundled via Helm dependency
- `AUTH_PROVIDER` setting auto-detects based on which credentials are configured

---

## Rollout Plan

### Phase 1: Foundation (Week 1)
- Sections 1-3: Terraform setup, DOKS cluster, container registry
- Validate: cluster accessible, images push/pull

### Phase 2: Service Imports (Week 2)
- Section 4: DNS module — import Route 53 zone (don't change records yet)
- Section 5: Cluster bootstrap — cert-manager, nginx-ingress
- Section 6: Auth0 Terraform — import all clients, RBAC, orgs, Action
- Section 7: GCP Vertex AI — import service account
- Section 10: Stripe Terraform — import products, prices, webhook, portal
- Section 11: PostHog Terraform — import project, feature flags
- Validate: `terraform plan` shows no diff after imports

### Phase 3: SaaS Automation (Week 3)
- Section 12: Auth0 org auto-provisioning — code changes to `on_installation.py`, M2M scope expansion
- Section 13: GitHub App configuration audit and lockdown
- Validate: new GitHub App install auto-creates Auth0 org, login works end-to-end

### Phase 4: Cutover (Week 4)
- Section 8: Update CI/CD workflows
- Section 9: Execute migration — full cutover checklist
- Validate: full deployment pipeline works, zero-downtime DNS switch
