# OpenSpec Framework

Canon adopts an [OpenSpec](https://github.com/Fission-AI/OpenSpec)-inspired structured artifact model. Specs are not freeform wiki pages — they're structured programs that the platform can parse, track, and verify.

## Artifact Types

Each feature or change can be expressed through complementary artifacts:

| Artifact | Purpose | File Pattern |
|----------|---------|-------------|
| **Proposal** | Why this change is needed, scope, impact | `docs/specs/<name>.md` (frontmatter + problem section) |
| **Spec Sections** | What the system must do (requirements + acceptance criteria) | Numbered sections within spec files |
| **Design** | How to implement it (architecture, trade-offs, migration) | `docs/decisions/*.md`, `docs/architecture.md` |
| **Tasks** | Implementation checklist with live ticket links | Acceptance criteria (`- [ ]`) + synced Jira/Linear/GitHub tickets |

## Spec File Structure

A spec file is a markdown document with YAML frontmatter and numbered sections:

```markdown
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

# Feature Name

Brief overview of this feature.

## 1. Background

Why this feature exists and what problem it solves.

## 2. Requirements

<!-- canon:system:2 status:todo -->
<!-- canon:ticket:jira:PROJ-100 -->

### Acceptance Criteria

- [ ] Criterion one
- [ ] Criterion two
- [x] Criterion three
```

## Frontmatter

The YAML frontmatter is the spec's metadata. Canon uses these fields for tracking, routing, and display:

| Field | Required | Description |
|-------|----------|-------------|
| `title` | Yes | Human-readable feature name |
| `status` | Yes | Overall spec status (`draft`, `todo`, `in_progress`, `done`, `blocked`, `deprecated`) |
| `owner` | No | Person responsible for the spec |
| `team` | No | Team that owns this feature |
| `ticket_project` | No | Jira project key, Linear team, or GitHub repo for ticket creation |
| `created` | No | Date the spec was first written |
| `updated` | No | Date of last modification |
| `tags` | No | List of tags for filtering and routing |

## Section Numbering

Sections use numbered headings (h2 for top-level, h3+ for subsections). This gives each section a stable identifier for ticket linking and status tracking:

```markdown
## 2. Stripe Migration          ← Section 2
### 2.1 API Integration         ← Section 2.1
### 2.2 Webhook Handler         ← Section 2.2
## 3. Idempotency Layer         ← Section 3
```

## Acceptance Criteria

Each section can have acceptance criteria expressed as markdown checklists:

```markdown
### Acceptance Criteria

- [ ] Email sent on new comment mentioning the user
- [x] Webhook signature verification on all incoming events
- [ ] Rate limit: max 10 emails per user per hour
```

Checked items (`[x]`) represent completed/verified criteria. The agent evaluates these against code in PRs to determine [realization status](/concepts/coverage).

## All-Markdown Knowledge Base

Canon indexes **every markdown file** in the repository, not just specs. All docs become part of the platform's knowledge and feed into agent analysis.

| Doc Type | Examples | How the Agent Uses It |
|----------|---------|----------------------|
| **Specs** | `docs/specs/*.md` | Primary intent — tracks sections, AC, tickets, realization |
| **ADRs** | `docs/decisions/*.md` | Context for "why was it built this way?" queries |
| **Architecture docs** | `docs/architecture.md` | System context for cross-cutting PR analysis |
| **READMEs** | `README.md`, `docs/*.md` | Onboarding context, API docs, usage guides |
| **Changelogs** | `CHANGELOG.md` | Release history for staleness detection |
| **Runbooks** | `docs/runbooks/*.md` | Operational context the agent can surface |
| **Contributing guides** | `CONTRIBUTING.md` | Process docs the agent keeps current |

Configure which files are indexed via `specs.doc_paths` in [CANON.yaml](/getting-started/configuration).

## Related

- **Guide**: [Writing Specs](/guides/writing-specs) — practical guide to authoring effective specs
- **Reference**: [Spec Format](/reference/spec-format) — formal syntax for frontmatter, sections, ACs, and comments
- **Reference**: [CANON.yaml](/reference/config) — full configuration schema
- **Concept**: [Living Specs](/concepts/living-specs) — how specs stay in sync with code through agents
- **Concept**: [Delta Tracking](/concepts/delta-tracking) — how status comments and ticket links work
