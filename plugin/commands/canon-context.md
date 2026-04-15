---
name: canon-context
description: Load spec context for the current task
argument-hint: "[topic or file path]"
---

The user invoked `/canon-context`. Use the Skill tool to invoke the **canon-context** skill, which loads relevant spec context for whatever the user is working on.

If arguments were provided ($ARGUMENTS), treat them as the topic or file path to anchor the context search. If no arguments, infer the topic from recent git changes or the user's recent messages.
