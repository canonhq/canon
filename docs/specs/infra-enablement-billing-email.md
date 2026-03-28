---
title: "Infrastructure Enablement: Billing, Email & Auth0 M2M"
type: spec
status: in_progress
owner: ng
team: platform
review_status: draft
tags: [infra, billing, stripe, smtp, auth0, doppler, helm]
depends_on:
  - managed-cloud-pricing
  - oidc-migration
created: "2026-03-20"
updated: "2026-03-20"
---

# Infrastructure Enablement: Billing, Email & Auth0 M2M

## 1. Background

<!-- canon:system:1 status:done -->

Several features have been implemented in canon-private but lack the infrastructure
wiring to function in production:

- **Billing** (`src/canon/billing/`): Complete Stripe integration with checkout,
  portal, webhook handling, BYOK encryption, and seat-based pricing. The billing
  module reads 8 environment variables that are never set in production because
  no K8s secrets exist for them.

- **Email** (`src/canon/billing/email.py`): SMTP-based notifications for
  enterprise contact form. Reads 5 SMTP env vars that are never set.

- **Auth0 M2M** (`src/canon/auth/providers/auth0.py`): Organization membership
  queries via Management API require `AUTH0_M2M_CLIENT_ID` and
  `AUTH0_M2M_CLIENT_SECRET`. These exist as Terraform outputs in gv-infra but
  are not passed through the deploy pipeline.

The Stripe Terraform resources (products, prices, webhook endpoint, portal
config) already exist in `gv-infra/experiments/canon/stripe.tf` but their
outputs have not been propagated to Doppler or the deployment pipeline.

This spec covers the end-to-end wiring across both repos to make these
features operational in production.

## 2. Doppler Secrets

### 2.1 Stripe Secrets
<!-- canon:system:2.1 status:todo -->

Add the following to Doppler `canon/prd`:

| Secret | Source |
|--------|--------|
| `STRIPE_SECRET_KEY` | Stripe Dashboard > API keys |
| `STRIPE_PUBLISHABLE_KEY` | Stripe Dashboard > API keys |
| `STRIPE_WEBHOOK_SECRET` | `terraform output stripe_webhook_secret` |
| `STRIPE_STARTER_MONTHLY_PRICE_ID` | `terraform output stripe_starter_monthly_price_id` |
| `STRIPE_STARTER_ANNUAL_PRICE_ID` | `terraform output stripe_starter_annual_price_id` |
| `STRIPE_PRO_MONTHLY_PRICE_ID` | `terraform output stripe_pro_monthly_price_id` |
| `STRIPE_PRO_ANNUAL_PRICE_ID` | `terraform output stripe_pro_annual_price_id` |
| `BYOK_ENCRYPTION_KEY` | Generate: `python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"` |

#### Acceptance Criteria

- [ ] All 8 Stripe-related secrets exist in Doppler `canon/prd`
- [ ] `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY` sourced from Stripe Dashboard (not Terraform)
- [ ] Price IDs match those created by `stripe.tf` in gv-infra
- [ ] `BYOK_ENCRYPTION_KEY` is a fresh 256-bit base64-encoded key

### 2.2 SMTP Secrets
<!-- canon:system:2.2 status:todo -->

Add the following to Doppler `canon/prd`:

| Secret | Source |
|--------|--------|
| `SMTP_HOST` | Email provider (e.g. `smtp.gmail.com`, `email-smtp.us-east-1.amazonaws.com`) |
| `SMTP_PORT` | Typically `587` (STARTTLS) or `465` (SSL) |
| `SMTP_USER` | Provider credentials |
| `SMTP_PASSWORD` | Provider credentials |
| `SMTP_FROM` | e.g. `noreply@canonhq.co` |

#### Acceptance Criteria

- [ ] All 5 SMTP secrets exist in Doppler `canon/prd`
- [ ] SMTP credentials are for a dedicated sending service (not personal email)
- [ ] `SMTP_FROM` domain matches `canonhq.co` or a verified sender domain

### 2.3 Auth0 M2M Secrets
<!-- canon:system:2.3 status:in_progress -->

Add the following to Doppler `canon/prd`:

| Secret | Source |
|--------|--------|
| `AUTH0_M2M_CLIENT_ID` | `terraform output canon_auth0_m2m_client_id` |
| `AUTH0_M2M_CLIENT_SECRET` | `terraform output canon_auth0_m2m_client_secret` |

