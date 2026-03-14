# Writing Specs

This guide covers how to write effective specs that Canon can parse, track, and verify. A well-structured spec becomes a living document that generates tickets, tracks implementation, and verifies itself against code.

## Start from the Template

Every repo with Canon includes a template at `docs/specs/_template.md`:

```markdown
---
title: "Feature Title"
status: draft
owner: your-name
team: team-name
ticket_project: null
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: []
---

# Feature Title

Brief overview of this feature.

## 1. Background

Why this feature exists and what problem it solves.

## 2. Requirements

<!-- canon:system:2 status:todo -->

### 2.1 Functional Requirements

- Requirement one
- Requirement two

### 2.2 Non-Functional Requirements

- Performance target
- Availability target

## 3. Design

<!-- canon:system:3 status:draft -->

Describe the technical approach.

### Acceptance Criteria

- [ ] Criterion one
- [ ] Criterion two
- [ ] Criterion three

## 4. Rollout Plan

<!-- canon:system:4 status:draft -->

How this will be deployed and validated.

## 5. Open Questions

- Question one?
- Question two?
```

Create a new spec with the Claude Code plugin:

```
/canon-new
```

Or copy the template manually:

```bash
cp docs/specs/_template.md docs/specs/my-feature.md
```

## Frontmatter

The YAML frontmatter is required. At minimum, include `title` and `status`:

```yaml
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
```

See the [Spec Format reference](/reference/spec-format) for all fields.

## Section Structure

Use numbered h2 headings for top-level sections and h3 for subsections:

```markdown
## 2. Stripe Migration
### 2.1 API Integration
### 2.2 Webhook Handler
## 3. Idempotency Layer
```

Each section can have a status comment. You don't need to add these manually — the agent manages them. But if you want to set an initial status:

```markdown
## 2. Stripe Migration
<!-- canon:system:2 status:in_progress -->
```

## Writing Good Acceptance Criteria

Acceptance criteria are the key to Canon's value. The agent evaluates code against ACs to determine realization status, so make them specific and verifiable.

### Do

```markdown
### Acceptance Criteria

- [ ] All checkout flows use Stripe PaymentIntents API
- [ ] Webhook signature verification using HMAC SHA-256
- [ ] Rate limit: max 10 emails per user per hour
- [ ] Idempotency keys stored in Redis with 24-hour TTL
```

Each criterion is:
- **Specific** — mentions concrete technology, API, or threshold
- **Verifiable** — an agent can check code for evidence
- **Independent** — can be evaluated in isolation

### Don't

```markdown
### Acceptance Criteria

- [ ] Payments work correctly
- [ ] Good error handling
- [ ] Performance is acceptable
- [ ] Users are happy
```

These are too vague for the agent to evaluate against code.

## Example: Complete Spec

Here's a complete example showing all the patterns:

```markdown
---
title: "Auth Migration to OAuth 2.0 + PKCE"
status: todo
owner: alex-kumar
team: identity
ticket_project: ID
created: 2026-01-10
updated: 2026-01-20
tags: [auth, security, q1-priority]
---

# Auth Migration to OAuth 2.0 + PKCE

Replace our custom session-based auth with OAuth 2.0 + PKCE flows,
enabling SSO and improving security posture.

## 1. Background

<!-- canon:system:1 status:done -->

Current auth is a custom session-cookie system built in 2020.
It doesn't support SSO, has no refresh token rotation, and
session fixation was patched twice last year. We need
standards-based auth before SOC2 audit in Q2.

## 2. OAuth Provider Integration

<!-- canon:system:2 status:todo -->
<!-- canon:ticket:linear:ID-301 -->

Integrate with Auth0 as the OAuth provider. Support Google
Workspace and Microsoft Entra ID as identity providers.

### Acceptance Criteria

- [ ] Auth0 tenant configured for production
- [ ] Google Workspace SSO working end-to-end
- [ ] Microsoft Entra ID SSO working end-to-end
- [ ] PKCE flow implemented for all client types

## 3. Token Management

<!-- canon:system:3 status:draft -->
<!-- canon:ticket:linear:ID-302 -->

Implement secure token storage and refresh flows.

Access tokens: 15-minute expiry, stored in memory only.
Refresh tokens: 7-day expiry, rotated on each use,
stored in httpOnly cookie.

### Acceptance Criteria

- [ ] Access tokens never persisted to storage
- [ ] Refresh token rotation on every use
- [ ] Revocation endpoint clears all active sessions
- [ ] Token introspection endpoint for service-to-service auth
```

## Tips

- **Start with Background** — Section 1 should explain *why*. The agent uses this to understand context.
- **One concern per section** — Each h2 section should cover one logical area. This maps cleanly to tickets.
- **Use subsections for detail** — h3 subsections let you break complex sections into trackable units.
- **Tag thoughtfully** — Tags are used for ticket routing and filtering. Use consistent tag names across specs.
- **Update the date** — Keep the `updated` frontmatter field current. The agent uses it for staleness detection.
- **Link related specs** — Reference other specs with relative links: `See [Auth Hardening](auth-hardening.md)`.
