---
title: Infrastructure Independence
status: draft
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

<!-- status: done -->

Set up Terraform project structure and state management in this repo.

### Acceptance Criteria

- [x] `infra/` directory with Terraform modules for each concern
- [x] Terraform state stored in DigitalOcean Spaces (S3-compatible) or Terraform Cloud
- [x] `infra/README.md` documenting how to init, plan, apply
- [x] CI workflow for `terraform plan` on PRs touching `infra/`
- [x] CI workflow for `terraform apply` on merge to main (with approval gate)
- [x] Provider versions pinned (digitalocean, aws, auth0, google, stripe, posthog)
- [x] Variables file with environment-specific tfvars (production, staging)

---

## 2. Dedicated DOKS Cluster

<!-- status: in_progress -->

Provision Canon's own Kubernetes cluster on DigitalOcean.

### Acceptance Criteria

- [x] Terraform module for DOKS cluster (region: nyc1, node pool config)
- [x] Node pool sized appropriately (2-3 nodes, s-2vcpu-4gb or similar)
- [x] Auto-upgrade enabled for minor K8s versions
- [x] Cluster tagged for cost tracking (`project:canon`)
- [x] kubeconfig output available for CI/CD workflows
- [ ] Doppler updated with new `DOKS_CLUSTER_NAME` value

---

## 3. Container Registry

<!-- status: in_progress -->

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

<!-- status: in_progress -->

Move DNS record management for `canonhq.co` into this repo's Terraform. The domain is registered with and hosted on AWS Route 53 (not DigitalOcean DNS).

### Acceptance Criteria

- [ ] Terraform AWS provider configured for Route 53 access
- [ ] Import existing Route 53 hosted zone (`canonhq.co`) into Terraform state
- [ ] A record for apex domain pointing to cluster's ingress load balancer IP
- [ ] Wildcard A record `*.canonhq.co` for PR preview environments
- [ ] MX/TXT records preserved from current configuration
- [ ] TTL set to 300s (current value), lower during cutover if needed
- [ ] No references to DigitalOcean DNS — all DNS stays on Route 53

---

## 5. Cluster Bootstrap Services

<!-- status: in_progress -->

Install shared services on the dedicated cluster that were previously provided by gv-infra.

### Acceptance Criteria

- [ ] cert-manager installed via Terraform Helm provider
- [ ] ClusterIssuer for LetsEncrypt (production + staging)
- [ ] nginx-ingress controller installed via Terraform Helm provider
- [ ] Ingress controller gets a DigitalOcean Load Balancer with static IP
- [ ] Load Balancer IP used for DNS A record
- [ ] Monitoring namespace with basic health checks (optional, can defer)

---

## 6. Auth0 Terraform

<!-- status: in_progress -->

Move the full Auth0 configuration (~16KB of HCL in `gv-infra/experiments/canon/auth0.tf`) into this repo's Terraform. This is one of the largest modules — it covers 3 application clients, RBAC with 3 roles and 4 permissions, a post-login Action, organization multi-tenancy, and a test user.

### Acceptance Criteria

**Clients:**
- [ ] Web application (`regular_web`) with callbacks for `canonhq.co`, `*.canonhq.co`
- [ ] Dev application (`regular_web`) with callbacks for `localhost:3000` only
- [ ] M2M application (`non_interactive`) for Management API + Canon backend org queries
- [ ] CLI application (`native`) with Device Authorization Grant (`urn:ietf:params:oauth:grant-type:device_code`) and rotating refresh tokens
- [ ] All clients use RS256 JWT signing

**API & RBAC:**
- [ ] Resource server (`https://canonhq.co/api`) with `access_token_authz` dialect
- [ ] 4 permissions: `specs:read`, `specs:write`, `specs:admin`, `org:manage`
- [ ] 3 roles: Viewer (`specs:read`), Editor (`specs:read` + `specs:write`), Admin (all 4)
- [ ] Role-permission assignments match current config

**Post-Login Action:**
- [ ] `canon-default-role` Action (Node 18, post-login v3 trigger)
- [ ] Auto-assigns Editor role on first GitHub login via M2M Management API
- [ ] Fetches GitHub IdP access token and embeds in `https://canonhq.co/github` ID token claim
- [ ] Action secrets wired: `AUTH0_DOMAIN`, `M2M_CLIENT_ID`, `M2M_CLIENT_SECRET`, `EDITOR_ROLE_ID`

**M2M Grants:**
- [ ] M2M client granted: `create:role_members`, `read:users`, `read:user_idp_tokens`, `read:organizations`

**Organizations:**
- [ ] Auth0 Organizations enabled for multi-tenant access (org_id in token claims)
- [ ] `canonhq` organization created with GitHub + Username-Password connections
- [ ] GitHub connection: `assign_membership_on_login = true` (safe due to restrict_signups gate)
- [ ] Organization usage set to `allow` (login works with or without `?organization=`)

