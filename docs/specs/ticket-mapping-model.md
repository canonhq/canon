---
title: "Ticket Mapping Model"
status: done
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-03-04
tags: [sync, enterprise, data-model]
---

# Ticket Mapping Model

Replace the hardcoded ticket sync mappings with a configurable, schema-driven model that supports enterprise-grade customization — custom workflows, field mapping, hierarchy templates, multi-system routing, and org-wide defaults.

## 1. Background

<!-- specwright:system:1 status:done -->

Today's sync layer assumes a fixed mapping between spec states and ticket system statuses (hardcoded dicts in `status_map.py`). Issue types are always "Task", there's no field mapping beyond summary/description, and each repo targets a single ticket system with a single project key.

This breaks in enterprise environments where:
- Jira workflows have custom statuses ("In QA", "Awaiting Deployment", "Product Review")
- Different teams use different issue types (Epic → Story → Subtask vs. Theme → Initiative → Task)
- Spec metadata (team, tags, owner) should flow into ticket fields (component, labels, assignee)
- Some orgs use multiple ticket systems (Jira for eng, ServiceNow for ops, GitHub Issues for OSS)
- Large orgs need org-wide defaults that individual repos can override

### Supported Enterprise Jira Workflows

The mapping model supports these real-world enterprise configurations:

**1. Software Development with QA Gate**
```yaml
status_map:
  forward:
    draft: "Backlog"
    todo: "Open"
    in_progress: "In Development"
    done: "Closed"
    blocked: "On Hold"
    deprecated: "Won't Fix"
  reverse:
    "Backlog": "draft"
    "Open": "todo"
    "In Development": "in_progress"
    "In QA": "in_progress"
    "Awaiting Deployment": "in_progress"
    "Closed": "done"
    "On Hold": "blocked"
```
Teams with a QA stage and deployment queue map multiple Jira statuses back to `in_progress` since the spec doesn't distinguish sub-stages of active work.

**2. Product-Led with Review Stages**
```yaml
status_map:
  forward:
    draft: "Icebox"
    todo: "Prioritized"
    in_progress: "In Progress"
    done: "Shipped"
    blocked: "Needs Input"
    deprecated: "Archived"
  reverse:
    "Icebox": "draft"
    "Prioritized": "todo"
    "Product Review": "in_progress"
    "In Progress": "in_progress"
    "Staging": "in_progress"
    "Shipped": "done"
    "Needs Input": "blocked"
    "Archived": "deprecated"
hierarchy:
  2: "Initiative"
  3: "Story"
  4: "Sub-task"
  auto_parent: true
```
Product orgs using Initiative → Story hierarchy with multiple review checkpoints before shipping.

**3. Regulated/Compliance Workflow**
```yaml
status_map:
  forward:
    draft: "New"
    todo: "Approved"
    in_progress: "In Development"
    done: "Released"
    blocked: "Pending Approval"
    deprecated: "Rejected"
  reverse:
    "New": "draft"
    "Approved": "todo"
    "In Development": "in_progress"
    "In Review": "in_progress"
    "Security Review": "in_progress"
    "Released": "done"
    "Pending Approval": "blocked"
    "Rejected": "deprecated"
field_map:
  standard:
    "frontmatter.team": "component"
    "frontmatter.owner": "assignee"
  custom:
    "customfield_10001": "frontmatter.tags[0]"
    "customfield_10050": "literal:canon-managed"
```
Regulated environments with mandatory security review stages and custom field tracking for audit compliance.

### Acceptance Criteria

- [x] MUST document at least 3 real enterprise Jira workflow configurations that the model supports
<!-- specwright:realized-in:PR#314 file:docs/specs/ticket-mapping-model.md -->
- [x] MUST preserve backward compatibility — repos without custom config behave identically to today
<!-- specwright:realized-in:PR#106 file:tests/test_sync/test_backward_compat.py -->

## 2. Mapping Schema

<!-- specwright:system:2 status:done -->

A new `TicketMappingConfig` Pydantic model that lives in `sync/mapping.py` and is referenced from `CANON.yaml`.

### 2.1 Status Mapping

<!-- specwright:system:2.1 status:done -->

User-defined bidirectional status maps that replace the hardcoded dicts.

