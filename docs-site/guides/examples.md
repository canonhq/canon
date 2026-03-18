# Example Specs

Real-world examples showing how to write Canon specs for different scenarios. These are included in the repo under `docs/examples/`.

## Auth Migration

A security-focused spec for migrating from custom session auth to OAuth 2.0 + PKCE. Demonstrates:

- Multi-section spec with background context
- Ticket links (`canon:ticket:linear:ID-301`)
- Status tracking per section (`status:done`, `status:todo`)
- Acceptance criteria as checklists
- Realization evidence (`canon:realized-in:PR#412`)

[View full spec →](https://github.com/canonhq/canon/blob/main/docs/examples/auth-migration.md)

## Payments Overhaul

A complex backend spec for rebuilding a payments system. Demonstrates:

- Nested subsections (e.g., 3.1 Key Generation under 3. Idempotency Layer)
- Cross-cutting concerns (observability, rollback)
- Multiple ticket system references
- Progressive realization as PRs merge

[View full spec →](https://github.com/canonhq/canon/blob/main/docs/examples/payments-overhaul.md)

## Writing Your Own

Create `docs/specs/my-feature.md`:

```markdown
---
title: My Feature
status: draft
owner: your-name
team: your-team
tags: [feature]
---

# My Feature

Brief description of what this feature does and why.

## 1. First Requirement

- [ ] Acceptance criteria as checklist items
- [ ] Each item should be independently verifiable
- [ ] Be specific about behavior, not implementation

## 2. Second Requirement

- [ ] More acceptance criteria
```

See the [Writing Specs Guide](./writing-specs) for best practices and the [Spec Format Reference](/reference/spec-format) for the full schema.
