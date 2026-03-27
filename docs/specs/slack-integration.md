---
title: "Slack App for Canon"
status: in_progress
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-03-25
tags: [slack, bot, integrations, enterprise]
---

# Slack App for Canon

A full-featured Slack app that brings spec context, workflow actions, and proactive insights into the team's communication flow. Built on Slack's Bolt SDK (Python), integrated into the existing FastAPI application.

## 1. Background

<!-- canon:system:1 status:done -->

Engineers and PMs currently need to navigate GitHub repos or the Spec Explorer web app to find spec information. A Slack app enables quick spec queries in the team's existing communication flow — "what's the status of auth hardening?" or "which specs are blocked?" — without context-switching.

The existing `SlackAlerter` (outbound webhooks) handles SRE alerts and weekly digests. This spec extends Canon's Slack presence into a **bidirectional, interactive app** that can receive commands, respond to mentions, and surface actionable insights.

**Related:** [#5](https://github.com/canonhq/canon/issues/5)

## 2. Slack App Setup & Architecture

<!-- canon:system:2 status:done -->

### 2.1 App Configuration

- Slack App created via [api.slack.com/apps](https://api.slack.com/apps) with bot token
- **Bot token scopes**: `chat:write`, `commands`, `app_mentions:read`, `reactions:read`, `reactions:write`, `channels:read`, `groups:read`, `im:read`, `users:read`
- **Event subscriptions**: `app_mention`, `message.im` (DMs to bot)
- **Interactivity**: enabled for button/modal actions
- **Slash commands**: `/canon`

### 2.2 Deployment Mode

- **Production**: HTTP mode — Slack sends events to `POST /slack/events` on the existing FastAPI app. The Bolt `AsyncApp` is mounted as an ASGI sub-application via `SlackRequestHandler`.
- **Development**: Socket Mode — connects via WebSocket, no public URL required. Enabled when `SLACK_APP_TOKEN` (xapp-) is set.
- The app gracefully degrades: if `SLACK_BOT_TOKEN` is not configured, all Slack bot routes return 503 (same pattern as Linear/Jira webhooks).

### 2.3 Settings

New environment variables in `Settings`:

| Variable | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | Bot user OAuth token (xoxb-) |
| `SLACK_SIGNING_SECRET` | Request signature verification |
| `SLACK_APP_TOKEN` | Socket mode token (xapp-), optional |

### Acceptance Criteria

- [ ] Slack app created with bot token and all required scopes listed in 2.1
- [ ] Bolt `AsyncApp` mounted on FastAPI at `/slack/events` using `SlackRequestHandler`
- [ ] Socket Mode activated when `SLACK_APP_TOKEN` is set, HTTP mode otherwise
- [ ] App returns 503 on `/slack/events` when `SLACK_BOT_TOKEN` is not configured
- [ ] `SLACK_SIGNING_SECRET` used to verify all incoming Slack requests in HTTP mode
- [ ] Settings added to `Settings` class with `slack_bot_token`, `slack_signing_secret`, `slack_app_token` fields
- [ ] `slack_bot_enabled` property returns True when bot token and signing secret are both set

## 3. Slash Command: `/canon`

<!-- canon:system:3 status:in_progress -->

The `/canon` slash command provides structured access to spec data.

### 3.1 Command Routing

`/canon <subcommand> [args]` — dispatched by the first argument:

| Command | Description | Example |
|---|---|---|
| `/canon status <spec>` | Spec status, progress %, and blockers | `/canon status auth-hardening` |
| `/canon list [--status <s>]` | List specs filtered by status | `/canon list --status active` |
| `/canon search <query>` | Full-text search across specs | `/canon search ticket sync` |
| `/canon coverage [team]` | Spec coverage metrics, optionally by team | `/canon coverage platform` |
| `/canon dashboard` | Post a rich coverage summary to the channel | `/canon dashboard` |
| `/canon review <spec>` | Request a spec review from the team | `/canon review auth-hardening` |
| `/canon help` | List available commands | `/canon help` |

### 3.2 Response Formatting

All responses use Slack Block Kit:

- **Status**: Header block with spec title + status badge, section blocks for each spec section showing AC progress (checkmarks), context block with last-updated timestamp and GitHub link.
- **List**: Section blocks per spec with status emoji, overflow menu for actions (view, review). Max 10 results, with "View all in Canon" button if more.
- **Search**: Similar to list, but with matched snippet context. Powered by existing spec parser keyword matching.
- **Coverage**: Stats section (total specs, % done, % in-progress), divider, per-team breakdown if teams exist. Uses number formatting with bar chart emoji (e.g., `[########--] 80%`).
- **Dashboard**: A multi-block summary posted as a **visible message in the channel** (not ephemeral), pinnable. Includes: health score (from analytics), coverage by team, recently updated specs, stale specs.

### 3.3 Error Handling

- Unknown subcommand: ephemeral message with available commands
- Spec not found: ephemeral message suggesting similar spec names (fuzzy match)
- Unauthorized org: ephemeral error explaining the workspace isn't connected
- All slash command responses are **ephemeral** by default (only visible to the invoker) except `/canon dashboard` which posts to the channel

### Acceptance Criteria

- [ ] `/canon` slash command registered and dispatching to subcommand handlers
- [ ] `status` subcommand returns spec details with section-level AC progress
- [ ] `list` subcommand returns filtered spec list with status badges, max 10 results
- [ ] `search` subcommand returns keyword-matched specs with snippet context
- [ ] `coverage` subcommand returns coverage metrics with optional team filter
- [ ] `dashboard` subcommand posts a visible, pinnable coverage summary to the channel
- [ ] `review` subcommand creates a review request message with approve/reject buttons
- [ ] `help` subcommand lists all available commands with descriptions
- [ ] Unknown subcommands return an ephemeral help message
- [ ] Spec-not-found errors suggest similar spec names via fuzzy matching
- [ ] All responses except `dashboard` are ephemeral
- [ ] Response time under 3 seconds for all structured commands (Slack's 3s timeout for slash commands; use `ack()` + deferred response for slower queries)

## 4. Natural Language Queries via @canon

<!-- canon:system:4 status:in_progress -->

### 4.1 Mention Handler

When `@canon` is mentioned in a channel or thread, the bot:

1. Extracts the message text (stripping the mention)
2. Resolves the workspace's connected GitHub org (from installation registry)
3. Loads relevant specs based on keyword extraction from the query
4. Sends the query + spec context to Claude via the existing `agent.client`
5. Posts the response in-thread (or creates a new thread if mentioned in a top-level message)

### 4.2 Context Window

The agent receives:
- The user's question
- Up to 5 most-relevant specs (by keyword match against query)
- Current coverage summary for the org
- The thread history (if responding in a thread, up to 10 previous messages for multi-turn context)

### 4.3 Thread Conversations

The bot **continues conversations in threads**:
- If `@canon` is mentioned in a thread, it reads thread history for multi-turn context
- Follow-up messages in the same thread that mention `@canon` maintain conversation state
- The bot adds a reaction (eyes emoji) when processing, replaced with checkmark on completion

### 4.4 DM Support

Users can DM the bot directly without `@canon` — all DMs are treated as natural language queries. Same context resolution applies.

### 4.5 Rate Limiting

- Per-user rate limit: 10 NL queries per minute (slash commands exempt)
- Rate-limited users receive an ephemeral message explaining the limit
- Rate limit state is in-memory (per-process), reset on restart

### Acceptance Criteria

- [ ] `@canon` mentions in channels route to Claude with spec context
- [ ] Bot responds in-thread, creating a new thread if mentioned top-level
- [ ] Thread history (up to 10 messages) included for multi-turn conversations
- [ ] DMs to the bot are handled as NL queries without requiring mention
- [ ] Eyes emoji reaction added on processing start, replaced with checkmark on completion
- [ ] Up to 5 relevant specs loaded as context based on query keyword matching
- [ ] Response time under 15 seconds for NL queries (deferred response via `respond()`)
- [ ] Per-user rate limit of 10 NL queries/minute with clear feedback on limit hit
- [ ] Errors from Claude API surface as a user-friendly "I couldn't answer that" message

## 5. Proactive Notifications

<!-- canon:system:5 status:in_progress -->

### 5.1 Event Types

Canon posts proactive notifications to configured Slack channels. Each event type can be independently enabled/disabled via `CANON.yaml`.

| Event | Channel Config | Description |
|---|---|---|
| `spec_status_change` | `slack_channel` | Spec transitions (draft -> active, etc.) with old/new status, author |
| `spec_created` | `slack_channel` | New spec added to repo with title, owner, and link |
| `coverage_regression` | `sre.alerts_channel` | Spec coverage drops below threshold (configurable, default 80%) |
| `stale_spec_warning` | `slack_channel` | Spec hasn't been updated in N days (from stale detection cron) |
| `pr_analysis_summary` | `slack_channel` | After PR analysis completes: specs affected, ACs realized, coverage delta |
| `ticket_sync_failure` | `sre.alerts_channel` | Ticket sync failed (Jira/Linear/GitHub API error) |
| `review_requested` | `slack_channel` | Someone requested a spec review via `/canon review` |

### 5.2 Notification Format

All notifications use Block Kit with consistent structure:

```
[emoji] *Event Title*
Brief description of what happened.
*Spec:* <link|spec-name> | *By:* @author | *Time:* timestamp
[View in Canon] [View on GitHub]
```

### 5.3 Channel Resolution

Notification target channel is resolved in order:
1. Spec-level `slack_channel` frontmatter override (per-spec targeting)
2. `CANON.yaml` `slack_channel` (repo-level default)
3. SRE-specific events use `sre.alerts_channel`
4. If no channel configured, notification is silently skipped (not an error)

### 5.4 Notification Preferences

New `CANON.yaml` section:

```yaml
slack:
  channel: "#specs"                    # Default notification channel
  notifications:
    spec_status_change: true           # Default: true
    spec_created: true                 # Default: true
    coverage_regression: true          # Default: true
    stale_spec_warning: true           # Default: true
    pr_analysis_summary: true          # Default: true
    ticket_sync_failure: true          # Default: true
    review_requested: true             # Default: true
  coverage_threshold: 80              # % below which coverage_regression fires
  quiet_hours:                        # Suppress non-critical notifications
    start: "22:00"                    # UTC
    end: "08:00"                      # UTC
```

### Acceptance Criteria

- [ ] Spec status change notifications posted with old/new status and GitHub link
- [ ] New spec notifications posted with title, owner, and link
- [ ] Coverage regression alerts fire when coverage drops below configurable threshold
- [ ] Stale spec warnings posted when stale detection cron finds overdue specs
- [ ] PR analysis summaries posted after agent completes PR review
- [ ] Ticket sync failure alerts posted to SRE alerts channel
- [ ] Each notification type independently configurable in `CANON.yaml` `slack.notifications`
- [ ] Channel resolution follows priority: spec frontmatter > CANON.yaml > SRE channel
- [ ] Missing channel config results in silent skip, not an error
- [ ] Quiet hours suppress non-critical notifications (coverage regression and ticket sync failure are always delivered)
- [ ] Notifications include actionable buttons (View in Canon, View on GitHub)

## 6. Workflow Actions from Slack

<!-- canon:system:6 status:in_progress -->

### 6.1 Button Actions

Notification messages and query responses include interactive buttons:

| Action | Button Label | Behavior |
|---|---|---|
| View spec | "View in Canon" | Opens Spec Explorer link in browser |
| Approve spec | "Approve" | Transitions spec from `review` to `approved` status, posts confirmation |
| Request changes | "Request Changes" | Opens a modal for feedback, posts comment to spec PR |
| Trigger sync | "Sync Tickets" | Triggers ticket sync for the spec, posts result summary |
| Refresh | "Refresh" | Re-fetches and updates the message with current data |

### 6.2 Permission Model

Actions check permissions via the Slack user's linked identity:
- Map Slack user ID to GitHub login via the installation registry (or Auth0 email match)
- `Approve` and `Request Changes` require `specs:write` permission
- `Sync Tickets` requires `specs:admin` permission
- Unauthorized actions return an ephemeral "You don't have permission" message

### 6.3 Modals

The "Request Changes" action opens a Slack modal with:
- Spec name (read-only display)
- Feedback text area (required, max 3000 chars)
- Submit posts the feedback as a comment on the spec's GitHub PR

### Acceptance Criteria

- [ ] "View in Canon" button opens the correct Spec Explorer URL
- [ ] "Approve" button transitions spec status and posts confirmation in-thread
- [ ] "Request Changes" opens a modal with feedback text area
- [ ] Modal submission posts feedback as a GitHub PR comment via existing `GitHubClient`
- [ ] "Sync Tickets" triggers ticket sync and posts a result summary
- [ ] "Refresh" button re-fetches data and updates the original message
- [ ] Slack user ID mapped to GitHub login for permission checks
- [ ] Unauthorized actions return ephemeral "permission denied" message
- [ ] All button actions acknowledge within 3 seconds (Slack timeout)

## 7. Slack-Native Dashboards

<!-- canon:system:7 status:in_progress -->

### 7.1 Coverage Dashboard

`/canon dashboard` posts a rich, visible message to the channel:

```
:bar_chart: *Canon Spec Dashboard* — Acme Corp
_Updated: Mar 25, 2026 at 3:45 PM_

*Health Score:* 82/100 :large_green_circle:

*Coverage by Team:*
Platform  [########--] 80% (8/10)
Backend   [######----] 60% (6/10)
Frontend  [####------] 40% (2/5)

*Recently Updated:*
- :white_check_mark: auth-hardening — approved (2h ago)
- :large_blue_circle: ticket-sync — in progress (1d ago)
- :yellow_circle: slack-integration — draft (3d ago)

*Needs Attention:*
- :warning: api-v2-migration — stale (45d, threshold: 30d)
- :red_circle: billing-integration — blocked (missing Linear access)
```

### 7.2 Auto-Refresh

The dashboard message includes a "Refresh" button. Optionally, a scheduled update can be configured:
- `slack.dashboard_refresh`: `"daily"`, `"weekly"`, or `false` (default: `false`)
- When enabled, updates the pinned dashboard message in-place rather than posting a new one (uses `chat.update`)

### Acceptance Criteria

- [ ] `/canon dashboard` posts a multi-block coverage summary to the channel
- [ ] Dashboard includes health score, per-team coverage bars, recent updates, and attention items
- [ ] Dashboard message is visible (not ephemeral) and pinnable
- [ ] "Refresh" button updates the message in-place with current data
- [ ] Optional auto-refresh via `slack.dashboard_refresh` config (daily/weekly/false)
- [ ] Auto-refresh updates existing pinned message rather than posting new ones

## 8. Team Digest Channels

<!-- canon:system:8 status:in_progress -->

### 8.1 Per-Team Digests

Extend the existing weekly SRE digest to support per-team spec digests:

- Each team can configure a Slack channel for their digest
- Digest includes: specs owned by that team, their coverage changes, recently completed ACs, upcoming stale warnings
- Delivered weekly (configurable day/time in `CANON.yaml`)

### 8.2 Configuration

```yaml
slack:
  team_digests:
    platform:
      channel: "#platform-specs"
      schedule: "monday 09:00"          # UTC
    backend:
      channel: "#backend-specs"
      schedule: "monday 09:00"
```

### 8.3 Digest Format

```
:newspaper: *Weekly Spec Digest — Platform Team*
_Week of Mar 17–23, 2026_

*Coverage:* 80% (+5% from last week) :chart_with_upwards_trend:

*Completed This Week:*
- :white_check_mark: auth-hardening §3.2 — "Rate limiting on login endpoint"
- :white_check_mark: auth-hardening §3.3 — "JWT refresh token rotation"

*In Progress:*
- :large_blue_circle: api-v2-migration §2 — 3/7 ACs done

*Needs Attention:*
- :warning: data-export — approaching stale (25d, threshold: 30d)

*New Specs:*
- :new: observability-v2 — draft by @alice
```

### Acceptance Criteria

- [ ] Per-team digest configuration in `CANON.yaml` under `slack.team_digests`
- [ ] Digest filters specs by team ownership
- [ ] Digest includes coverage delta from previous week
- [ ] Digest lists completed ACs, in-progress sections, and stale warnings
- [ ] Digest delivered on configured schedule (day + time, UTC)
- [ ] Digest posted to team-specific Slack channel
- [ ] Teams without configuration are silently skipped

## 9. Multi-Workspace Support

<!-- canon:system:9 status:in_progress -->

### 9.1 Installation Flow

For managed cloud (multi-tenant), support Slack OAuth install flow:

- "Add to Slack" button on the Canon web app
- OAuth flow stores bot token per-workspace in the installation registry (DB)
- Each workspace linked to a Canon org via the install flow
- Tokens encrypted at rest using `BYOK_ENCRYPTION_KEY`

### 9.2 Self-Hosted Mode

For self-hosted deployments:
- Single workspace, manual token configuration via `SLACK_BOT_TOKEN`
- No OAuth flow needed
- Same feature set as managed cloud

### 9.3 Slack Connect

For enterprise customers sharing channels across orgs:
- Bot responds in shared channels if installed in either workspace
- Responses scoped to the org that owns the spec (no cross-org data leakage)
- Shared channels explicitly opted-in via `CANON.yaml` `slack.allow_shared_channels: true`

### Acceptance Criteria

- [ ] OAuth install flow stores bot tokens per-workspace in the installation registry
- [ ] Workspace linked to Canon org during install flow
- [ ] Bot tokens encrypted at rest using existing BYOK encryption
- [ ] Self-hosted mode works with manual `SLACK_BOT_TOKEN` config (no OAuth)
- [ ] Bot responds in Slack Connect shared channels when enabled
- [ ] Responses in shared channels scoped to the requesting org's data only
- [ ] `slack.allow_shared_channels` config controls shared channel behavior (default: false)

## 10. Implementation Notes

### 10.1 Dependencies

```
slack-bolt>=1.20.0       # Bolt SDK for Python (async)
slack-sdk>=3.30.0        # Underlying Slack API client
```

### 10.2 Module Structure

```
src/canon/slack/
  __init__.py
  app.py              # Bolt AsyncApp factory + FastAPI mount
  commands.py          # /canon slash command handlers
  mentions.py          # @canon mention + DM handler
  actions.py           # Button/modal interaction handlers
  notifications.py     # Proactive notification dispatch
  dashboard.py         # Dashboard block builder
  digest.py            # Per-team digest builder
  blocks.py            # Shared Block Kit builder utilities
  permissions.py       # Slack user -> Canon permission mapping
  install.py           # OAuth install flow (managed cloud only)
```

### 10.3 Migration Path

The existing `SlackAlerter` (webhook-based) continues to work for SRE alerts. When the Slack bot is enabled (`SLACK_BOT_TOKEN` set), notifications transition to using the bot's `chat.postMessage` API instead of webhooks. This provides:
- Richer formatting (Block Kit instead of plain text)
- Two-way interaction (buttons on alert messages)
- Unified bot identity in Slack

If only the webhook is configured (no bot token), the existing `SlackAlerter` behavior is preserved with zero changes.

### 10.4 Testing Strategy

- Unit tests: mock Slack API responses, test command parsing and block building
- Integration tests: use Slack's `SocketModeClient` test fixtures
- E2E: manual testing with a dedicated Slack workspace

## 11. Open Questions

- **Thread storage**: Should thread conversation history be persisted (DB) or in-memory only? Persisting enables better multi-turn but adds DB schema.
- **Slash command scope**: Should `/canon` be usable in DMs with the bot, or channels only?
- **Dashboard storage**: Where to store the message timestamp for auto-refresh updates? Installation registry or a new table?
- **Rate limit scope**: Should NL query rate limits be per-user-per-workspace, or global per-user?