```yaml
# CANON.yaml
ticket_systems:
  primary:
    system: jira
    project: PAY
    status_map:
      forward:
        # spec_state: ticket_status_name
        draft: "Backlog"
        todo: "Open"
        in_progress: "In Development"
        done: "Closed"
        blocked: "On Hold"
        deprecated: "Won't Fix"
      reverse:
        # jira_status_category_key or exact_status_name: spec_state
        "new": "todo"
        "indeterminate": "in_progress"
        "done": "done"
        "On Hold": "blocked"
```

When `status_map.forward` is provided, it overrides individual entries in the default forward mapping for that system — any spec states not covered by the custom map fall back to the built-in default (merge-with-fallback). When `status_map.reverse` is provided, it extends/overrides the default reverse mapping. Unmapped values fall back to the `fallback` value (default: "draft"). This structure mirrors the `StatusMapConfig` Pydantic model in section 5.

### Acceptance Criteria

- [x] MUST support user-defined forward status map (spec → ticket)
<!-- specwright:realized-in:PR#106 file:src/specwright/sync/mapping.py -->
<!-- specwright:realized-in:PR#291 file:src/specwright/sync/engine.py -->
- [x] MUST support user-defined reverse status map (ticket → spec)
- [x] MUST fall back to current hardcoded defaults when no custom map is configured
<!-- specwright:realized-in:PR#106 file:src/specwright/sync/status_map.py -->
- [x] MUST validate that all 6 spec states are covered in a custom status_map (warn if incomplete)
- [x] SHOULD support mapping by exact status name OR by Jira statusCategory key

### 2.2 Field Mapping

<!-- specwright:system:2.2 status:done -->

Declarative rules for mapping spec metadata to ticket fields.

```yaml
ticket_systems:
  primary:
    system: jira
    project: PAY
    field_map:
      standard:
        # spec_source: ticket_field
        "frontmatter.team": "component"
        "frontmatter.owner": "assignee"
        "frontmatter.tags": "labels"
        "section.section_number": "summary_prefix"
        "section.acceptance_criteria": "description_appendix"
      custom:
        # jira custom field ID: spec source or literal
        "customfield_10001": "frontmatter.tags[0]"    # Epic Name
        "customfield_10002": "literal:canon-managed"
```

Field mapping is optional. When absent, behavior matches today (summary = section title, description = section content).

### Acceptance Criteria

- [x] MUST support mapping frontmatter fields to ticket fields
<!-- specwright:realized-in:PR#106 file:src/specwright/sync/field_resolver.py -->
- [x] MUST support mapping to Jira custom fields by field ID
- [x] MUST support literal values in field mappings
- [x] MUST validate field map sources against known spec model fields at config parse time
- [x] SHOULD support array/list field sources (tags → labels)

<!-- canon:ticket:github:432 -->
### 2.3 Hierarchy Templates

<!-- canon:system:2.3 status:in_progress -->

Configurable mapping from spec section depth to ticket issue types and parent-child relationships.

```yaml
ticket_systems:
  primary:
    system: jira
    project: PAY
    hierarchy:
      # section_depth: issue_type
      2: "Epic"        # h2 → Epic
      3: "Story"       # h3 → Story
      4: "Sub-task"    # h4 → Sub-task
    auto_parent: true  # h3 auto-links to parent h2's ticket
```

When `hierarchy` is absent, all sections create "Task" issues (current behavior). When `auto_parent` is true, the engine passes the parent section's ticket_id as `parent_ticket_id` in `CreateTicketInput`.

### Acceptance Criteria

- [x] MUST support configuring issue type per section depth
<!-- specwright:realized-in:PR#106 file:src/specwright/sync/hierarchy.py -->
- [x] MUST support auto-parenting (child section ticket linked to parent section ticket)
- [x] MUST fall back to "Task" issue type when no hierarchy is configured
- [x] MUST validate issue type names are non-empty strings
- [ ] SHOULD support Linear team-specific workflow states in hierarchy context

<!-- canon:ticket:github:433 -->
## 3. Multi-System Routing

<!-- canon:system:3 status:in_progress -->

Support multiple ticket systems per repo, with routing rules that determine which system a given section targets.