**Connections:**
- [ ] GitHub social connection enabled for all relevant clients
- [ ] Username-Password-Authentication database connection enabled

**Test Infrastructure:**
- [ ] Test user (`hello+canon@njgerner.com`) with Admin role and org membership
- [ ] Import all existing Auth0 resources without disruption
- [ ] Credentials stored in Doppler (already the case)

---

## 7. GCP Vertex AI Terraform

<!-- status: in_progress -->

Move GCP service account and Vertex AI configuration into this repo's Terraform.

### Acceptance Criteria

- [ ] Terraform GCP provider configured
- [ ] Service account for Vertex AI embeddings API
- [ ] IAM roles: `roles/aiplatform.user` on the project
- [ ] Service account key generated and stored in Doppler
- [ ] Project and location configurable via tfvars

---

## 8. CI/CD Workflow Updates

<!-- status: in_progress -->

Update all GitHub Actions workflows to use Canon-owned infrastructure.

### Acceptance Criteria

- [ ] `deploy.yml` uses Canon's own DOKS cluster and DOCR
- [ ] `preview.yml` uses Canon's own cluster for preview namespaces
- [ ] `publish.yml` updated if any registry references changed
- [ ] `ci.yml` updated for any Helm lint changes
- [ ] DevSpace config (`devspace.yaml`) updated for new cluster
- [ ] All workflows tested end-to-end after migration
- [ ] Rollback plan documented in case of deployment failure

---

## 9. Migration Execution

<!-- status: in_progress -->

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

<!-- status: in_progress -->

Move Stripe billing infrastructure into this repo's Terraform. Currently in `gv-infra/experiments/canon/stripe.tf` — covers 2 products with 4 price points, a webhook endpoint, and customer portal configuration.

### Acceptance Criteria

- [ ] Terraform Stripe provider configured
- [ ] 2 products: Canon Starter ($9/seat/month) and Canon Pro ($19/seat/month)
- [ ] 4 prices: monthly + annual for each product (~20% annual discount)
- [ ] Webhook endpoint at `https://canonhq.co/api/webhooks/stripe` with events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`
- [ ] Customer portal configuration with subscription management (upgrade/downgrade, seat changes, cancellation at period end)
- [ ] Import existing Stripe resources (products, prices, webhook, portal) into Terraform state
- [ ] Price IDs output and stored in Doppler (`STRIPE_STARTER_MONTHLY_PRICE_ID`, etc.)
- [ ] Portal supports billing cycle switching (monthly↔annual) and tier changes (Starter↔Pro)

---

## 11. PostHog Terraform

<!-- status: in_progress -->

Move PostHog project and feature flags into this repo's Terraform. Currently in `gv-infra/experiments/canon/posthog.tf`.

### Acceptance Criteria

- [ ] Terraform PostHog provider configured
- [ ] PostHog project (`canon`, timezone: `America/New_York`)
- [ ] Feature flag: `enable-public-signup` (gates GitHub install + paid plan CTAs, default OFF in production)
- [ ] Import existing PostHog project and feature flags into Terraform state
- [ ] PostHog API key and project ID stored in Doppler

---

## 12. Auth0 Organization Auto-Provisioning

<!-- status: in_progress -->

The biggest gap blocking true SaaS onboarding. Currently, when a customer installs the Canon GitHub App, an Auth0 Organization must be manually created via Terraform and linked to the installation via manual SQL (`UPDATE gh_installations SET oidc_org_id = ...`). This section automates that entire flow.

### Acceptance Criteria

**On GitHub App install (`installation.created`):**
- [ ] `on_installation` handler calls Auth0 Management API to create an Organization (name derived from `org_login`)
- [ ] Enable GitHub social connection on the new org with `assign_membership_on_login = true`
- [ ] Enable Username-Password-Authentication connection on the new org
- [ ] Store returned `org_id` on the installation record via `registry.set_oidc_org_id()`
- [ ] No manual SQL or Terraform apply required for new customers

**Auth0 M2M scope expansion:**
- [ ] Add `create:organizations` scope to M2M client grant
- [ ] Add `create:organization_connections` scope to M2M client grant
- [ ] Add `read:connections` scope to M2M client grant (needed to look up connection IDs)
- [ ] Update both Terraform config (§6) and live Auth0 tenant

**On GitHub App uninstall (`installation.deleted`):**
- [ ] Disable the Auth0 Organization (remove connections, preventing login)
- [ ] Log the action but don't delete the org (preserves audit trail)

**Error handling:**
- [ ] Auth0 API failures don't block the installation webhook response
- [ ] Failed provisioning is logged and can be retried manually
- [ ] Idempotent: re-installing the app for the same org reuses or recreates the Auth0 org

---

## 13. GitHub App Configuration

<!-- status: in_progress -->

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
- [ ] Document the canonical App configuration in `infra/README.md`

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
