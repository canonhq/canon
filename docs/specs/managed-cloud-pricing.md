---
title: "Managed Cloud Pricing & Stripe Billing"
status: in-progress
owner: ng
team: platform
ticket_project: null
created: 2026-03-14
updated: 2026-03-14
tags: [billing, stripe, pricing, enterprise]
---

# Managed Cloud Pricing & Stripe Billing

Implement a production billing stack for Canon's managed cloud offering with per-seat pricing, Stripe integration, BYOK pricing differentiation, AI operation metering, and enterprise contact flow.

## 1. Background

Canon currently offers a free, self-hosted deployment with a "Coming Soon" waitlist for managed cloud. The managed cloud uses per-seat pricing to align revenue growth with team adoption.

This spec covers the initial monetization of Canon's Tier 1 (Repo Agents) capabilities. Future tiers (Agent Mesh, Org Brain) will build on this billing infrastructure but are out of scope here.

**Key insight — BYOK as a pricing lever:** Canon's primary variable cost is Claude API usage for PR analysis and spec realization. Users who bring their own Anthropic API key eliminate this cost, enabling a lower price point that drives adoption while preserving margin on the all-inclusive tier.

### Current State

- Pricing section on landing page: Self-Hosted (free) + Managed Cloud (TBD / waitlist)
- Waitlist email capture via `POST /api/waitlist` → PostHog event
- Auth0 user management with no billing fields
- No payment processing, subscription logic, or plan enforcement

### Goals

1. Launch managed cloud with per-seat pricing and Stripe checkout
2. Differentiate BYOK vs all-inclusive pricing to reflect cost structure
3. Enable self-service billing management (upgrades, downgrades, invoices)
4. Provide enterprise contact path for custom deals
5. Build billing infrastructure that supports future tiers
6. 14-day Pro trial to maximize top-of-funnel conversion

## 2. Pricing Model

<!-- canon:system:pricing-model status:in-progress -->

### 2.1 Tier Definitions

| | Self-Hosted | Starter | Pro | Enterprise |
|---|---|---|---|---|
| **Price** | Free forever | $9/user/mo | $19/user/mo | Custom |
| **Trial** | N/A | 14-day free (full Pro features) | 14-day free | POC engagement |
| **Repos** | Unlimited | Up to 10 | Unlimited | Unlimited |
| **AI Compute** | Your infra | BYOK (you pay Anthropic) | 500 ops/user/mo included | Unlimited included |
| **AI Overage** | N/A | N/A (BYOK) | $0.08/op | Negotiated |
| **PR Analysis** | Yes | Yes | Yes | Yes |
| **Spec Indexing** | Yes | Yes | Yes | Yes |
| **Ticket Sync** | 1 system | 1 system | All systems | All + custom |
| **Auto Doc PRs** | Yes | Yes | Yes | Yes |
| **Stale Detection** | Yes | Yes | Yes | Yes |
| **Slack Q&A** | — | — | Yes | Yes |
| **SSO / SAML** | — | — | — | Yes |
| **Audit Logs** | — | — | — | Yes |
| **Support** | Community | Email | Priority | Dedicated |

**Minimum 3 seats** on all paid plans. Signals Canon is a team product.

### 2.2 Annual Discount (20%)

- Starter: $86/user/yr ($7.17/mo effective)
- Pro: $182/user/yr ($15.17/mo effective)

### 2.3 AI Operations

Each of these counts as 1 operation:
- PR analysis (reviewing a pull request against specs)
- Doc update generation (creating a PR to update stale docs)
- Spec coverage scan (checking implementation against acceptance criteria)
- Slack Q&A response (answering a question from indexed docs)
- Spec generation assist (AI-powered spec writing in web editor)

Spec parsing, ticket sync, and CLI/MCP queries do NOT count as ops.

### 2.4 Seat Counting