```yaml
ticket_systems:
  engineering:
    system: jira
    project: ENG
    # ... status_map, field_map, hierarchy ...
  operations:
    system: jira
    project: OPS
    host_override: ops-jira.example.com  # different Jira instance
  oss:
    system: github
    repo: org/public-repo

routing:
  # Rules evaluated in order; first match wins
  - match:
      tags: ["infrastructure", "ops"]
    target: operations
  - match:
      tags: ["open-source"]
    target: oss
  - match:
      default: true
    target: engineering
```

Routing matches against section-level or frontmatter-level metadata. When no routing rules are defined and only one system is configured under `ticket_systems`, all sections target that system (simple case, backward compatible).

### Acceptance Criteria

- [x] MUST support defining multiple named ticket system configurations
- [x] MUST support tag-based routing rules
<!-- specwright:realized-in:PR#106 file:src/specwright/sync/router.py -->
- [x] MUST support a default route (fallback)
- [x] MUST evaluate routing rules in declared order (first match wins)
- [x] MUST fall back to single-system behavior when only one system is defined
- [x] SHOULD support routing by frontmatter fields (team, owner)
- [x] SHOULD support routing by spec file path glob

<!-- section done: old ticket #266 closed -->
<!-- canon:ticket:github:434 -->
## 4. Enterprise Configuration Layers

<!-- canon:system:4 status:in_progress -->

Support org-wide defaults that individual repos inherit and can override.

<!-- section done: old ticket #267 closed -->
<!-- section done: old ticket #289 closed -->
### 4.1 Org-Level Defaults

<!-- specwright:system:4.1 status:done -->

