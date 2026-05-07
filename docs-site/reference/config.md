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
  auto_tickets: boolean   # Auto-create tickets from spec sections (default: true)
  require_review: boolean # Require review before ticket creation
  lifecycle_sync: boolean | "close_only"  # Sync ticket lifecycle to spec status

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

# IDE / Claude Code plugin
ide:
  auto_context:
    enabled: boolean
    on_session_start: boolean
    on_prompt: boolean
    max_specs: integer
  auto_verify:
    enabled: boolean
    on_stop: boolean
    on_commit: boolean
    confidence: medium | high
  ai_exposure:
    default: full | metadata | none
    restricted_tags: string[]
  evidence_pipeline:
    enabled: boolean
    persist: file | mcp | both
    commit_on_push: ask | always | never

# SRE integration
sre:
  alerts_channel: string
  auto_triage: boolean
  weekly_digest: boolean
  error_spike_threshold: integer

# Advanced Slack configuration
slack:
  default_channel: string
  sre_channel: string
  notifications:
    spec_status_change: boolean
    spec_created: boolean
    coverage_regression: boolean
    stale_spec_warning: boolean
    pr_analysis_summary: boolean
    ticket_sync_failure: boolean
    review_requested: boolean
    coverage_threshold: integer
  quiet_hours:
    start: string
    end: string
  digest:
    channel: string
    schedule: string
    team_digests: map
  dashboard_refresh: daily | weekly | false
  allow_shared_channels: boolean

# Extension configuration
extensions:
  <extension-name>: map
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
**Default:** `true`

When `true`, the agent automatically creates tickets from spec sections.

#### `specs.require_review`

**Type:** `boolean`
**Default:** `true`

When `true`, auto-created tickets require review before creation.

#### `specs.lifecycle_sync`

**Type:** `boolean | "close_only"`
**Default:** `true`

Controls whether spec section status is synced from ticket lifecycle events.

- `true` — full bidirectional sync: ticket status changes update spec section status
- `false` — no lifecycle sync
- `"close_only"` — only sync when a ticket is closed/done (does not sync intermediate states like "in progress")

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

### `ide`

Controls the Canon Claude Code plugin behavior in the IDE. All fields are optional; omitting a sub-section uses its defaults.

```yaml
ide:
  auto_context:
    enabled: true
    on_session_start: true
    on_prompt: true
    max_specs: 5

  auto_verify:
    enabled: true
    on_stop: true
    on_commit: false
    confidence: medium

  ai_exposure:
    default: full
    restricted_tags: []

  evidence_pipeline:
    enabled: false
    persist: file
    commit_on_push: ask
```

#### `ide.auto_context`

Controls automatic spec context injection into Claude sessions.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `boolean` | `true` | Master switch for auto-context injection |
| `on_session_start` | `boolean` | `true` | Inject relevant specs when a new session starts |
| `on_prompt` | `boolean` | `true` | Re-inject context on each prompt turn |
| `max_specs` | `integer` | `5` | Maximum number of specs to inject (must be ≥ 1) |

#### `ide.auto_verify`

Controls the Canon verify gate that runs acceptance criteria checks.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `boolean` | `true` | Master switch for the verify gate |
| `on_stop` | `boolean` | `true` | Run verify when a Claude session stops |
| `on_commit` | `boolean` | `false` | Run verify before each git commit |
| `confidence` | `"medium" \| "high"` | `"medium"` | Minimum confidence level required to pass verification |

#### `ide.ai_exposure`

Controls how much spec content is exposed to AI tools at the repo level. Individual specs can override this with `ai_exposure` frontmatter.

| Field | Type | Default | Description |
|---|---|---|---|
| `default` | `"full" \| "metadata" \| "none"` | `"full"` | Default exposure level for all specs in this repo |
| `restricted_tags` | `string[]` | `[]` | Specs with any of these tags are automatically downgraded to `"metadata"` exposure. Note: `"none"` can only be set per-spec via frontmatter. |

#### `ide.evidence_pipeline`

Opt-in pipeline that records dev-session evidence to `.canon/session-evidence.json` and verify-gate results to `.canon/verify-log.jsonl`. Off by default.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `boolean` | `false` | Enable the evidence pipeline |
| `persist` | `"file" \| "mcp" \| "both"` | `"file"` | Where to persist evidence: local file, MCP server, or both |
| `commit_on_push` | `"ask" \| "always" \| "never"` | `"ask"` | Whether to auto-commit evidence files when pushing |

### `sre`

Controls Canon's SRE/observability integration features.

```yaml
sre:
  alerts_channel: "#canon-alerts"
  auto_triage: true
  weekly_digest: true
  error_spike_threshold: 10
```

| Field | Type | Default | Description |
|---|---|---|---|
| `alerts_channel` | `string` | `"#canon-alerts"` | Slack channel for SRE alert notifications |
| `auto_triage` | `boolean` | `true` | Automatically triage incoming alerts against open spec sections |
| `weekly_digest` | `boolean` | `true` | Send a weekly SRE digest to `alerts_channel` |
| `error_spike_threshold` | `integer` | `10` | Number of errors per minute that triggers a spike alert |