#### Acceptance Criteria

- [ ] Both M2M secrets exist in Doppler `canon/prd`
- [ ] Values match Terraform outputs from `gv-infra/experiments/canon/`

## 3. gv-infra: Terraform Apply
<!-- canon:system:3 status:todo -->

Ensure Stripe resources are applied and outputs are available.

#### Acceptance Criteria

- [ ] `terraform plan` in `experiments/canon/` shows no pending Stripe changes (already applied)
- [ ] OR `terraform apply` is run to create Stripe products, prices, webhook, and portal config
- [ ] All Terraform outputs are accessible: `terraform output stripe_webhook_secret`, price IDs, etc.

## 4. canon-private: Helm Chart Updates

### 4.1 Stripe Secret Template
<!-- canon:system:4.1 status:done -->

Add `secrets.stripe` to `values.yaml` and a corresponding K8s Secret template.

**values.yaml** addition:
```yaml
secrets:
  stripe:
    secretKey: ""
    publishableKey: ""
    webhookSecret: ""
    starterMonthlyPriceId: ""
    starterAnnualPriceId: ""
    proMonthlyPriceId: ""
    proAnnualPriceId: ""
    byokEncryptionKey: ""
    existingSecret: ""
```

**New template**: `chart/canon/templates/secret-stripe.yaml` — conditional on
`secrets.stripe.secretKey` being set AND `existingSecret` being empty. Maps
values to `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`,
`STRIPE_WEBHOOK_SECRET`, the 4 price ID env vars, and `BYOK_ENCRYPTION_KEY`.

#### Acceptance Criteria

- [x] `values.yaml` has `secrets.stripe` section with all 8 fields + `existingSecret`
- [x] `secret-stripe.yaml` template creates K8s Secret conditionally
- [x] Env var names match `src/canon/settings.py` exactly
- [x] `deployment.yaml` mounts the Stripe secret via `envFrom` (conditional)
- [x] `helm template` renders correctly with Stripe values set
- [x] `helm template` renders correctly with `existingSecret` set
- [x] `helm template` renders correctly with no Stripe values (secret omitted)

### 4.2 SMTP Secret Template
<!-- canon:system:4.2 status:done -->

Add `secrets.smtp` to `values.yaml` and a corresponding K8s Secret template.

**values.yaml** addition:
```yaml
secrets:
  smtp:
    host: ""
    port: "587"
    user: ""
    password: ""
    from: ""
    existingSecret: ""
```

**New template**: `chart/canon/templates/secret-smtp.yaml` — conditional on
`secrets.smtp.host` being set AND `existingSecret` being empty. Maps to
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`.

#### Acceptance Criteria

- [x] `values.yaml` has `secrets.smtp` section with all 5 fields + `existingSecret`
- [x] `secret-smtp.yaml` template creates K8s Secret conditionally
- [x] Env var names match `src/canon/settings.py` exactly
- [x] `deployment.yaml` mounts the SMTP secret via `envFrom` (conditional)
- [x] `helm template` renders correctly in all 3 modes (values, existingSecret, omitted)

### 4.3 Auth0 M2M in Existing Secret
<!-- canon:system:4.3 status:done -->

The `canon-auth0` K8s secret already exists but is missing M2M credentials.
No new Helm template needed — just update the deploy workflow to include them.

#### Acceptance Criteria

- [x] `AUTH0_M2M_CLIENT_ID` and `AUTH0_M2M_CLIENT_SECRET` are included in `canon-auth0` K8s secret
- [x] Auth0 values.yaml section documents M2M fields for non-existingSecret mode
- [x] Existing `secret.yaml` template includes M2M fields when set

### 4.4 Production Values
<!-- canon:system:4.4 status:done -->

Update `values-production.yaml` to reference new `existingSecret` names.

```yaml
secrets:
  stripe:
    existingSecret: canon-stripe
  smtp:
    existingSecret: canon-smtp
