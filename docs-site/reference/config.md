# CANON.yaml Reference

::: info Legacy Config
If your repo has a `SPECWRIGHT.yaml`, Canon will still read it as a fallback. Rename it to `CANON.yaml` when convenient.
:::

The `CANON.yaml` file configures Canon behavior for a repository. Place it in the repository root.

## Schema

```yaml
# Required
version: "1"

# Optional: team metadata
team: string              # Team name
ticket_system: string     # Default ticket system (jira, linear, github)
project_key: string       # Default project key
slack_channel: string     # Slack channel for notifications

# Spec configuration
specs:
  doc_paths: string[]     # Glob patterns for files to index
  auto_tickets: boolean   # Auto-create tickets from spec sections
  require_review: boolean # Require review before ticket creation

# Agent behavior
agents:
  pr_analysis: boolean    # Enable PR analysis comments
  doc_updates: boolean    # Enable doc update suggestions
  stale_detection: string | false  # Duration or false
  realization_check: boolean       # Enable AC realization tracking

# Simple ticket sync
sync:
  system: string          # jira, linear, or github
  project_key: string     # Project key for ticket creation
  create_tickets: boolean # Auto-create tickets
  reverse_sync: boolean   # Sync ticket status back to specs

# Advanced: multi-system ticket routing
ticket_systems:
  <name>:
    system: string        # jira, linear, or github
    project: string       # Project key
    status_map:           # Spec status → ticket status mapping
      draft: string
      todo: string
      in_progress: string
      done: string
      blocked: string
      deprecated: string
    hierarchy:            # Section depth → issue type mapping
      2: string           # e.g., "Epic"
      3: string           # e.g., "Story"
      4: string           # e.g., "Sub-task"
    auto_parent: boolean  # Auto-link child tickets to parent

routing:
  - match:
      tags: string[]      # Match on spec tags
      team: string        # Match on team
      default: boolean    # Default route
    target: string        # ticket_systems key
```

## Fields

### `version`

**Required.** Schema version. Currently only `"1"` is supported.

### `team`

Team name used for ticket routing and dashboards.

### `ticket_system`

Default ticket system. One of: `jira`, `linear`, `github`.

### `project_key`

Default project key for ticket creation (Jira project key, Linear team key, or GitHub `owner/repo`).

### `slack_channel`

Slack channel for notifications (e.g., `"#payments-eng"`).

### `specs`

#### `specs.doc_paths`

**Type:** `string[]`
**Default:** `["docs/specs/*.md"]`

Glob patterns for files to index. All matched files become part of the agent's knowledge base.

```yaml
specs:
  doc_paths:
    - "docs/specs/*.md"
    - "docs/**/*.md"
    - "README.md"
    - "CHANGELOG.md"
```

#### `specs.auto_tickets`

**Type:** `boolean`
**Default:** `false`

When `true`, the agent automatically creates tickets from spec sections.

#### `specs.require_review`

**Type:** `boolean`
**Default:** `true`

When `true`, auto-created tickets require review before creation.

### `agents`

#### `agents.pr_analysis`

**Type:** `boolean`
**Default:** `true`

Enable PR analysis comments. Set to `false` to disable the bot commenting on PRs.

#### `agents.doc_updates`

**Type:** `boolean`
**Default:** `true`

Enable doc update suggestions in PR comments.

#### `agents.stale_detection`

**Type:** `string | false`
**Default:** `"30d"`

Duration string (e.g., `"30d"`, `"7d"`) before flagging stale sections, or `false` to disable.

#### `agents.realization_check`

**Type:** `boolean`
**Default:** `true`

Enable acceptance criteria realization tracking in PR analysis.

### `sync`

Simple ticket sync configuration. For multi-system routing, use `ticket_systems` instead.

#### `sync.system`

**Type:** `string`

Ticket system: `jira`, `linear`, or `github`.

#### `sync.project_key`

**Type:** `string`

Project key for ticket creation.

#### `sync.create_tickets`

**Type:** `boolean`
**Default:** `true`

Auto-create tickets from spec sections.

#### `sync.reverse_sync`

**Type:** `boolean`
**Default:** `true`

Sync ticket status changes back to specs.

### `ticket_systems` / `routing`

Advanced multi-system ticket routing. See the [Ticket Sync guide](/guides/ticket-sync#advanced-multi-system-routing) for detailed usage.

## Examples

### Minimal

```yaml
version: "1"

specs:
  doc_paths:
    - "docs/specs/*.md"
```

### Full-Featured

```yaml
version: "1"

team: payments
ticket_system: jira
project_key: PAY
slack_channel: "#payments-eng"

specs:
  doc_paths:
    - "docs/specs/*.md"
    - "docs/**/*.md"
    - "README.md"
    - "CHANGELOG.md"
  auto_tickets: true
  require_review: true

agents:
  pr_analysis: true
  doc_updates: true
  stale_detection: "30d"
  realization_check: true

sync:
  system: jira
  project_key: PAY
  create_tickets: true
  reverse_sync: true
```
