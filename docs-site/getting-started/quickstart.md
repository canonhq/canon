# Quickstart: Your First Spec in 5 Minutes

Write a spec, run Canon's tools against it, and see the feedback loop — all locally, no server or GitHub App needed.

## Prerequisites

- Canon CLI installed (`pip install canonhq` — see [Installation](./installation))
- A git repository (any repo works)

## Step 1: Initialize Canon

```bash
cd your-repo
canon setup
```

This creates `CANON.yaml` and a spec template at `docs/specs/_template.md`.

## Step 2: Write a Spec

Create `docs/specs/user-notifications.md`:

```markdown
---
title: "User Notifications"
status: draft
owner: your-name
team: product
created: 2026-01-15
updated: 2026-01-15
tags: [notifications, mvp]
---

# User Notifications

Add email and in-app notifications for key user events.

## 1. Background

Our users have no way to know when important events happen
(new comments, status changes, approvals) without manually
checking the app.

## 2. Email Notifications

<!-- canon:system:2 status:todo -->

Send email notifications for high-priority events.

### Acceptance Criteria

- [ ] Email sent on new comment mentioning the user
- [ ] Email sent on spec status change (draft → in_progress)
- [ ] Unsubscribe link in every email
- [ ] Rate limit: max 10 emails per user per hour

## 3. In-App Notifications

<!-- canon:system:3 status:todo -->

Show a notification bell with unread count in the app header.

### Acceptance Criteria

- [ ] Notification bell shows unread count
- [ ] Click opens notification drawer
- [ ] Mark individual or all as read
- [ ] Notifications persist for 30 days
```

## Step 3: Check Your Spec

Run the spec dashboard:

```bash
canon status
```

You'll see something like:

```
Spec Coverage Dashboard
═══════════════════════

user-notifications.md
  §1 Background           — (no status)
  §2 Email Notifications  — todo  (0/4 ACs checked)
  §3 In-App Notifications — todo  (0/4 ACs checked)

Overall: 0% realized
```

## Step 4: Lint It

```bash
canon lint
```

Canon validates frontmatter, section numbering, AC format, and status comment syntax. Fix any warnings it reports.

## Step 5: See Your Tasks

```bash
canon tasks
```

```
Tasks (from specs)
══════════════════

user-notifications.md
  §2 Email Notifications  [todo]
    - [ ] Email sent on new comment mentioning the user
    - [ ] Email sent on spec status change (draft → in_progress)
    - [ ] Unsubscribe link in every email
    - [ ] Rate limit: max 10 emails per user per hour

  §3 In-App Notifications  [todo]
    - [ ] Notification bell shows unread count
    - [ ] Click opens notification drawer
    - [ ] Mark individual or all as read
    - [ ] Notifications persist for 30 days
```

## Step 6: Start Work and Track Progress

Mark a section as in-progress:

```bash
canon start 2
```

The spec file updates with `status:in_progress`. Implement the feature, then mark it done:

```bash
canon done 2
```

## Step 7: Verify Against Code

After implementing, run verification to check which ACs have evidence in your codebase:

```bash
canon verify
```

Canon greps your source for keywords from each AC and reports which ones appear implemented vs. not started.

## Step 8: Sync to Tickets (Optional)

If you use GitHub Issues, Jira, or Linear, sync your spec sections into tickets. First, make sure your spec has a `ticket_project` in the frontmatter (or set `project_key` in `CANON.yaml`):

```bash
# Preview what would be created
canon sync --dry-run

# Create the tickets
canon sync
```

Each spec section becomes a ticket. To pull ticket status changes back into the spec, run `canon sync --reverse`.

## What's Next?

You've seen the core loop: **write spec → track status → verify code → sync tickets**.

From here, layer on more automation:

- **[GitHub App](./installation#github-app)** — automated PR analysis with spec realization comments
- **[GitHub Actions](/guides/github-actions/)** — CI checks for spec lint, coverage, and sync
- **[Claude Code Plugin](./installation#claude-code-plugin)** — spec-driven slash commands in your editor
- **[Writing Specs](/guides/writing-specs)** — spec authoring best practices
- **[Configuration](./configuration)** — customize ticket sync, routing, and agent behavior
- **[Concepts](/concepts/)** — understand living specs, delta tracking, and the coverage model
