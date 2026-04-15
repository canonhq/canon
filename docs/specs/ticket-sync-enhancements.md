---
title: "Ticket Sync Enhancements"
status: in_progress
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-03-04
tags: [sync, asana, webhooks, real-time]
---

# Ticket Sync Enhancements

Extend the ticket sync engine with an Asana adapter and real-time reverse sync via webhooks, replacing the cron-based polling approach.

## 1. Background

<!-- canon:system:1 status:todo -->

The ticket sync engine currently supports Jira, Linear, and GitHub Issues via an adapter pattern. Two gaps exist: Asana is not supported (teams using Asana can't use Canon's ticket sync), and reverse sync (ticket → spec status updates) only runs via a daily cron job, meaning spec statuses can be up to 24 hours behind ticket reality.

**Related:** [#59](https://github.com/canonhq/canon/issues/59), [#56](https://github.com/canonhq/canon/issues/56)

<!-- canon:ticket:github:437 -->
## 2. Asana Ticket Adapter

<!-- canon:system:2 status:todo -->

Implement the `TicketAdapter` protocol for Asana, extending ticket sync to teams using Asana for project management.

### 2.1 Implementation

- Use Asana REST API v1 (Personal Access Token or OAuth2 for auth)
- Map spec sections to Asana tasks within a project
- Map spec statuses to Asana custom fields or sections (columns)
- Support Asana webhooks for reverse sync (§3)

### 2.2 Status Mapping

| Spec Status | Asana Equivalent |
|---|---|
| draft | Backlog section |
| todo | To Do section |
| in_progress | In Progress section |
| done | Complete section |
| blocked | Blocked (custom field) |
| deprecated | Archived |

### Acceptance Criteria

- [ ] `AsanaAdapter` implements the `TicketAdapter` protocol
- [ ] Forward sync: spec sections create/update Asana tasks
- [ ] Reverse sync: Asana task status changes update spec status
- [ ] Adapter authenticated via Personal Access Token or OAuth2
- [ ] Status mapping is configurable via `CANON.yaml` ticket mapping
- [ ] Adapter registered in the adapter factory (`from_config()`)
- [ ] Tests cover create, update, and status sync operations

## 3. Real-Time Reverse Sync via Webhooks

<!-- canon:system:3 status:done -->
<!-- section done: old ticket #56 closed -->

Replace the cron-based reverse sync with webhook-driven updates for near-real-time spec status tracking.

### 3.1 Webhook Endpoints

| Ticket System | Webhook Endpoint | Events |
|---|---|---|
| GitHub Issues | GitHub App webhook → `on_issues` handler | `issues.opened`, `issues.closed`, `issues.labeled` |
| Jira | `/webhooks/jira` | `jira:issue_updated` |
| Linear | `/webhooks/linear` | `Issue.update` |
| Asana | `/webhooks/asana` | Handshake + task status changes (event processing blocked on §2) |

### 3.2 Processing

1. Receive webhook event
2. Validate signature/authentication
3. Extract ticket ID and new status
4. Look up linked spec section via ticket link comment
5. Update spec section status via GitHub API (commit to repo)
6. Emit audit event

### 3.3 Reliability

- Idempotent processing (same event processed twice = same result)
- Webhook secret verification for each ticket system
- Dead letter queue for failed processing (log + retry)
- Cron job retained as fallback/catch-up mechanism

### Acceptance Criteria

- [x] Webhook endpoints for GitHub Issues, Jira, Linear, and Asana
<!-- canon:realized-in:PR#295 file:src/specwright/webhooks/router.py -->
<!-- canon:realized-in:PR#295 file:src/specwright/github/handlers/on_issues.py -->
<!-- canon:realized-in:PR#312 file:src/specwright/webhooks/router.py -->
<!-- canon:realized-in:PR#312 file:src/specwright/github/handlers/on_issues.py -->
<!-- canon:realized-in:PR#497 file:src/canon/sync/adapters/jira.py -->
- [x] Webhook signature/authentication verification for each system
<!-- canon:realized-in:PR#295 file:src/specwright/webhooks/verify.py -->
<!-- canon:realized-in:PR#312 file:src/specwright/webhooks/verify.py -->
- [x] Ticket status changes trigger immediate spec status updates
<!-- canon:realized-in:PR#295 file:src/specwright/webhooks/processor.py -->
<!-- canon:realized-in:PR#295 file:src/specwright/webhooks/router.py -->
<!-- canon:realized-in:PR#312 file:src/specwright/webhooks/processor.py -->
- [x] Processing is idempotent (duplicate events are safe)
<!-- canon:realized-in:PR#295 file:src/specwright/webhooks/processor.py -->
- [x] Failed webhook processing is logged and retryable
<!-- canon:realized-in:PR#295 file:src/specwright/webhooks/router.py -->
- [x] Cron job retained as catch-up mechanism (not removed)
<!-- canon:realized-in:PR#312 file:src/specwright/cron/sync_status.py -->
<!-- canon:realized-in file:src/specwright/cron/sync_status.py -->
- [x] Latency from ticket change to spec update is under 30 seconds
<!-- canon:realized-in:PR#295 file:src/specwright/webhooks/router.py -->

## 4. Resolved Questions

- **Webhook hosting:** Same FastAPI app via `APIRouter(prefix="/webhooks")`, mounted in `main.py`
- **Retry policy:** Infrastructure errors return HTTP 500 (triggering sender retry); business outcomes return HTTP 200 to prevent retry storms
- **Asana auth:** PAT for v1; OAuth2 deferred
