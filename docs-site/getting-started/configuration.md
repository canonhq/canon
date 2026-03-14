# Configuration

Canon is configured via a `CANON.yaml` file in your repository root. This page covers all available settings.

## Minimal Configuration

```yaml
version: "1"

specs:
  doc_paths:
    - "docs/specs/*.md"
```

This enables spec parsing for files matching `docs/specs/*.md`. All other features use sensible defaults.

## Full Configuration

```yaml
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
    - "CONTRIBUTING.md"
  auto_tickets: true
  require_review: true

agents:
  pr_analysis: true
  doc_updates: true
  stale_detection: "30d"
  realization_check: true
```

## Settings Reference

### Top-Level

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `team` | string | — | Team name for ticket routing and dashboards |
| `ticket_system` | string | — | Default ticket system (`jira`, `linear`, `github`) |
| `project_key` | string | — | Default project key for ticket creation |
| `slack_channel` | string | — | Slack channel for notifications |

### `specs`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `doc_paths` | string[] | `["docs/specs/*.md"]` | Glob patterns for spec and doc files to index |
| `auto_tickets` | boolean | `true` | Auto-create tickets from spec sections when the agent processes a push |
| `require_review` | boolean | `true` | Require `review_status: approved` in frontmatter before ticket creation |

### `agents`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `pr_analysis` | boolean | `true` | Enable PR analysis comments |
| `doc_updates` | boolean | `true` | Enable doc update suggestions |
| `stale_detection` | string \| false | `"30d"` | Flag sections not updated within this duration |
| `realization_check` | boolean | `true` | Enable acceptance criteria realization tracking |

## Ticket Sync Behavior

Forward sync (`canon sync`) creates tickets **only for sections with `status:todo` or `status:in_progress`**. Sections in `draft`, `done`, `blocked`, or `deprecated` status are skipped — they're not actionable work items.

If you're logged in (`canon login`) and your org has the Canon GitHub App installed, sync automatically uses the server as a proxy — no local `GITHUB_TOKEN` needed. Use `canon sync --local` to force local credentials.

See the [Ticket Sync guide](/guides/ticket-sync) for full details and the [CLI Reference](/reference/cli) for command options.

## All-Markdown Indexing

By default, Canon only indexes files matching `docs/specs/*.md`. To index your entire documentation tree — ADRs, guides, READMEs, changelogs — expand `doc_paths`:

```yaml
specs:
  doc_paths:
    - "docs/specs/*.md"        # specs (always)
    - "docs/**/*.md"           # all docs recursively
    - "README.md"              # root readme
    - "CHANGELOG.md"           # changelog
    - "CONTRIBUTING.md"        # contributing guide
```

All indexed documents become part of the agent's context when analyzing PRs. This means ADRs, architecture docs, and guides are checked for staleness alongside specs.

## Advanced: Multi-System Ticket Routing

For enterprise teams with multiple ticket systems or custom Jira workflows, use the `ticket_systems` key:

```yaml
ticket_systems:
  engineering:
    system: jira
    project: ENG
    status_map:
      draft: "Backlog"
      todo: "Open"
      in_progress: "In Development"
      done: "Closed"
      blocked: "On Hold"
      deprecated: "Won't Fix"
    hierarchy:
      2: "Epic"
      3: "Story"
      4: "Sub-task"
    auto_parent: true
  oss:
    system: github
    repo: org/public-repo

routing:
  - match:
      tags: ["open-source"]
    target: oss
  - match:
      default: true
    target: engineering
```

See the [Ticket Sync guide](/guides/ticket-sync) for details.

## Repo Structure

A typical repository with Canon looks like:

```
my-service/
├── src/
├── tests/
├── docs/
│   ├── specs/
│   │   ├── payments-overhaul.md    ← living spec
│   │   └── auth-migration.md       ← living spec
│   ├── decisions/
│   │   └── 2026-01-datastore.md    ← ADR (indexed)
│   ├── architecture.md             ← agent-maintained
│   └── runbooks/
│       └── deploy-payments.md      ← operational doc
├── README.md                        ← indexed
├── CHANGELOG.md                     ← indexed
├── CANON.yaml                  ← config
└── ...
```
