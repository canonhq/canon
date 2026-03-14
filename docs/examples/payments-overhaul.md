---
title: "Payments Overhaul"
status: in_progress
owner: sarah-chen
team: payments
ticket_project: PAY
created: 2025-11-15
updated: 2026-01-28
tags: [payments, infrastructure, q1-priority]
---

# Payments Overhaul

Migrate from legacy payment processor to Stripe, adding support for multi-currency transactions and improving reliability with an idempotency layer.

## 1. Background

<!-- canon:system:1 status:done -->

Our current payment stack was built in 2019 on a custom integration with PayCo. It processes ~$2M/month but has a 0.3% failure rate — 3x industry average. The PayCo contract expires March 2026.

Key problems:
- No multi-currency support (losing EU customers)
- Retry logic is ad-hoc, causing duplicate charges (~$15k/month in reversals)
- No webhook verification, making us vulnerable to replay attacks

## 2. Stripe Migration

<!-- canon:system:2 status:in_progress -->
<!-- canon:ticket:jira:PAY-142 -->

Core payment processing migration from PayCo to Stripe.

### 2.1 API Integration

<!-- canon:system:2.1 status:in_progress -->
<!-- canon:ticket:jira:PAY-143 -->

Replace PayCo SDK calls with Stripe SDK. Use PaymentIntents API for all transactions.

### Acceptance Criteria

- [ ] All checkout flows use Stripe PaymentIntents
- [x] Stripe webhook endpoint verified with signature checking
- [ ] Existing stored payment methods migrated to Stripe Customer objects
- [ ] Fallback to PayCo for in-flight transactions during migration window

### 2.2 Webhook Handler

<!-- canon:system:2.2 status:done -->
<!-- canon:ticket:jira:PAY-144 -->

Implement secure webhook processing for Stripe events.

### Acceptance Criteria

- [x] Webhook signature verification on all incoming events
- [x] Idempotent event processing (safe to replay)
- [x] Dead letter queue for failed webhook processing

## 3. Idempotency Layer

<!-- canon:system:3 status:blocked:PAY-200 -->
<!-- canon:ticket:jira:PAY-150 -->

Implement a request-level idempotency layer to prevent duplicate charges.

Every payment mutation must accept an `Idempotency-Key` header. The server stores the key + response for 24 hours. Repeated requests with the same key return the cached response without re-executing.

### Acceptance Criteria

- [ ] Idempotency key storage in Redis with 24hr TTL
- [ ] Atomic check-and-set to prevent race conditions
- [ ] Client SDK generates deterministic keys from (user_id, cart_id, amount)
- [ ] Dashboard shows duplicate request metrics

## 4. Multi-Currency Support

<!-- canon:system:4 status:todo -->
<!-- canon:ticket:jira:PAY-160 -->

Add support for EUR, GBP, and CAD transactions.

### 4.1 Currency Conversion

<!-- canon:system:4.1 status:todo -->

Real-time FX rates from Stripe with a 15-minute cache. All amounts stored in smallest currency unit (cents, pence, etc.).

### 4.2 Display Formatting

<!-- canon:system:4.2 status:draft -->

Locale-aware currency formatting in all customer-facing UIs.

### Acceptance Criteria

- [ ] Prices displayed in customer's local currency
- [ ] Conversion rates cached with 15-minute TTL
- [ ] All amounts stored as integers in smallest unit
- [ ] Admin dashboard shows revenue in USD equivalent

## 5. Monitoring & Alerts

<!-- canon:system:5 status:deprecated -->

_Moved to the observability team's spec. See `docs/specs/observability-v2.md`._

## 6. Rollout Plan

<!-- canon:system:6 status:draft -->

Phased rollout:
1. Shadow mode — process via both PayCo and Stripe, compare results
2. Canary — 5% of new transactions to Stripe
3. Ramp — 25% → 50% → 100% over 2 weeks
4. Sunset PayCo integration

### Acceptance Criteria

- [ ] Feature flag controls traffic split percentage
- [ ] Automated comparison reports during shadow mode
- [ ] Rollback to PayCo in < 5 minutes via flag flip
