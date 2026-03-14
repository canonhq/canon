# Spec Format

Spec files are markdown documents with YAML frontmatter and structured sections. This page is the canonical reference for the format.

## File Location

Specs live in `docs/specs/` by default. Configure custom paths via `specs.doc_paths` in [CANON.yaml](./config).

## Frontmatter

Every spec begins with YAML frontmatter between `---` delimiters:

```yaml
---
title: "Feature Name"
status: draft
owner: your-name
team: team-name
ticket_project: PROJ
created: 2026-02-01
updated: 2026-02-26
tags: [feature, mvp]
---
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | **Yes** | Human-readable feature name |
| `status` | string | **Yes** | Overall spec status |
| `owner` | string | No | Person responsible for the spec |
| `team` | string | No | Team that owns this feature |
| `ticket_project` | string | No | Jira project key, Linear team, or GitHub repo |
| `created` | date | No | Date first written (YYYY-MM-DD) |
| `updated` | date | No | Date of last modification |
| `tags` | string[] | No | Tags for filtering and routing |

### Status Values

| Status | Meaning |
|--------|---------|
| `draft` | Initial state — requirements not yet finalized |
| `todo` | Ready for implementation |
| `in_progress` | Work has started on at least one section |
| `done` | All sections complete |
| `blocked` | Waiting on a dependency |
| `deprecated` | No longer relevant |

## Sections

Sections use numbered h2 headings. Subsections use h3+:

```markdown
## 1. Background
## 2. Requirements
### 2.1 Functional Requirements
### 2.2 Non-Functional Requirements
## 3. Design
## 4. Rollout Plan
```

### Section Numbering

- Use integers for top-level sections: `## 1.`, `## 2.`, etc.
- Use decimal notation for subsections: `### 2.1`, `### 2.2`
- Numbering is used as the stable section identifier for ticket linking

## Status Comments

Each section can have a hidden status comment immediately after the heading:

```markdown
## 2. Requirements
<!-- canon:system:2 status:todo -->
```

### Syntax

```
<!-- canon:system:<section-id> status:<status> -->
```

- `section-id`: Matches the section number or a custom slug
- `status`: One of `draft`, `todo`, `in_progress`, `done`, `blocked`, `deprecated`

Blocked status can include a dependency:

```markdown
<!-- canon:system:3 status:blocked:PAY-200 -->
```

## Ticket Links

Link a section to an external ticket:

```markdown
<!-- canon:ticket:<system>:<ticket-id> -->
```

Examples:

```markdown
<!-- canon:ticket:jira:PAY-142 -->
<!-- canon:ticket:linear:ID-301 -->
<!-- canon:ticket:github:42 -->
```

## Acceptance Criteria

Acceptance criteria use markdown checkbox syntax under a `### Acceptance Criteria` heading:

```markdown
### Acceptance Criteria

- [ ] Email sent on new comment mentioning the user
- [x] Webhook signature verification on all incoming events
- [ ] Rate limit: max 10 emails per user per hour
```

- `[ ]` — Not yet realized
- `[x]` — Realized (verified against code)

ACs can appear at any section level. The agent evaluates ACs in the context of their parent section.

## Realization Evidence

When the agent verifies that code implements an AC, it inserts a realization comment:

```markdown
<!-- canon:realized-in:PR#412 src/payments/keys.ts:42-60 -->
```

### Syntax

```
<!-- canon:realized-in:PR#<number> <file>:<start>-<end> -->
```

- `PR#<number>`: The pull request that introduced the implementation
- `<file>:<start>-<end>`: File path and line range with the evidence

## Complete Example

```markdown
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

Migrate from legacy payment processor to Stripe.

## 1. Background

<!-- canon:system:1 status:done -->

Our current payment stack has a 0.3% failure rate.

## 2. Stripe Migration

<!-- canon:system:2 status:in_progress -->
<!-- canon:ticket:jira:PAY-142 -->

### 2.1 API Integration

<!-- canon:system:2.1 status:in_progress -->
<!-- canon:ticket:jira:PAY-143 -->

### Acceptance Criteria

- [ ] All checkout flows use Stripe PaymentIntents
- [x] Stripe webhook endpoint verified with signature checking
<!-- canon:realized-in:PR#389 src/webhooks/stripe.py:15-42 -->
- [ ] Existing payment methods migrated to Stripe

### 2.2 Webhook Handler

<!-- canon:system:2.2 status:done -->
<!-- canon:ticket:jira:PAY-144 -->
<!-- canon:realized-in:PR#389 src/webhooks/stripe.py -->

### Acceptance Criteria

- [x] Webhook signature verification on all incoming events
- [x] Idempotent event processing
- [x] Dead letter queue for failed processing
```
