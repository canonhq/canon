---
name: canon-context
description: >
  Load spec context for the current task. Use when starting work on a feature,
  investigating a bug, or reviewing code that relates to a spec. Automatically
  identifies relevant specs from git changes or a user-provided topic.
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - mcp__canon__search
  - mcp__canon__get_spec
  - mcp__canon__get_section
---

# Load Spec Context

You are loading spec context for the user's current task.

## Step 1: Identify Relevant Files

Check what the user is currently working on:

```bash
git diff --name-only HEAD 2>/dev/null || git diff --name-only --cached 2>/dev/null || echo ""
```

If the user provided a topic, use that instead of git changes.

## Step 2: Find Relevant Specs

**With MCP (preferred):** Use `mcp__canon__search` to find specs matching changed files or the topic.

**Without MCP (fallback):** Search locally:
1. Use `Glob` to find all specs: `docs/specs/*.md`
2. Use `Grep` to search spec content for terms from changed files or topic
3. Use `Read` to load matching spec files

## Step 3: Present Context

For each relevant spec, present:
- **Title** and **status** from frontmatter
- **Relevant sections** with their status (draft/todo/in_progress/done)
- **Acceptance criteria** — checked items and unchecked items
- **Ticket links** if present

## Spec Format Reference

Specs use YAML frontmatter:
```yaml
---
title: "Feature Name"
type: spec          # spec, proposal, design, adr
status: draft       # draft, in_progress, done, deprecated
owner: "name"
team: "team-name"
tags: [tag1, tag2]
---
```

Sections are numbered headings (`## 1. Section Title`).
Status comments: `<!-- canon:system:1.1 status:todo -->`
Ticket links: `<!-- canon:ticket:github:ORG-123 -->`
AC checkboxes: `- [ ] Unchecked` / `- [x] Checked`