A "seat" = any user who interacts with Canon in a billing period:
- Views the Canon dashboard or billing page
- Triggers a PR analysis or spec coverage scan
- Uses the CLI or MCP tools
- Receives a Canon PR comment (passive interaction counts)
- Uses Slack Q&A

Billing mechanics:
- Monthly: billed for max active seats in the billing period
- Annual: billed for committed seat count, true-up quarterly if exceeded
- Seat count visible in billing dashboard with per-user activity breakdown

### 2.5 BYOK (Bring Your Own Key)

Users on the Starter tier provide their own Anthropic API key. Canon stores the key encrypted at rest and uses it for all Claude API calls associated with the user's repos. This means:

- Canon pays zero AI compute cost for BYOK users
- User has full visibility into their Anthropic usage/billing
- User can set their own rate limits and model preferences
- If the user's key is revoked or runs out of credits, agent features degrade gracefully

### 2.6 Trial Mechanics

- 14-day Pro trial for all new users
- Full Pro features during trial (AI included, unlimited repos, all integrations)
- No credit card required to start trial
- Auto-downgrade to Starter (or free) at trial end

### Acceptance Criteria

- [x] Pricing page displays all four tiers with accurate feature comparison
- [x] BYOK and all-inclusive pricing is clearly differentiated
- [x] Per-seat pricing with minimum 3 seats enforced
- [x] Annual billing option applies 20% discount
- [x] Monthly/annual toggle on pricing page
- [x] AI operations defined and metered for Pro tier
- [x] 14-day Pro trial available without credit card

## 3. Stripe Integration

<!-- canon:system:stripe-integration status:in-progress -->

### 3.1 Stripe Setup

Create Stripe Products and Prices that map to the per-seat pricing model:

```
Products:
  canon_starter       → "Canon Starter (BYOK)"
  canon_pro           → "Canon Pro"

Prices (per product):
  starter_monthly     → $9/seat/mo (per-unit)
  starter_annual      → $86/seat/yr (per-unit)
  pro_monthly         → $19/seat/mo (per-unit)
  pro_annual          → $182/seat/yr (per-unit)
```

### 3.2 Checkout Flow

1. User clicks "Start Free Trial" or "Get Started" on a plan
2. `POST /api/checkout` creates a Stripe Checkout Session with seat quantity
3. Stripe Checkout handles payment details, tax calculation, and 3D Secure
4. New users get 14-day trial (no payment required during trial)
5. On success, webhook confirms subscription creation

### 3.3 Billing Portal

Stripe's Customer Portal for self-service:

- View/download invoices
- Update payment method
- Switch between monthly/annual billing
- Cancel subscription
- Adjust seat count

### 3.4 Webhook Handler

`POST /api/webhooks/stripe` handles these events:

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Create subscription with seat count from metadata |
| `customer.subscription.updated` | Handle plan/seat changes, update entitlements |
| `customer.subscription.deleted` | Revoke managed cloud access, notify user |
| `invoice.payment_failed` | Notify user, mark subscription past_due |

### Acceptance Criteria

- [x] Stripe Prices support per-seat quantity
- [x] Checkout flow passes seat_count in metadata
- [x] Trial period (14 days) enabled for new customers
- [x] Billing Portal allows subscription management
- [x] Webhook handler processes all subscription lifecycle events
- [x] Webhook signature verification prevents spoofed events

## 4. BYOK Key Management

<!-- canon:system:byok status:in-progress -->

(Same as before — encryption, validation, routing, graceful degradation.)

### Acceptance Criteria

- [x] Anthropic API key can be submitted and is encrypted at rest (AES-256-GCM)
- [x] Key validation endpoint verifies key works before storing
- [x] Key is never returned in full via API (last 4 chars only)
- [ ] Agent uses BYOK key for Starter plans, Canon key for Pro/Enterprise
- [ ] Graceful degradation when BYOK key fails

## 5. Enterprise Contact Flow

<!-- canon:system:enterprise-contact status:in-progress -->