```

#### Acceptance Criteria

- [x] `values-production.yaml` references `canon-stripe` and `canon-smtp` existing secrets
- [x] Existing `canon-auth0` reference unchanged (M2M vars added to same secret)

## 5. canon-private: Deploy Workflow Updates

### 5.1 Stripe Secret in deploy.yml
<!-- canon:system:5.1 status:done -->

Add Stripe env vars to the "Ensure app secrets" step and create a `canon-stripe`
K8s secret.

#### Acceptance Criteria

- [x] `deploy.yml` fetches 8 Stripe secrets from Doppler
- [x] Creates `canon-stripe` K8s secret with all 8 env vars
- [x] Secret created with `--dry-run=client -o yaml | kubectl apply -f -` pattern

### 5.2 SMTP Secret in deploy.yml
<!-- canon:system:5.2 status:done -->

Add SMTP env vars and create a `canon-smtp` K8s secret.

#### Acceptance Criteria

- [x] `deploy.yml` fetches 5 SMTP secrets from Doppler
- [x] Creates `canon-smtp` K8s secret
- [x] Same creation pattern as other secrets

### 5.3 Auth0 M2M in deploy.yml
<!-- canon:system:5.3 status:done -->

Add M2M credentials to the existing `canon-auth0` K8s secret creation.

#### Acceptance Criteria

- [x] `deploy.yml` fetches `AUTH0_M2M_CLIENT_ID` and `AUTH0_M2M_CLIENT_SECRET` from Doppler
- [x] Both are added as `--from-literal` args to the `canon-auth0` secret creation
- [x] Existing Auth0 secret fields unchanged

### 5.4 Preview Workflow Updates
<!-- canon:system:5.4 status:done -->

Preview deployments should work without billing/SMTP (graceful degradation).
Verify that the preview workflow does NOT need Stripe/SMTP secrets since the
app gates on `stripe_enabled` and `smtp_enabled` properties.

#### Acceptance Criteria

- [x] Preview deployments continue to work without Stripe or SMTP secrets
- [x] `settings.stripe_enabled` returns `False` when secrets are absent
- [x] `settings.smtp_enabled` returns `False` when secrets are absent
- [x] No errors logged at startup when billing/SMTP is unconfigured

## 6. Helm Template Tests
<!-- canon:system:6 status:done -->

Add test cases to `tests/test_helm/test_template_rendering.py` for the new
secret templates and deployment envFrom conditions.

#### Acceptance Criteria

- [x] Test: Stripe secret renders with all values set
- [x] Test: Stripe secret skipped with `existingSecret` set
- [x] Test: Stripe secret skipped with no values
- [x] Test: SMTP secret renders with all values set
- [x] Test: SMTP secret skipped with `existingSecret` set
- [x] Test: SMTP secret skipped with no values
- [x] Test: Deployment envFrom includes Stripe secret ref when configured
- [x] Test: Deployment envFrom includes SMTP secret ref when configured
- [x] Test: Auth0 secret includes M2M fields when set
- [x] All existing Helm tests continue to pass

## 7. Rollout Plan

<!-- canon:system:7 status:draft -->

### Phase 1: Terraform & Doppler (gv-infra + Doppler UI)
1. Run `terraform apply` in `gv-infra/experiments/canon/` (if Stripe resources not yet applied)
2. Copy Terraform outputs to Doppler `canon/prd`
3. Add Stripe API keys from Stripe Dashboard to Doppler
4. Generate and store `BYOK_ENCRYPTION_KEY` in Doppler
5. Add Auth0 M2M credentials from Terraform outputs to Doppler
6. Add SMTP credentials to Doppler (choose provider: SES, SendGrid, etc.)

### Phase 2: Helm Chart + Deploy Workflow (canon-private PR)
1. Add Stripe and SMTP values/templates to Helm chart
2. Update Auth0 secret template for M2M fields
3. Update `values-production.yaml` with `existingSecret` refs
4. Update `deploy.yml` to create new K8s secrets
5. Add Helm template tests
6. Merge to main — deploy workflow creates secrets and deploys

### Phase 3: Verification
1. Confirm `stripe_enabled` returns `True` in production logs
2. Confirm `smtp_enabled` returns `True` in production logs
3. Test Stripe checkout flow end-to-end
4. Test enterprise contact form sends email
5. Confirm Auth0 org membership queries work (if orgs enabled)

### Success Criteria
- Stripe checkout creates a subscription and webhook fires successfully
- Enterprise contact form sends email notification
- Auth0 M2M org queries return membership data
- No regressions in existing functionality
- Preview deployments unaffected (graceful degradation)