An org-level config stored in a well-known location (e.g., `.github/canon.yaml` in the org's `.github` repo, or managed via the Canon web app) that provides defaults for all repos.

```yaml
# Org-level: .github/canon.yaml
org_defaults:
  ticket_systems:
    primary:
      system: jira
      project: null  # must be set per-repo
      status_map:
        draft: "Backlog"
        todo: "To Do"
        in_progress: "In Progress"
        done: "Done"
        blocked: "Blocked"
        deprecated: "Won't Do"
      hierarchy:
        2: "Epic"
        3: "Story"
        4: "Sub-task"
      field_map:
        "frontmatter.team": "component"
```

Repo-level `CANON.yaml` merges on top of org defaults using a deep-merge strategy: maps are merged key-by-key, lists are replaced (not appended), scalars are overridden.

### Acceptance Criteria

- [x] MUST support loading org-level defaults from a configurable source
<!-- specwright:realized-in:PR#291 file:src/specwright/sync/org_config.py -->
<!-- specwright:realized-in:PR#314 file: -->
- [x] MUST deep-merge repo config on top of org defaults
<!-- specwright:realized-in:PR#291 file:src/specwright/sync/mapping.py -->
<!-- specwright:realized-in:PR#291 file:src/specwright/github/handlers/on_push.py -->
- [x] MUST allow repos to override any org default
- [x] MUST allow repos to explicitly null-out an org default (e.g., `field_map: null`)
- [x] SHOULD support loading org config from `.github` repo or Canon API
<!-- specwright:realized-in:PR#291 file:src/specwright/sync/org_config.py -->

### 4.2 Auth Profiles

<!-- specwright:system:4.2 status:done -->

Named credential sets that decouple auth from system config, supporting multiple Jira instances or mixed auth methods.

```yaml
auth_profiles:
  jira-cloud:
    system: jira
    auth_method: api_token
    env_prefix: JIRA_CLOUD_    # reads JIRA_CLOUD_HOST, JIRA_CLOUD_EMAIL, JIRA_CLOUD_API_TOKEN
  jira-datacenter:
    system: jira
    auth_method: personal_access_token
    env_prefix: JIRA_DC_
  linear-eng:
    system: linear
    auth_method: api_key
    env_prefix: LINEAR_ENG_
  github-oss:
    system: github
    auth_method: app_installation
    env_prefix: GH_OSS_

ticket_systems:
  engineering:
    auth_profile: jira-cloud
    project: ENG
  ops:
    auth_profile: jira-datacenter
    project: OPS
```

When `auth_profile` is set, the adapter factory reads credentials from the named profile's env vars instead of the default env vars. When absent, falls back to today's auto-detection from `JIRA_HOST`, `LINEAR_API_KEY`, etc.

### Acceptance Criteria

- [x] MUST support named auth profiles with configurable env var prefixes
- [x] MUST support at least: api_token, personal_access_token, api_key, app_installation auth methods
- [x] MUST fall back to current env var auto-detection when no auth profile is set
- [x] MUST validate that referenced auth profiles exist in config
- [x] MUST NOT store credentials in config files (env vars only)

<!-- canon:ticket:github:435 -->
### 4.3 Ticket Description Templates

<!-- canon:system:4.3 status:in_progress -->

Configurable Jinja2-style templates for ticket body generation, replacing the current hardcoded `section.content[:2000]` truncation.

```yaml
ticket_systems:
  primary:
    system: jira
    project: ENG
    templates:
      description: |
        h2. {{section.title}}

        {{section.content}}

        h3. Acceptance Criteria
        {{#each section.acceptance_criteria}}
        * {{this.text}}
        {{/each}}

        ----
        _Managed by [Canon|{{spec_url}}] — {{spec.title}} §{{section.section_number}}_
      summary: "[{{section.section_number}}] {{section.title}}"
```

When no template is defined, use sensible defaults that match current behavior.

### Acceptance Criteria

- [x] MUST support configurable description templates with variable interpolation
<!-- specwright:realized-in:PR#106 file:src/specwright/sync/templates.py -->
- [x] MUST support configurable summary templates
- [x] MUST expose spec metadata, section data, and acceptance criteria as template variables
- [x] MUST fall back to current behavior when no template is configured
- [ ] SHOULD support system-specific markup (ADF for Jira, Markdown for GitHub/Linear)

## 5. Data Model (Pydantic)

<!-- specwright:system:5 status:done -->

The core Pydantic models that implement this spec. All models live in `sync/mapping.py`.

```python
class StatusMapConfig(BaseModel):
    forward: dict[str, str] = {}      # spec_state → ticket_status
    reverse: dict[str, str] = {}      # ticket_status → spec_state
    fallback: str = "draft"           # unmapped ticket statuses → this spec state

class FieldMapConfig(BaseModel):
    standard: dict[str, str] = {}     # spec_source → ticket_field
    custom: dict[str, str] = {}       # custom_field_id → spec_source_or_literal

class HierarchyConfig(BaseModel):
    depth_to_type: dict[int, str] = {}   # section_depth → issue_type
    auto_parent: bool = False
    default_type: str = "Task"

class TemplateConfig(BaseModel):
    summary: str | None = None
    description: str | None = None

class AuthProfile(BaseModel):
    system: str                       # jira, linear, github
    auth_method: str                  # api_token, personal_access_token, api_key, app_installation
    env_prefix: str                   # e.g. "JIRA_CLOUD_"

class TicketSystemConfig(BaseModel):
    system: str                       # jira, linear, github
    project: str | None = None
    auth_profile: str | None = None   # reference to AuthProfile name
    host_override: str | None = None
    status_map: StatusMapConfig = StatusMapConfig()
    field_map: FieldMapConfig = FieldMapConfig()
    hierarchy: HierarchyConfig = HierarchyConfig()
    templates: TemplateConfig = TemplateConfig()

class RoutingRule(BaseModel):
    match: dict[str, Any]             # tags, team, path, default
    target: str                       # ticket_system name

class TicketMappingConfig(BaseModel):
    auth_profiles: dict[str, AuthProfile] = {}
    ticket_systems: dict[str, TicketSystemConfig] = {}
    routing: list[RoutingRule] = []
    org_defaults_source: str | None = None  # ".github" or API URL
```

### Acceptance Criteria

- [x] MUST implement all models listed above with Pydantic v2
- [x] MUST validate config at parse time (missing refs, invalid field sources, incomplete status maps)
- [x] MUST produce clear, actionable error messages for invalid configs
- [x] MUST serialize cleanly to/from YAML
- [x] MUST support deep-merge of partial configs (for org → repo layering)

## 6. Backward Compatibility

<!-- specwright:system:6 status:done -->

Existing repos must work without changes. The migration path:

1. **No config change needed**: Repos with today's simple config (`ticket_system: jira`, `project_key: PAY`) continue to work. The parser synthesizes a `TicketMappingConfig` from the legacy fields.
2. **Gradual adoption**: Repos can add `ticket_systems:` alongside legacy fields. If both exist, `ticket_systems:` takes precedence with a deprecation warning on the legacy fields.
3. **Existing comments preserved**: The `<!-- canon:ticket:{system}:{id} -->` format remains unchanged. No migration of spec files required.

### Acceptance Criteria

- [x] MUST synthesize TicketMappingConfig from legacy config fields (ticket_system, project_key)
- [x] MUST emit deprecation warning when legacy and new config coexist
- [x] MUST NOT require changes to existing spec markdown files
- [x] MUST pass all existing sync tests unchanged after refactor
- [x] MUST NOT break the CLI (canon sync) or GitHub webhook handler
<!-- specwright:realized-in:PR#291 file:src/specwright/cli/sync_cmd.py -->

<!-- canon:ticket:github:436 -->
## 7. Adapter Protocol Changes

<!-- canon:system:7 status:in_progress -->

Extend the `TicketAdapter` protocol to support the richer mapping model without breaking existing adapters.

The current protocol:
```python
class TicketAdapter(Protocol):
    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult: ...
    async def update_ticket(self, input: UpdateTicketInput) -> None: ...
    async def get_ticket_status(self, ticket_id: str) -> TicketStatusResult: ...
    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None: ...
```

Changes:
- `CreateTicketInput` gains optional fields: `issue_type`, `custom_fields`, `parent_ticket_id` (already exists), `template_rendered_description`, `template_rendered_summary`
- `TicketAdapter` gains optional `capabilities` property so the engine knows what the adapter supports (custom fields, hierarchy, etc.)
- Factory gains `from_config(name: str, config: TicketSystemConfig, auth_profiles: dict) -> TicketAdapter`

### Acceptance Criteria

- [x] MUST extend CreateTicketInput with issue_type and custom_fields
<!-- specwright:realized-in:PR#106 file:src/specwright/sync/models.py -->
- [x] MUST add adapter capabilities discovery
<!-- specwright:realized-in:PR#106 file:src/specwright/sync/adapters/base.py -->
- [x] MUST add config-driven factory method
<!-- specwright:realized-in:PR#106 file:src/specwright/sync/adapters/factory.py -->
- [x] MUST NOT break existing adapter implementations
- [x] SHOULD add UpdateTicketInput.custom_fields for reverse field sync

<!-- section done: old tickets #268, #290 closed -->
## 8. Rollout Plan

<!-- specwright:system:8 status:done -->

**Phase 1 — Data model + status mapping** (this spec, core)
- Implement Pydantic models in `sync/mapping.py`
- Refactor `status_map.py` to use configurable maps with hardcoded defaults
- Update config parser to handle new `ticket_systems` key
- Backward compatibility layer for legacy config

**Phase 2 — Field mapping + hierarchy**
- Implement field mapping resolution in engine
- Implement hierarchy template logic (depth → type, auto-parent)
- Extend adapter protocol with new fields

**Phase 3 — Multi-system routing + auth profiles**
- Implement routing rule evaluation
- Implement auth profile resolution in factory
- Support multiple adapters per sync run

**Phase 4 — Org defaults + templates**
- Org config loading (from `.github` repo or API)
- Deep-merge logic
- Template rendering engine

### Acceptance Criteria

- [x] MUST ship Phase 1 as a standalone, useful increment
- [x] MUST have tests for each phase before moving to the next
- [x] SHOULD be deployable incrementally (no big-bang migration)

## 9. Open Questions

<!-- canon:system:9 status:done -->

- ~~Should org defaults be loaded at startup or on each sync?~~ **Resolved**: On each sync with 5-minute TTL cache (`org_config.py`).
- Do we need a `canon validate-config` CLI command for testing enterprise configs?
- Should we support Azure DevOps and ServiceNow adapters in this spec or defer to a follow-up?
- ~~How do we handle Jira Server vs. Jira Cloud API differences in status mapping?~~ **Resolved**: Reverse mapping supports both exact status names and Jira `statusCategory` keys.
- Should routing rules support regex matching on section titles?
