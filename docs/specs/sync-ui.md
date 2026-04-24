---
title: "Sync UI"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-04-23
updated: 2026-04-23
tags: [sync, ui, ticket-mapping, dashboard, enterprise]
---

# Sync UI

Add a web-based management interface for ticket mapping and sync operations. Today, sync configuration lives exclusively in CANON.yaml with no visibility into sync runs, errors, or mapping correctness. This spec introduces a sync dashboard, mapping configuration editor, and persistent sync history so teams can monitor, debug, and configure ticket sync from the browser.

## 1. Sync Dashboard

<!-- canon:system:1 status:draft -->

A dedicated `/app/:org/sync` page providing visibility into sync operations across all repos in an org.

### 1.1 Sync Overview Page

<!-- canon:section:1.1 status:draft -->

Top-level sync dashboard showing aggregate sync health and recent activity.

**Layout:**
- Header with org-level sync stats: total synced specs, total tickets created, active errors
- Filter bar: repo selector, date range, system filter (Jira/Linear/GitHub), status filter
- Sync runs table: paginated list of recent sync operations

**Sync Run Row:**
| Column | Source |
|--------|--------|
| Repo | `sync_runs.repo` |
| Spec | spec title from sync context |
| System | target ticket system |
| Direction | forward / reverse |
| Result | created / updated / closed / errors counts |
| Triggered by | cron / manual / webhook / PR merge |
| Timestamp | `sync_runs.started_at` |
| Duration | `ended_at - started_at` |

**Acceptance Criteria:**

- [ ] New `SyncView.vue` renders at `/app/:org/sync` with navigation entry (icon: `ArrowLeftRight` or `RefreshCw`)
- [ ] Dashboard header shows aggregate stats loaded from `GET /app/:org/api/sync/stats`
- [ ] Sync runs table loads paginated data from `GET /app/:org/api/sync/runs` with cursor-based pagination
- [ ] Filter bar supports repo, system, direction, and date range filters passed as query params
- [ ] Empty state shown when no sync history exists ("No sync runs yet — connect a ticket system in Settings")
- [ ] Clicking a sync run row expands or navigates to sync run detail (section 1.2)

---

### 1.2 Sync Run Detail

<!-- canon:section:1.2 status:draft -->

Expanded view of a single sync run showing all operations performed.

**Layout:**
- Summary header: repo, spec, system, direction, trigger, timing, overall status (success / partial / failed)
- Operations list grouped by type: Created, Updated, Status Changed, Closed, Reopened, Skipped, Errors
- Each operation shows: section title, ticket ID (linked), operation detail, timestamp

**Error Display:**
- Error entries show: section title, adapter method, error message, stack trace (collapsible)
- Retry button for individual failed operations (creates a new targeted sync run)

**Acceptance Criteria:**

- [ ] Sync run detail view loads from `GET /app/:org/api/sync/runs/:run_id`
- [ ] Operations grouped by type with count badges (e.g., "Created (5)", "Errors (2)")
- [ ] Ticket IDs link to the external ticket system URL
- [ ] Error entries show adapter error messages with collapsible stack traces
- [ ] Retry button on error entries triggers `POST /app/:org/api/sync/retry` for the failed section

---

### 1.3 Per-Spec Sync Status

<!-- canon:section:1.3 status:draft -->

Within the existing spec detail view (`SpecView.vue`), add a sync status panel showing the sync state of each section.

**Layout:**
- Sync status badge on spec header: "Synced to Jira (PAY)", "Not synced", "Sync errors (3)"
- Section-level sync indicators: ticket link, last sync time, sync status (synced / pending / error)
- Quick action: "Sync now" button to trigger forward sync for this spec

**Acceptance Criteria:**

- [ ] Spec detail view shows sync status badge in header area
- [ ] Each spec section shows its linked ticket (if any) with external link
- [ ] "Sync now" button triggers `POST /app/:org/api/sync/trigger` for the specific spec
- [ ] Sync status data loaded from `GET /app/:org/api/sync/specs/:owner/:repo/:spec_path`

---

### 1.4 Manual Sync Trigger

<!-- canon:section:1.4 status:draft -->