### Acceptance Criteria

- [x] Enterprise contact form collects name, email, company, team size
- [ ] Form submission sends email to sales@canonhq.co
- [x] PostHog event tracks enterprise contact (no PII in event)
- [x] Honeypot field prevents basic spam bots
- [ ] User sees confirmation message after submission

## 6. Backend Architecture

<!-- canon:system:backend status:in-progress -->

### 6.1 Modules

```
src/canon/
  billing/
    __init__.py
    stripe_client.py     # Stripe API wrapper (Checkout, Portal, Webhooks)
    models.py            # Pydantic: Subscription, Plan, AiOpUsage, seat/ops constants
    service.py           # Business logic: subscriptions, seats, AI ops, BYOK, trials
    encryption.py        # AES-256-GCM encrypt/decrypt for BYOK keys
    routes.py            # FastAPI routes: checkout, billing, seats, AI ops, BYOK, enterprise
```

### 6.2 Database Tables

```sql
subscriptions           -- Org subscriptions with seat_count, trial dates
seat_activity           -- Per-user activity tracking for seat counting
ai_op_usage             -- Individual AI operation records
ai_op_monthly_summary   -- Monthly aggregated usage (for billing)
billing_events          -- Stripe webhook audit log
anthropic_keys          -- Encrypted BYOK keys
enterprise_contacts     -- Sales inquiry leads
```

### 6.3 API Routes

Org-scoped routes use the `/app/{org}/api/` prefix (matching ticket, profile, and API key routes). The Stripe webhook stays at `/api/` since it's called by Stripe, not the frontend.

```
POST   /app/{org}/api/checkout                  # Create Stripe Checkout Session (per-seat)
POST   /app/{org}/api/billing/portal            # Create Stripe Billing Portal session
GET    /app/{org}/api/billing/subscription      # Get current subscription details
GET    /app/{org}/api/billing/seats             # Get seat count and active users
GET    /app/{org}/api/billing/ai-ops            # Get AI operation usage for current period
POST   /app/{org}/api/billing/start-trial       # Start 14-day Pro trial (no card required)
POST   /app/{org}/api/settings/anthropic-key    # Submit/validate BYOK key
GET    /app/{org}/api/settings/anthropic-key    # Get BYOK key status
DELETE /app/{org}/api/settings/anthropic-key    # Remove BYOK key
POST   /app/{org}/api/contact/enterprise        # Enterprise contact form
POST   /api/webhooks/stripe                     # Stripe webhook handler (separate router)
```

### Acceptance Criteria

- [x] Billing module is organized with per-seat models
- [x] Database schema includes seat_activity and ai_op_usage tables
- [x] All API routes are implemented
- [x] Settings loaded from environment variables
- [x] Comprehensive test suite (140 tests passing)

## 7. Known Deferrals

Items identified in PR review that are tracked for follow-up:

- **BYOK rate limiting**: `POST /settings/anthropic-key` makes a real Anthropic API call per request. Add per-org rate limit (e.g. 5 attempts/hour) to prevent abuse.
- **Stripe SDK global state**: `stripe.api_key` is set as a module-level global in `stripe_client.py`. Use the instance-level `stripe.StripeClient(api_key)` API to avoid test isolation issues.
- **Enterprise email notifications**: Contact form saves to DB and tracks in PostHog but does not send email to `sales@canonhq.co`. Needs an email service (SES, Resend, etc.).
- **BYOK graceful degradation**: When a stored BYOK key is revoked or exhausted, agent features should degrade gracefully rather than hard-fail. Partially implemented via `mark_anthropic_key_invalid` but no automatic retry/fallback logic.

## 8. Open Questions

- Should BYOK remain available on Pro as a cost-saving option?
- What's the right ops/user/mo number for Pro? (500 is a starting guess — needs validation against actual Anthropic API costs per operation)
- Grace period duration for failed payments?
