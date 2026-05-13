# Ticket Sync

Canon maintains a **live link** between spec sections and tickets. This is bidirectional — specs create tickets, ticket status flows back to specs, and code merges close tickets with evidence.

## How It Works

### Spec → Tickets (Forward Sync)

When `auto_tickets` is enabled, the agent creates tickets from spec sections:

```markdown
## 3. Idempotency Layer
<!-- canon:ticket:jira:PAY-142 -->
<!-- canon:system:idempotency status:in_progress -->

All payment endpoints must support idempotency keys...

### 3.1 Key Generation
<!-- canon:ticket:jira:PAY-143 -->
<!-- canon:system:key-gen status:done -->
<!-- canon:realized-in:PR#412 src/payments/keys.ts -->

### 3.2 Retry Handling
<!-- canon:ticket:jira:PAY-144 -->
<!-- canon:system:retry status:in_progress -->
```

Hidden HTML comments track the bidirectional link. Engineers never think about this — the agent manages it.

### Tickets → Spec (Reverse Sync)

- Engineer closes PAY-143 → agent verifies against code, updates spec status
- PM adds acceptance criteria in Jira → agent opens PR to update spec section
- Unmapped ticket created → agent asks: "Should I add a spec section, or is this out of scope?"

### Code → Spec (Realization Sync)

- PR merges implementing §3.1 → agent analyzes code, marks section as realized
- Code changes contradict §3.2 → agent flags conflict, suggests spec or code update
- New behavior introduced without spec → agent asks: "Should I add a spec section for this?"

## Configuration

### Simple Setup

For a single ticket system with default status mappings:

```yaml
ticket_system: jira       # or: linear, github
project_key: PAY          # Jira project key, Linear team, or GitHub repo
specs:
  auto_tickets: true      # auto-create tickets from spec sections
  lifecycle_sync: true    # sync ticket status back to specs
```

### Supported Systems

| System | `system` value | `project_key` format |
|--------|---------------|---------------------|
| Jira | `jira` | Project key (e.g., `PAY`) |
| Linear | `linear` | Team key (e.g., `payments`) |
| GitHub Issues | `github` | `owner/repo` |

### Required Secrets

| System | Environment Variables |
|--------|---------------------|
| Jira | `JIRA_HOST`, `JIRA_EMAIL`, `JIRA_API_TOKEN` |
| Linear | `LINEAR_API_KEY` |
| GitHub (local) | `GITHUB_TOKEN` or `gh` CLI authenticated |
| GitHub (server proxy) | None — just `canon login` |

::: tip Server Proxy for GitHub
If you've run `canon login` and your org has the Canon GitHub App installed, `canon sync` automatically uses the server as a proxy. The server makes GitHub API calls using its App installation token — no local `GITHUB_TOKEN` needed. Use `--local` to bypass the proxy.
:::

## Advanced: Multi-System Routing

For enterprise teams with multiple ticket systems or custom Jira workflows:

```yaml
ticket_systems:
  engineering:
    system: jira
    project: ENG
    status_map:
      forward:
        draft: "Backlog"
        todo: "Open"
        in_progress: "In Development"
        done: "Closed"
        blocked: "On Hold"
        deprecated: "Won't Fix"
    hierarchy:
      depth_to_type:
        2: "Epic"        # h2 sections → Epics
        3: "Story"       # h3 sections → Stories
        4: "Sub-task"    # h4 sections → Sub-tasks
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

### Status Mapping

Map spec statuses to your ticket system's workflow statuses:

```yaml
status_map:
  forward:
    draft: "Backlog"        # spec draft → ticket Backlog
    todo: "Open"            # spec todo → ticket Open
    in_progress: "In Development"
    done: "Closed"
    blocked: "On Hold"
    deprecated: "Won't Fix"
```

### Hierarchy Templates

Map spec section depth to issue types:

```yaml
hierarchy:
  depth_to_type:
    2: "Epic"       # h2 sections create Epics
    3: "Story"      # h3 sections create Stories
    4: "Sub-task"   # h4 sections create Sub-tasks
  auto_parent: true
  default_type: Task
```

With `auto_parent: true`, child tickets are automatically linked to their parent.

### Routing Rules

Route sections to different ticket systems based on tags, team, or file path:

```yaml
routing:
  - match:
      tags: ["open-source"]
    target: oss
  - match:
      team: "security"
    target: security-board
    shadow_targets:
      - engineering    # read-only mirror to engineering board
  - match:
      default: true
    target: engineering
```

**Shadow targets** let you mirror tickets to additional systems as read-only copies. This is useful for cross-team visibility without creating duplicate work items.

### Field Mapping

Map spec metadata to ticket fields. Standard fields map common attributes; custom fields target system-specific fields using dotpath syntax.

```yaml
ticket_systems:
  engineering:
    system: jira
    project: ENG
    field_map:
      standard:
        frontmatter.team: component
        frontmatter.owner: assignee
        frontmatter.tags: labels
      custom:
        customfield_10001: frontmatter.owner
        customfield_10042: frontmatter.team
```

See the [full field mapping reference](/reference/config#field-mapping) for all available options.

### Presets

The Canon web app (Settings → Sync) offers **presets** — pre-configured mappings for common setups like "Jira Scrum", "Linear Standard", or "GitHub Issues". Applying a preset replaces the current status mappings, field mappings, and routing rules with preconfigured defaults.

Presets are a starting point — after applying one, you can customize individual mappings in the editor or directly in CANON.yaml.

## Configuring from the Web App

Sync configuration can be managed from the Canon web app at **Settings → Sync**. The editor provides:

- **Repository selector** — each repo has its own configuration
- **Status mapping editor** — visual forward/reverse status mapping
- **Field mapping editor** — standard and custom field mappings
- **Hierarchy editor** — depth-to-type mapping and auto-parent toggle
- **Routing rules editor** — match conditions and target/shadow target selection
- **Presets** — one-click starting configurations
- **Validation** — check your configuration for errors before applying
- **Config preview** — see the raw YAML that will be committed to CANON.yaml

Changes made in the web app are committed directly to your repository's CANON.yaml file via the Canon GitHub App.

For the full configuration reference, see the [CANON.yaml reference](/reference/config#ticket-systems).

## Adapter Architecture

Canon uses an adapter pattern to support multiple ticket systems:

```
┌──────────────────────────────────────────┐
│           Canon Core                │
│        (speaks "spec items")             │
├──────────────────────────────────────────┤
│       Ticket Adapter Interface           │
│                                          │
│  create_ticket(spec_item)                │
│  update_ticket(id, changes)              │
│  sync_status(id) → status                │
│  link_pr(ticket_id, pr_url)              │
│  close_ticket(id, evidence)              │
├────────┬────────┬────────┬───────┬───────┤
│  Jira  │ Linear │ GitHub │ Azure │  API  │
│Adapter │Adapter │Issues  │DevOps │ Proxy │
│        │        │Adapter │Adapter│Adapter│
└────────┘────────┘────────┘───────┘───────┘
                                       │
                              Canon Server
                              (GitHub App token)
```

The **API Proxy Adapter** is used by the CLI when you're logged in. Instead of calling GitHub directly, it routes requests through the Canon server, which uses its GitHub App installation token. This means developers don't need local `GITHUB_TOKEN` — just `canon login`.

The top-level `ticket_system` and `project_key` fields provide simple single-system configuration. For multi-system routing, use the `ticket_systems` and `routing` blocks instead. See the [configuration reference](/reference/config#sync) for the mapping between simple and advanced fields.
