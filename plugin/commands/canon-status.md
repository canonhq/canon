---
name: canon-status
description: Show spec coverage dashboard for the current repo
argument-hint: "[spec slug]"
---

The user invoked `/canon-status`. Use the Skill tool to invoke the **canon-status** skill, which shows the spec coverage dashboard.

If $ARGUMENTS contains a spec slug, show the detail view for that spec. Otherwise, show the aggregate dashboard across all specs in the repo.

You can also run `canon status` (with optional `--spec <slug>` or `--json`) directly via Bash for a faster non-interactive view.
