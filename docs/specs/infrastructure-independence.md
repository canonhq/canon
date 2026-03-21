---
title: Infrastructure Independence
status: draft
owner: ng
team: platform
priority: high
tags: [infrastructure, terraform, digitalocean, deployment]
---

# Infrastructure Independence

## Background

Canon's infrastructure is currently managed in the `gv-infra` repo under `experiments/canon/` and `core/`. This creates tight coupling to GV's shared infrastructure: the DOKS cluster (`gv-shared`), container registry, DNS records, Auth0 tenant, and GCP service account are all provisioned and controlled externally. As Canon scales and potentially operates independently, it needs to own its infrastructure end-to-end.

### Current State

| Concern | Where it lives | Canon's control |
|---|---|---|
| DOKS cluster | `gv-infra/core/` | None — shared tenant |
| Container registry (DOCR) | `gv-infra/core/` | Push access only |
| DNS (`canonhq.co`) | `gv-infra/experiments/canon/` | None |
| cert-manager + nginx-ingress | `gv-infra/core/` | Annotation references |
| Auth0 tenant/apps | `gv-infra/experiments/canon/auth0.tf` | None |
| GCP Vertex AI SA | `gv-infra/experiments/canon/` | None |
| Stripe products | `gv-infra/experiments/canon/stripe.tf` | None |
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

<!-- status: todo -->

Set up Terraform project structure and state management in this repo.

### Acceptance Criteria

- [ ] `infra/` directory with Terraform modules for each concern
- [ ] Terraform state stored in DigitalOcean Spaces (S3-compatible) or Terraform Cloud
- [ ] `infra/README.md` documenting how to init, plan, apply
- [ ] CI workflow for `terraform plan` on PRs touching `infra/`
- [ ] CI workflow for `terraform apply` on merge to main (with approval gate)
- [ ] Provider versions pinned (digitalocean, auth0, google, stripe)
- [ ] Variables file with environment-specific tfvars (production, staging)

---

## 2. Dedicated DOKS Cluster

<!-- status: todo -->

Provision Canon's own Kubernetes cluster on DigitalOcean.

### Acceptance Criteria

- [ ] Terraform module for DOKS cluster (region: nyc1, node pool config)
- [ ] Node pool sized appropriately (2-3 nodes, s-2vcpu-4gb or similar)
- [ ] Auto-upgrade enabled for minor K8s versions
- [ ] Cluster tagged for cost tracking (`project:canon`)
- [ ] kubeconfig output available for CI/CD workflows
- [ ] Doppler updated with new `DOKS_CLUSTER_NAME` value

---

## 3. Container Registry

<!-- status: todo -->

Set up Canon's own container registry on DigitalOcean.

### Acceptance Criteria

- [ ] Terraform resource for DOCR registry (or dedicated subscription)
- [ ] Registry credentials available to the DOKS cluster (K8s pull secret)
- [ ] CI/CD workflows updated to push to new registry
- [ ] Doppler updated with new `DOCR_REGISTRY_NAME` value
- [ ] Old images in `gv-shared` registry cleaned up after migration
- [ ] `values-production.yaml` updated with new registry path

---

## 4. DNS Management

<!-- status: todo -->

Move DNS record management for `canonhq.co` into this repo's Terraform.

### Acceptance Criteria

- [ ] Terraform module for DigitalOcean DNS zone (`canonhq.co`)
- [ ] A record pointing to new cluster's ingress load balancer IP
- [ ] Wildcard record `*.canonhq.co` for preview environments
- [ ] MX/TXT records preserved from current configuration
- [ ] TTL set appropriately for migration (low during cutover, normal after)
- [ ] Import existing DNS state into Terraform without downtime

---

## 5. Cluster Bootstrap Services

<!-- status: todo -->

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

<!-- status: todo -->

Move Auth0 configuration into this repo's Terraform.

### Acceptance Criteria

- [ ] Terraform Auth0 provider configured
- [ ] Web application (SPA) with correct callback URLs
- [ ] M2M application for Management API access
- [ ] Native application for CLI device auth flow
- [ ] Organization settings configured
- [ ] Callback URLs include `canonhq.co`, `*.canonhq.co`, `localhost:*`
- [ ] Import existing Auth0 resources without disruption
- [ ] Auth0 credentials stored in Doppler (already the case)

---

## 7. GCP Vertex AI Terraform

<!-- status: todo -->

Move GCP service account and Vertex AI configuration into this repo's Terraform.

### Acceptance Criteria

- [ ] Terraform GCP provider configured
- [ ] Service account for Vertex AI embeddings API
- [ ] IAM roles: `roles/aiplatform.user` on the project
- [ ] Service account key generated and stored in Doppler
- [ ] Project and location configurable via tfvars

---

## 8. CI/CD Workflow Updates

<!-- status: todo -->

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

<!-- status: todo -->

Execute the actual cutover from shared to dedicated infrastructure.

### Acceptance Criteria

- [ ] New cluster running and accessible
- [ ] Application deployed and healthy on new cluster
- [ ] DNS cutover with minimal downtime (< 5 minutes)
- [ ] SSL certificates issued successfully on new cluster
- [ ] All cron jobs running on new cluster
- [ ] Preview environments functional on new cluster
- [ ] Smoke tests pass post-migration
- [ ] Old cluster resources cleaned up (namespace, secrets, images)
- [ ] gv-infra Canon-specific Terraform marked as deprecated/removed

---

## Technical Design

### Directory Structure

```
infra/
  main.tf              # Provider config, backend, module calls
  variables.tf         # Input variables
  outputs.tf           # Cluster endpoint, registry URL, LB IP
  terraform.tfvars     # Production values (non-secret)
  versions.tf          # Provider version constraints
  modules/
    doks/              # DOKS cluster + node pools
    docr/              # Container registry
    dns/               # DNS zone + records
    bootstrap/         # cert-manager, nginx-ingress (Helm releases)
    auth0/             # Auth0 apps + settings
    gcp/               # GCP project, SA, IAM
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

### Phase 2: Supporting Services (Week 2)
- Sections 4-5: DNS module (don't apply yet), cluster bootstrap
- Sections 6-7: Auth0 and GCP Terraform (import existing)
- Validate: cert-manager issues certs, ingress routes traffic

### Phase 3: Cutover (Week 3)
- Section 8: Update CI/CD workflows
- Section 9: Execute migration
- Validate: full deployment pipeline works, zero-downtime DNS switch
