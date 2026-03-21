---
title: "Enterprise Adoption Enablement"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-03-20
updated: 2026-03-20
tags: [enterprise, adoption, jira, hierarchy, review, metrics]
---

# Enterprise Adoption Enablement

Feature-level enhancements that make Canon viable for large engineering organizations (100+ engineers, complex Jira workflows, multi-repo initiatives, non-technical stakeholders). Informed by an internal enterprise adoption proposal that revealed Canon's biggest gaps for organizations with existing SDLC infrastructure.

## 1. Background

<!-- canon:system:1 status:done -->

Canon today is optimized for spec-driven teams that adopt the full workflow: write specs in repos, sync sections to tickets, track coverage. This works well for teams that already buy into spec-driven development.

Enterprise adoption follows a different pattern. Organizations want to:
1. Start with **Jira hygiene automation** (PR-ticket linking, status transitions) before any spec authoring
2. Introduce specs **progressively by role** — PMs first (initiative specs), then EMs (epic specs), then engineers (implementation)
3. Track **initiatives across repos** — a single feature may span 5-50 repositories
4. Enforce **governance and compliance** — specs must be reviewed before tickets are created, certain Jira fields are mandatory
5. Export **metrics to existing engineering analytics** platforms (Jellyfish, LinearB, Swarmia)

Canon's current model assumes specs exist before ticket sync begins. The most impactful change is decoupling git lifecycle events from spec-driven sync, allowing Canon to deliver value at "Phase 0" — before any spec files exist.

**Related specs:**
- `ticket-mapping-model.md` (done) — configurable ticket field/status mapping
- `spec-review-workflow.md` (in_progress) — review lifecycle data model
- `slack-integration.md` (draft) — notification delivery

## 2. Git Lifecycle Sync

<!-- canon:system:2 status:todo -->

A new sync mode where git events (commit, PR open, PR merge, PR close) drive ticket status transitions, independent of spec content. This is the "Phase 0" capability that enterprises need before adopting specs.

### 2.1 Branch Name → Ticket ID Extraction

Canon's GitHub App already receives push and pull_request events. Add configurable branch name parsing to extract ticket IDs:

```yaml
# CANON.yaml
git_lifecycle:
  enabled: true
  branch_pattern: "^(?:feature/|bugfix/|hotfix/)?(?P<ticket_id>[A-Z]+-\\d+)[/-]"
  # Extracts "PROJ-1234" from "feature/PROJ-1234/add-export" or "PROJ-1234-fix-bug"
```

The `branch_pattern` is a regex with a named group `ticket_id`. Default pattern matches common conventions: `PROJ-123/description`, `feature/PROJ-123-description`, `PROJ-123-description`.

### 2.2 Event → Status Transition Map

Configurable mapping from git events to ticket system transitions:

```yaml
git_lifecycle:
  status_transitions:
    first_commit: "In Progress"        # First push to a branch with ticket ID
    pr_opened: "Needs Code Review"     # PR opened against default branch
    pr_approved: "Ready to Deploy"     # PR receives approving review
    pr_merged: "Done"                  # PR merged to default branch
    pr_closed: "In Progress"           # PR closed without merge (revert)
  skip_transitions: ["In QA", "In Staging"]  # Never auto-transition out of these states
```

The `skip_transitions` list prevents Canon from overriding QA gates, compliance stages, or other manually-managed states. If a ticket is in a skip state, Canon logs the event but does not transition.

### 2.3 PR → Ticket Linking

When a PR is opened and a ticket ID is extracted from the branch name:
- Add the PR URL as a remote link on the ticket (Jira REST API `remotelink` endpoint, Linear `attachmentCreate` mutation)
- Add the ticket URL to the PR body if not already present (GitHub API)
- Track the link in `sync_state` for deduplication

### 2.4 Interaction with Spec-Driven Sync