Allow users to manually trigger sync operations from the UI.

**Acceptance Criteria:**

- [ ] `POST /app/:org/api/sync/trigger` accepts `{ repo, spec_path?, direction: "forward" | "reverse" | "both" }`
- [ ] Sync runs in background (using `BackgroundTasks` or `waitUntil`), returns `{ run_id }` immediately
- [ ] UI shows toast notification: "Sync started" with link to sync run detail
- [ ] Rate limited: max 1 manual sync per repo per minute
- [ ] Requires `specs:write` permission

---

## 2. Sync History Persistence

<!-- canon:system:2 status:draft -->

Persist sync operations to the database so they can be queried, displayed, and audited.

### 2.1 Sync Run Storage

<!-- canon:section:2.1 status:draft -->

New database tables and store for sync history.

**`sync_runs` table:**

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| org_login | VARCHAR(255) | Org that owns the repo |
| repo | VARCHAR(512) | `owner/repo` |
| spec_path | VARCHAR(1024) | Relative path to spec file (nullable for repo-level syncs) |
| system | VARCHAR(50) | Target ticket system (jira/linear/github) |
| direction | VARCHAR(20) | forward / reverse |
| trigger | VARCHAR(50) | cron / manual / webhook / pr_merge |
| status | VARCHAR(20) | running / success / partial / failed |
| created_count | INT | Tickets created |
| updated_count | INT | Tickets updated |
| closed_count | INT | Tickets closed |
| reopened_count | INT | Tickets reopened |
| skipped_count | INT | Sections skipped |
| error_count | INT | Errors encountered |
| started_at | TIMESTAMPTZ | Run start time |
| ended_at | TIMESTAMPTZ | Run end time (nullable while running) |
| triggered_by | VARCHAR(255) | User ID or "system" for cron |
| metadata | JSONB | Additional context (commit SHA, PR number, etc.) |

**`sync_events` table:**

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| run_id | UUID | FK to sync_runs |
| event_type | VARCHAR(30) | created / updated / status_changed / closed / reopened / skipped / error |
| section_title | VARCHAR(500) | Spec section title |
| section_number | VARCHAR(50) | Section number (e.g., "2.3") |
| ticket_id | VARCHAR(255) | External ticket ID (nullable for errors) |
| ticket_url | VARCHAR(1024) | External ticket URL (nullable) |
| detail | JSONB | Event-specific detail (error message, old/new status, fields changed) |
| created_at | TIMESTAMPTZ | Event timestamp |

**Indexes:**
- `sync_runs`: (org_login, started_at DESC), (org_login, repo, started_at DESC), (status)
- `sync_events`: (run_id, event_type), (ticket_id)

**Acceptance Criteria:**

- [ ] Migration creates `sync_runs` and `sync_events` tables with indexes
- [ ] `SyncHistoryStore` class with methods: `create_run`, `complete_run`, `add_event`, `add_events_batch`, `get_run`, `list_runs` (paginated), `get_run_events`, `get_stats`, `get_spec_sync_status`
- [ ] `list_runs` supports filtering by repo, system, direction, status, date range with cursor pagination
- [ ] `get_stats` returns aggregate counts for the dashboard header
- [ ] Old sync runs auto-cleaned after 90 days (configurable via `SYNC_HISTORY_RETENTION_DAYS`)

---

### 2.2 Sync Engine Integration

<!-- canon:section:2.2 status:draft -->

Wire the sync engine to persist results to the new store.

**Acceptance Criteria:**

- [ ] `forward_sync()` and `reverse_sync()` accept an optional `SyncHistoryStore` parameter
- [ ] When store is provided, a `sync_run` record is created at start and completed at end
- [ ] Each `SyncCreated`, `SyncUpdated`, `SyncClosed`, `SyncReopened`, `SyncSkipped`, `SyncError` is persisted as a `sync_event`
- [ ] Events are batch-inserted at end of sync (not one-at-a-time) for performance
- [ ] Cron jobs (`sync_status.py`) pass the store when invoking sync
- [ ] Manual sync trigger (section 1.4) passes the store
- [ ] Existing sync behavior is unchanged when store is not provided (backward compatible)

---

