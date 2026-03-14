---
title: "Slack Bot for Spec Queries"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-02-26
tags: [slack, bot, integrations]
---

# Slack Bot for Spec Queries

Build a Slack bot using Bolt SDK that answers natural language questions about specs and codebase, bringing spec context into the team's communication flow.

## 1. Background

<!-- specwright:system:1 status:done -->

Engineers and PMs currently need to navigate GitHub repos or the Spec Explorer web app to find spec information. A Slack bot enables quick spec queries in the team's existing communication flow — "what's the status of auth hardening?" or "which specs are blocked?" — without context-switching.

**Related:** [#5](https://github.com/canonhq/canon/issues/5)

## 2. Slack App Setup

<!-- specwright:system:2 status:todo -->
<!-- specwright:ticket:github:5 -->

### 2.1 Configuration

- Slack app with bot token and slash commands
- `/canon` slash command for structured queries
- `@canon` mention handler for natural language questions
- Bot token scopes: `chat:write`, `commands`, `app_mentions:read`

### Acceptance Criteria

- [ ] Slack app created with bot token and required scopes
- [ ] `/canon` slash command registered and responding
- [ ] `@canon` mention handler processing natural language queries
- [ ] Bot deployed alongside the main Canon application

## 3. Query Capabilities

<!-- specwright:system:3 status:todo -->
<!-- specwright:ticket:github:5 -->

### 3.1 Structured Commands

| Command | Description |
|---|---|
| `/canon status <spec-name>` | Show spec status, progress, and blockers |
| `/canon list [--status draft\|active]` | List specs filtered by status |
| `/canon search <query>` | Search specs by keyword |
| `/canon coverage [repo]` | Show spec coverage metrics |

### 3.2 Natural Language Queries

Route `@canon` mentions to Claude with spec + code context. Examples:
- "What's the status of the auth hardening work?"
- "Which specs have open questions?"
- "What are the acceptance criteria for ticket sync?"

### Acceptance Criteria

- [ ] Structured commands return formatted Slack messages with spec data
- [ ] Natural language queries route to Claude with relevant spec context
- [ ] Responses use Slack Block Kit for rich formatting (sections, buttons, links)
- [ ] Queries scope to the workspace's connected GitHub org
- [ ] Response time under 5 seconds for structured commands, under 15 seconds for NL queries

## 4. Notifications

<!-- specwright:system:4 status:draft -->

Optional: push spec status changes to configured Slack channels.

- Spec status transitions (draft → approved, etc.)
- New spec created
- Spec coverage drops below threshold
- Configurable via `CANON.yaml` `slack_channel` field

### Acceptance Criteria

- [ ] Spec status change notifications posted to configured channel
- [ ] Notifications are configurable (opt-in per event type)
- [ ] Notification format includes spec title, old/new status, and link

## 5. Open Questions

- Should the bot be a standalone service or integrated into the existing FastAPI app?
- What's the authentication model? (Slack OAuth install flow, or manual token config?)
- Should the bot support multi-workspace installations?