### `slack`

Advanced Slack integration settings. For a simple notification channel, use the top-level `slack_channel` field instead.

```yaml
slack:
  default_channel: "#canon-specs"
  sre_channel: "#canon-sre"
  notifications:
    spec_status_change: true
    spec_created: true
    coverage_regression: true
    stale_spec_warning: true
    pr_analysis_summary: true
    ticket_sync_failure: true
    review_requested: true
    coverage_threshold: 80
  quiet_hours:
    start: "22:00"
    end: "08:00"
  digest:
    channel: "#canon-digest"
    schedule: "monday 09:00"
    team_digests:
      payments:
        channel: "#payments-digest"
        schedule: "monday 09:00"
  dashboard_refresh: false
  allow_shared_channels: false
```

#### `slack` top-level fields

| Field | Type | Default | Description |
|---|---|---|---|
| `default_channel` | `string` | `"#canon-specs"` | Default channel for general Canon notifications |
| `sre_channel` | `string` | `""` | Override channel for SRE alerts (falls back to `sre.alerts_channel`) |
| `dashboard_refresh` | `"daily" \| "weekly" \| false` | `false` | Post a dashboard summary on this cadence |
| `allow_shared_channels` | `boolean` | `false` | Allow Canon to post to Slack shared channels (external workspaces) |

#### `slack.notifications`

Toggle individual notification types. Each field can be a `boolean`, or a dict with `enabled` and `channel` to route that type to a specific channel.

| Field | Type | Default | Description |
|---|---|---|---|
| `spec_status_change` | `boolean \| {enabled, channel}` | `true` | Notify when a spec section changes status |
| `spec_created` | `boolean \| {enabled, channel}` | `true` | Notify when a new spec is created |
| `coverage_regression` | `boolean \| {enabled, channel}` | `true` | Notify when spec coverage drops |
| `stale_spec_warning` | `boolean \| {enabled, channel}` | `true` | Notify when specs pass the stale threshold |
| `pr_analysis_summary` | `boolean \| {enabled, channel}` | `true` | Post PR analysis summaries to Slack |
| `ticket_sync_failure` | `boolean \| {enabled, channel}` | `true` | Alert when ticket sync encounters errors |
| `review_requested` | `boolean \| {enabled, channel}` | `true` | Notify when a spec review is requested |
| `coverage_threshold` | `integer` | `80` | Coverage percentage below which a regression notification fires |

Example — route coverage alerts to a dedicated channel while disabling review notifications:

```yaml
slack:
  notifications:
    coverage_regression:
      enabled: true
      channel: "#eng-coverage"
    review_requested: false
```

#### `slack.quiet_hours`

Suppress notifications during off-hours. When set, notifications are queued and delivered after `end` time.

| Field | Type | Default | Description |
|---|---|---|---|
| `start` | `string` | `"22:00"` | Start of quiet period (24-hour `HH:MM`) |
| `end` | `string` | `"08:00"` | End of quiet period (24-hour `HH:MM`) |

#### `slack.digest`

Configure a periodic digest of spec activity.

| Field | Type | Default | Description |
|---|---|---|---|
| `channel` | `string` | `""` | Channel to post the digest (required to enable) |
| `schedule` | `string` | `"monday 09:00"` | Cron-style schedule: `"<day> HH:MM"` |
| `team_digests` | `map<string, {channel, schedule}>` | `{}` | Per-team digest overrides. Each entry requires a `channel` and optionally a `schedule`. |

#### `slack.work_context`

> **Status (v1):** Infrastructure is built but this section is disabled by default. Enable it only after wiring `canon_config`, `slack_identity_store`, and `slack_spec_loader` into `app.state` (see deployment notes).

Controls the smarter-bot personal DM context feature. When enabled, DMs to the Canon bot include user-specific context (owned specs, team coverage, follow/mute state) so the bot can answer "my specs", "what should I work on", and similar personal queries without the user naming themselves.

```yaml
slack:
  work_context:
    enabled: false   # set to true to activate personal DM context
```

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `boolean` | `false` | Enable personal DM context injection for @canon mentions and DMs. Requires `slack_identity_store` wired into `app.state`. |

When `enabled: false` (default), the bot answers DMs with the same channel-style spec context — no personal data is injected and behavior is identical to earlier releases.

When `enabled: true`, the bot additionally:
- Resolves the Slack user ID to a GitHub login (via `/canon link`)
- Injects owned specs, team coverage, and follow/mute state into the Claude system prompt for DM queries
- Activates intent shortcuts: "my specs", "what should I work on", "what's blocked on me", "my team"

Source loaders active in v1: `canon_specs`, `slack_threads`. Loaders `github_prs`, `github_commits`, `tickets`, and `canon_pr_analysis` ship as graceful stubs and will become active in a follow-up release once the underlying APIs are extended.

### `extensions`

The `extensions` key is reserved for configuring Canon plugin extensions. Extension-specific options are defined by each extension and documented separately.

```yaml
extensions:
  my-extension:
    option: value
```

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