## 3. Mapping Configuration UI

<!-- canon:system:3 status:draft -->

Visual editor for ticket mapping configuration, generating CANON.yaml snippets that users can copy or apply.

### 3.1 Mapping Config Page

<!-- canon:section:3.1 status:draft -->

New settings tab or standalone page for viewing and editing ticket mapping configuration per repo.

**Location:** `/app/:org/settings/sync` (new tab in existing Settings layout) or accessible from sync dashboard per-repo.

**Layout:**
- Repo selector dropdown (repos with CANON.yaml containing ticket config)
- Current config display: parsed CANON.yaml ticket mapping config rendered as structured cards
- Edit mode toggle: switch from read-only view to editor

**Acceptance Criteria:**

- [ ] New route `/app/:org/settings/sync` with tab in `SettingsView.vue`
- [ ] Repo selector loads repos that have ticket system configuration
- [ ] Current mapping config loaded from `GET /app/:org/api/sync/config/:owner/:repo`
- [ ] Config displayed as structured cards (not raw YAML) showing systems, status maps, field maps, routing

---

### 3.2 Status Map Editor

<!-- canon:section:3.2 status:draft -->

Visual editor for bidirectional status mapping between spec states and ticket system statuses.

**Layout:**
- Two-column table: Spec State (left) → Ticket Status (right) for forward mapping
- Reverse mapping section: Ticket Status → Spec State
- Preset selector: load common presets ("Standard Jira", "Agile Board", "Product-Led")
- Validation: warns if any spec state is unmapped, highlights duplicates

**Acceptance Criteria:**

- [ ] Forward map editor shows all 6 spec states (draft, todo, in_progress, done, blocked, deprecated) with editable ticket status fields
- [ ] Reverse map editor allows adding arbitrary ticket_status → spec_state rows
- [ ] Preset dropdown loads predefined status map configurations
- [ ] Validation warnings shown inline (unmapped states, duplicate targets)
- [ ] Changes produce a YAML snippet shown in a preview panel
- [ ] "Apply" saves changes via `PUT /app/:org/api/sync/config/:owner/:repo`

---

### 3.3 Field Mapping Editor

<!-- canon:section:3.3 status:draft -->

Visual editor for standard and custom field mappings.

**Layout:**
- Standard fields table: ticket field name → spec source path (dropdown with valid sources)
- Custom fields section: custom field ID → source path or literal value
- Source path picker: dropdown showing `frontmatter.*` and `section.*` options with descriptions
- "Add field" button for new mappings

**Valid source paths** (populated from `FieldMapConfig` schema):
- `frontmatter.title`, `frontmatter.status`, `frontmatter.owner`, `frontmatter.team`, `frontmatter.tags`, `frontmatter.doc_type`, `frontmatter.depends_on`
- `section.title`, `section.section_number`, `section.content`, `section.acceptance_criteria`, `section.depth`, `section.id`
- `literal:<value>` for static values

**Acceptance Criteria:**

- [ ] Standard field mapping shown as editable table with source path dropdown
- [ ] Custom field section allows adding field_id → source pairs
- [ ] `literal:` prefix option available for static values
- [ ] Source path dropdown shows descriptions of each available path
- [ ] Validation: warns on invalid source paths, empty field IDs
- [ ] Changes reflected in YAML preview

---

### 3.4 Hierarchy & Template Editor

<!-- canon:section:3.4 status:draft -->

Editors for hierarchy configuration and summary/description templates.

**Hierarchy Editor:**
- Depth-to-type mapping table: depth number → issue type string
- Auto-parent toggle
- Default type input

**Template Editor:**
- Summary template input with Mustache variable autocomplete (`{{spec.title}}`, `{{section.title}}`, etc.)
- Description template textarea with live preview showing rendered output for a sample section
- Variable reference panel listing available template variables

**Acceptance Criteria:**

- [ ] Hierarchy depth-to-type editor with add/remove rows and issue type input
- [ ] Auto-parent checkbox and default type input
- [ ] Summary template input with Mustache variable insertion
- [ ] Description template textarea with live preview using sample spec data
- [ ] Template variable reference panel shown alongside editor
- [ ] Changes reflected in YAML preview

