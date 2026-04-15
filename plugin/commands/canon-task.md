---
name: canon-task
description: Pick up a single task from a spec and implement its acceptance criteria
argument-hint: "[spec section id or task description]"
---

The user invoked `/canon-task`. Use the Skill tool to invoke the **canon-task** skill, which loads a single spec section, walks through its acceptance criteria, and helps the user implement them.

If $ARGUMENTS contains a spec section ID (e.g., `auth-hardening:2.1`), load that section directly. Otherwise, ask the user which task to pick up or list the unfinished tasks in the active spec.
