# Quickstart: Your First Spec in 5 Minutes

This tutorial walks you through creating a spec, getting it tracked by Canon, and seeing the feedback loop in action.

## Prerequisites

- A GitHub repository with Canon installed (see [Installation](./installation))
- A `CANON.yaml` in your repo root

## Step 1: Create a Spec File

Create `docs/specs/user-notifications.md`:

```markdown
---
title: "User Notifications"
status: draft
owner: your-name
team: product
ticket_project: PROJ
created: 2026-02-26
updated: 2026-02-26
tags: [notifications, mvp]
---

# User Notifications

Add email and in-app notifications for key user events.

## 1. Background

Our users have no way to know when important events happen
(new comments, status changes, approvals) without manually
checking the app. This leads to missed updates and slow
response times.

## 2. Email Notifications

<!-- canon:system:2 status:todo -->

Send email notifications for high-priority events.

### Acceptance Criteria

- [ ] Email sent on new comment mentioning the user
- [ ] Email sent on spec status change (draft → in_progress)
- [ ] Unsubscribe link in every email
- [ ] Rate limit: max 10 emails per user per hour

## 3. In-App Notifications

<!-- canon:system:3 status:draft -->

Show a notification bell with unread count in the app header.

### Acceptance Criteria

- [ ] Notification bell shows unread count
- [ ] Click opens notification drawer
- [ ] Mark individual or all as read
- [ ] Notifications persist for 30 days
```

## Step 2: Commit and Push

```bash
git add docs/specs/user-notifications.md
git commit -m "spec: add user notifications spec"
git push
```

## Step 3: Open a PR That Implements Part of the Spec

Create a branch and implement one of the acceptance criteria:

```bash
git checkout -b feat/email-notifications
# ... implement email notifications ...
git push -u origin feat/email-notifications
```

Open a pull request. Within about 60 seconds, the Canon bot comments:

```
## Canon

> This PR implements email notification sending for user-notifications.md §2.

### Relevant Specs
**User Notifications** · docs/specs/user-notifications.md

| Section | |
|---------|---|
| §2 Email Notifications | Implements email sending logic |

### Realization Status
**User Notifications** § 2. Email Notifications

| AC | Status | Evidence |
|----|--------|----------|
| Email sent on new comment | ✅ Realized | `src/notifications/email.py:42-60` |
| Email sent on status change | ⬜ Not addressed | |
| Unsubscribe link | ✅ Realized | `src/notifications/templates/base.html:15` |
| Rate limit: max 10/hr | ⬜ Not addressed | |
```

## Step 4: Iterate

As you address more acceptance criteria in follow-up PRs, the spec sections auto-transition from `todo` → `in_progress` → `done`. Linked tickets close automatically when all ACs in a section are realized.

## What's Next?

- [Writing Specs](/guides/writing-specs) — Learn the full spec format and best practices
- [Configuration](./configuration) — Customize Canon for your workflow
- [Concepts](/concepts/) — Understand living specs, delta tracking, and the feedback loop