---

### 3.5 Routing Rules Editor

<!-- canon:section:3.5 status:draft -->

Visual editor for routing rules that direct specs to different ticket systems.

**Layout:**
- Rules list with drag-to-reorder (order determines priority)
- Each rule: match criteria (tags, team, owner, path glob) → target system + optional shadow targets
- "Default" rule indicator (match: {default: true})
- "Add rule" creates a new routing rule
- Validation: ensures at least one default rule, all targets reference defined systems

**Acceptance Criteria:**

- [ ] Routing rules displayed as ordered cards with match criteria and target system
- [ ] Match criteria editor supports tags (multi-select), team (text), owner (text), path (glob input)
- [ ] Default rule clearly indicated and cannot be deleted if it's the only rule
- [ ] Target and shadow target dropdowns populated from defined ticket systems
- [ ] Drag-to-reorder changes rule priority
- [ ] Validation ensures all targets reference defined systems
- [ ] Changes reflected in YAML preview

---

### 3.6 Config API Endpoints

<!-- canon:section:3.6 status:draft -->

Backend API endpoints for reading and writing ticket mapping configuration.

**Acceptance Criteria:**

- [ ] `GET /app/:org/api/sync/config/:owner/:repo` returns parsed `TicketMappingConfig` as JSON
- [ ] `PUT /app/:org/api/sync/config/:owner/:repo` accepts JSON config, validates, and writes to CANON.yaml via GitHub commit
- [ ] `POST /app/:org/api/sync/config/:owner/:repo/validate` validates config without saving, returns errors/warnings
- [ ] `GET /app/:org/api/sync/config/:owner/:repo/presets` returns available status map presets
- [ ] Config write requires `specs:write` permission and creates a commit with message "chore: update ticket mapping config"
- [ ] Config read returns both effective config (with org defaults merged) and repo-level overrides separately

---

## 4. Sync API Routes

<!-- canon:system:4 status:draft -->

New FastAPI router for sync management endpoints.

### 4.1 Sync Management Router

<!-- canon:section:4.1 status:draft -->

New `sync_routes.py` mounted at `/app/{org}/api/sync`.

**Endpoints:**

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/stats` | specs:read | Aggregate sync stats for org |
| GET | `/runs` | specs:read | Paginated sync run history |
| GET | `/runs/:run_id` | specs:read | Single sync run with events |
| POST | `/trigger` | specs:write | Manual sync trigger |
| POST | `/retry` | specs:write | Retry failed sync events |
| GET | `/specs/:owner/:repo/:path` | specs:read | Per-spec sync status |
| GET | `/config/:owner/:repo` | specs:read | Read mapping config |
| PUT | `/config/:owner/:repo` | specs:write | Update mapping config |
| POST | `/config/:owner/:repo/validate` | specs:read | Validate config |
| GET | `/config/:owner/:repo/presets` | specs:read | Status map presets |

**Acceptance Criteria:**

- [ ] New `sync_routes.py` with `sync_router` APIRouter
- [ ] Router mounted in `main.py` with prefix pattern matching existing routes
- [ ] All endpoints require authentication and org membership
- [ ] Permission checks match the table above
- [ ] Rate limiting on `/trigger` and `/retry` (1/min/repo)
- [ ] Consistent error response format matching existing API patterns
- [ ] Pagination uses cursor-based approach consistent with other list endpoints

---

## 5. Navigation & Layout Integration

<!-- canon:system:5 status:draft -->

### 5.1 Navigation Updates

<!-- canon:section:5.1 status:draft -->

Add sync pages to the app navigation and integrate with existing views.

**Acceptance Criteria:**

- [ ] "Sync" nav item added to `AppNav.vue` between Tasks and Settings (icon: `RefreshCw` from lucide)
- [ ] Sync settings tab added to `SettingsView.vue` tab list
- [ ] Spec detail view (`SpecView.vue`) shows sync status badge and "Sync now" action
- [ ] Repo detail view (`RepoView.vue`) shows sync summary (last run, error count) with link to filtered sync dashboard
- [ ] Breadcrumb navigation works: Sync → Run Detail, Settings → Sync Config