Git lifecycle sync and spec-driven sync are complementary:
- Git lifecycle sync manages ticket **status** based on code lifecycle
- Spec-driven sync manages ticket **creation, content, and coverage** based on spec sections
- When both are active, spec-driven status wins for spec-linked tickets (spec is the source of truth for what's "done")
- Git lifecycle sync handles tickets that have no linked spec (pure code tasks)

Priority resolution: if a ticket is linked to both a spec section AND a branch, spec-driven sync takes precedence for status. Git lifecycle sync still creates the PR link.

### Acceptance Criteria

- [ ] Branch name parsing extracts ticket IDs from configurable regex patterns
- [ ] Default branch pattern matches `PROJ-123/desc`, `feature/PROJ-123-desc`, `PROJ-123-desc`
- [ ] First push to a branch with ticket ID triggers configurable status transition
- [ ] PR opened triggers configurable status transition on linked ticket
- [ ] PR merged triggers configurable status transition on linked ticket
- [ ] PR closed without merge triggers configurable revert transition
- [ ] PR approval triggers configurable status transition
- [ ] Skip transitions list prevents Canon from overriding protected states
- [ ] PR URL added as remote link on ticket when PR is opened
- [ ] Ticket URL added to PR body when ticket ID is extracted
- [ ] Git lifecycle sync and spec-driven sync coexist without conflicts
- [ ] Spec-driven sync takes precedence for status on spec-linked tickets
- [ ] Git lifecycle sync works with Jira, Linear, and GitHub Issues adapters
- [ ] Git lifecycle sync works without any spec files in the repo (pure Phase 0)

## 3. Hierarchical Spec Relationships

<!-- canon:system:3 status:todo -->

Support parent-child relationships between specs, enabling the initiative → epic → ticket decomposition pattern used by large organizations.

### 3.1 Parent Field in Frontmatter

Add an optional `parent` field to spec frontmatter:

```yaml
---
title: "Patient Export Feature"
status: in_progress
type: spec
parent: "./initiative-q2-platform.md"  # Relative path to parent spec
---
```

The `parent` field is a relative path from the spec file to its parent. The parser resolves and validates this reference. Circular references are rejected.

### 3.2 Spec Type Progression

Canon already supports `type: spec | proposal | design | adr`. Enhance this with a natural hierarchy:

| Type | Purpose | Typical Author | Children |
|------|---------|---------------|----------|
| `proposal` | Problem statement, goals, scope (the "why") | PM | `spec` |
| `spec` | Requirements with acceptance criteria (the "what") | PM / EM | `design` |
| `design` | Technical approach, architecture (the "how") | EM / Tech Lead | — |
| `adr` | Decision record (standalone) | Anyone | — |

Enforcement is optional — a spec can have any type as its parent. The progression is a convention, not a constraint.

### 3.3 Coverage Rollup

Coverage aggregation through the hierarchy:
- A parent spec's coverage includes its own ACs plus aggregated coverage from all children
- The `get_coverage` MCP tool accepts an optional `include_children: true` parameter
- The coverage dashboard shows both direct and rolled-up coverage

### 3.4 Tree Navigation in MCP

New MCP tool capabilities:
- `get_spec` returns a `children` list (paths of specs that reference this spec as parent)
- `get_spec` returns resolved `parent` path if set
- `list_specs` accepts `root_only: true` to show only top-level specs (no parent)

### Acceptance Criteria

- [ ] `parent` field accepted in spec frontmatter as relative path
- [ ] Parser resolves and validates parent references (file must exist)
- [ ] Circular parent references are detected and rejected with clear error
- [ ] `get_spec` MCP tool returns `parent` and `children` fields
- [ ] `list_specs` supports `root_only` filter for top-level specs only
- [ ] Coverage rollup includes children's ACs when `include_children: true`
- [ ] `canon status` CLI shows hierarchy with indentation for child specs
- [ ] Spec types (`proposal`, `spec`, `design`, `adr`) are documented as a suggested hierarchy

## 4. Spec Review Enforcement

<!-- canon:system:4 status:todo -->

Make the existing `require_review` config flag and `review_status` frontmatter field operational. Currently these are data model placeholders with no runtime enforcement.

### 4.1 Gated Ticket Creation

When `specs.require_review: true` in CANON.yaml:
- The sync engine skips ticket creation for specs with `review_status` other than `approved`
- Specs with `review_status: draft` or `review_status: in_review` are visible in the dashboard but do not generate tickets
- When a spec transitions to `approved`, the next sync run creates tickets for all eligible sections

### 4.2 Review Status Transitions

Enforce valid transitions:
- `draft` → `in_review` (author submits for review)
- `in_review` → `approved` (reviewer approves)
- `in_review` → `draft` (reviewer requests changes)
- `approved` → `draft` (re-opened for revision)

Invalid transitions (e.g., `draft` → `approved`) are rejected by the parser with a warning. Transitions are tracked in `agent_events`.

### 4.3 Configurable Reviewer Requirements

Optional configuration for mandatory review:

```yaml
specs:
  require_review: true
  review:
    min_approvals: 1
    required_roles: []  # Optional: ["pm", "engineering_lead"]
```

When `required_roles` is set, the review workflow checks that approvers have the specified roles (mapped from GitHub team membership or CANON.yaml role definitions). This is optional — most teams will use simple approval counts.

### Acceptance Criteria

- [ ] Sync engine skips ticket creation for specs without `review_status: approved` when `require_review: true`
- [ ] Specs transitioning to `approved` trigger ticket creation on next sync
- [ ] Invalid review status transitions are rejected with clear error message
- [ ] Review status transitions logged in `agent_events`
- [ ] `min_approvals` configuration respected when set
- [ ] `required_roles` configuration respected when set (optional feature)
- [ ] `require_review: false` (default for OSS) bypasses all review gating
- [ ] Dashboard shows review status for each spec when review is enabled

## 5. Cross-Repo Initiative Tracking

<!-- canon:system:5 status:todo -->

Enable tracking of initiatives that span multiple repositories. A spec in one repo can reference implementation across many repos, with aggregated coverage.

### 5.1 Cross-Repo References

Extend the `parent` field to support cross-repo references:

```yaml
parent: "org/repo-name:docs/specs/initiative.md"
```

Format: `{org}/{repo}:{path}` — Canon resolves this via the GitHub API using the installation's access.

### 5.2 Initiative Coverage Aggregation

The `get_coverage` MCP tool and coverage snapshot CronJob support org-level aggregation:
- Query coverage by initiative (root spec path) across all repos in the org
- Coverage dashboard shows per-repo breakdown within an initiative
- Trend data aggregated at initiative level

### 5.3 Org-Level Initiative Dashboard

The web dashboard and MCP tool surface initiative-level views:
- List all initiatives (root-level proposal/spec specs) across the org
- Show coverage rollup per initiative including all child specs in any repo
- Filter by team, status, or tag

### Acceptance Criteria

- [ ] Cross-repo parent references resolve via GitHub API
- [ ] Coverage aggregation works across repos for a single initiative
- [ ] `get_coverage` accepts `initiative` parameter for cross-repo rollup
- [ ] Coverage snapshots include cross-repo initiative data
- [ ] Web dashboard shows initiative-level view across repos
- [ ] Broken cross-repo references logged as warnings (not errors — repo may be inaccessible)

## 6. Non-Technical Authoring Enhancements

<!-- canon:system:6 status:todo -->

Enhance the existing web editor to support enterprise adoption patterns where PMs and non-technical stakeholders author specs without CLI/git expertise.

### 6.1 Spec Templates in Web Editor

Pre-populated templates selectable when creating a new spec:
- **Initiative Proposal** — problem statement, goals, success metrics, scope
- **Feature Spec** — requirements organized by feature area with AC scaffolding
- **Technical Design** — architecture decisions, API contracts, data model changes
- **ADR** — context, decision, consequences

Templates match Canon's spec types and guide authors through structured fields.

### 6.2 Guided AC Authoring

When editing acceptance criteria, the editor offers:
- Autocomplete suggestions based on the section context
- Validation that ACs are specific and testable (heuristic: contains a verb, is not vague)
- "Generate ACs" button that uses Claude to suggest acceptance criteria from the section description

### 6.3 Structured Import

API endpoint for importing specs from external sources:

```
POST /api/{org}/specs/import
Content-Type: application/json

{
  "repo": "org/repo-name",
  "title": "Feature Name",
  "type": "spec",
  "content": "# Feature Name\n\n## Requirements\n...",
  "create_pr": true
}
```

This enables external tools (Google Docs add-ons, Notion integrations, Confluence exports) to push structured content into Canon's spec workflow. When `create_pr: true`, Canon creates a branch and PR for review rather than committing directly.

### Acceptance Criteria

- [ ] Web editor offers template selection when creating new specs
- [ ] Templates exist for proposal, spec, design, and ADR types
- [ ] Templates pre-populate frontmatter and section structure
- [ ] AC authoring includes "Generate ACs" Claude-assisted suggestion
- [ ] Import API endpoint accepts structured content and creates spec files
- [ ] Import API supports `create_pr: true` for review workflow
- [ ] Import API validates content structure before creating files

## 7. Engineering Metrics Export

<!-- canon:system:7 status:todo -->

Export Canon's operational data to external engineering analytics platforms. Enterprises use tools like Jellyfish, LinearB, and Swarmia for cycle time, investment tracking, and team health — Canon should feed into these systems.

### 7.1 Event Webhook

Configurable outbound webhook that emits structured events:

```yaml
# CANON.yaml
webhooks:
  metrics:
    url: "https://analytics.company.com/canon-events"
    secret: "${METRICS_WEBHOOK_SECRET}"  # HMAC signing
    events:
      - spec_created
      - spec_approved
      - ticket_created
      - ticket_completed
      - realization_confirmed
      - coverage_snapshot
```

Events are signed with HMAC-SHA256 and include a retry queue (3 attempts with exponential backoff).

### 7.2 Metrics API

REST endpoint exposing Canon metrics for pull-based integrations:

```
GET /api/{org}/metrics/cycle-time?from=2026-01-01&to=2026-03-20
GET /api/{org}/metrics/coverage?repo=org/repo-name
GET /api/{org}/metrics/spec-freshness?stale_threshold=30d
```

Returns:
- **Cycle time**: spec created → ticket created → first PR → PR merged → ticket closed
- **Coverage**: current coverage by repo, team, initiative
- **Spec freshness**: time since last spec update vs. last code change per spec
- **Adoption**: percentage of tickets with linked specs, PRs with linked tickets

### 7.3 Coverage Snapshot Export

The existing daily coverage snapshot CronJob can optionally push snapshots to the metrics webhook, enabling external dashboards to track coverage trends without polling.

### Acceptance Criteria

- [ ] Outbound webhook delivers structured events to configurable URL
- [ ] Webhook events signed with HMAC-SHA256
- [ ] Webhook includes retry queue with exponential backoff (3 attempts)
- [ ] Metrics API returns cycle time data (spec → ticket → PR → merge)
- [ ] Metrics API returns coverage data filterable by repo and team
- [ ] Metrics API returns spec freshness data
- [ ] Metrics API returns adoption percentages (tickets with specs, PRs with tickets)
- [ ] Coverage snapshot CronJob optionally pushes to metrics webhook
- [ ] Metrics API endpoints require authentication (API key or session)

## 8. Compliance Workflow Gates

<!-- canon:system:8 status:todo -->

Configurable gates that enforce organizational compliance requirements before ticket status transitions. Enterprises operating under SOC-2, HIPAA, or similar frameworks need certain workflow stages to be manually controlled.

### 8.1 Protected Ticket States

Extend `git_lifecycle.skip_transitions` to a more general concept:

```yaml
compliance:
  protected_states: ["In QA", "In Staging", "Security Review"]
  required_fields:
    - field: "Work Type"
      values: ["Fundamentals", "Support", "DevProd", "Product", "Platform", "Ops"]
    - field: "Subteam"
    - field: "Program"
```

Canon never auto-transitions a ticket out of a protected state. This ensures QA, security review, and deployment gates remain under human control.

### 8.2 Required Field Validation

Before creating or updating a ticket, Canon validates that all `required_fields` are populated. If a required field value cannot be determined from spec metadata or CANON.yaml defaults, Canon:
1. Skips ticket creation with a warning log
2. Reports the missing field in the dashboard
3. Does not silently create a ticket that will be rejected by Jira's own field validation

### 8.3 Field Defaults from Spec Metadata

Map spec metadata to required ticket fields:

```yaml
compliance:
  field_defaults:
    "Work Type": "Product"              # Static default
    "Subteam": "${spec.team}"           # From spec frontmatter team field
    "Program": "${spec.tags[0]}"        # From spec tags
```

This reduces manual data entry while ensuring compliance fields are always populated.

### Acceptance Criteria

- [ ] Protected states prevent Canon from auto-transitioning tickets
- [ ] Required fields validated before ticket creation
- [ ] Missing required fields logged as warnings with spec/section context
- [ ] Dashboard shows tickets blocked by missing required fields
- [ ] Field defaults populate from spec metadata using template syntax
- [ ] Static field defaults supported in CANON.yaml
- [ ] Jira, Linear, and GitHub Issues adapters all respect compliance config
- [ ] Compliance config is optional — absent config means no enforcement

## 9. Plugin Marketplace Distribution

<!-- canon:system:9 status:todo -->

Enhance the existing Canon Claude Code plugin to support organization-wide distribution through plugin marketplaces (Anthropic plugin registry, org-internal marketplaces).

### 9.1 Org-Specific Skill Packaging

Allow organizations to extend the Canon plugin with custom skills:

```
plugin/
  .claude-plugin/
    plugin.json          # Base Canon plugin manifest
  skills/
    canon-task/          # Built-in Canon skills
    canon-verify/
  org-skills/            # Org-specific extensions (gitignored in OSS)
    sprint-plan/
    jira-hygiene/
```

The plugin manifest supports an `extensions` field pointing to org-specific skill directories. Organizations fork the Canon plugin and add their own skills alongside Canon's built-in ones.

### 9.2 Marketplace Metadata

Enhance `plugin.json` with metadata for marketplace distribution:
- Version, description, author, license
- Required Canon server version (minimum API compatibility)
- Required MCP tools (declares dependencies)
- Configuration schema (what CANON.yaml fields the plugin expects)

### 9.3 Distribution Patterns

Document and support two distribution patterns:
1. **Fork and extend** — organization forks Canon plugin, adds custom skills, distributes via internal marketplace
2. **Layered plugins** — organization creates a separate plugin that depends on Canon plugin, adding only org-specific skills

### Acceptance Criteria

- [ ] Plugin manifest supports `extensions` field for org-specific skill directories
- [ ] Marketplace metadata fields added to `plugin.json` (version, description, compatibility)
- [ ] Documentation covers fork-and-extend distribution pattern
- [ ] Documentation covers layered plugin distribution pattern
- [ ] Org-specific skills can reference Canon MCP tools
- [ ] Example org-specific skill template provided

## Open Questions

1. **Git lifecycle sync vs. GitHub Actions**: Should Canon's git lifecycle sync replace or complement existing GitHub Actions that enterprises may already have for Jira automation? Recommendation: complement — Canon provides the config-driven approach, enterprises can keep existing Actions and Canon will not conflict (both can create remote links; status transitions are idempotent).

2. **Cross-repo performance**: Cross-repo initiative tracking requires GitHub API calls to resolve references. Should we cache resolved references, and if so, for how long? The org config cache (5-minute TTL) may be appropriate.

3. **Review enforcement strictness**: Should `require_review` be all-or-nothing, or should it support per-spec-type granularity? (e.g., proposals require review, ADRs don't). Recommendation: per-spec-type granularity via `review.required_types: [proposal, spec]`.

4. **Metrics API authentication**: Should the metrics API use the same API key auth as the MCP server, or should it support dedicated read-only metrics tokens? Recommendation: same API key auth with a new `metrics:read` permission.
