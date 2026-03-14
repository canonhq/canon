---
name: canon-new
description: >
  Create a new spec document from a template. Use when starting a new feature,
  writing a design doc, proposal, or ADR. Walks through structured creation
  with the user.
allowed-tools:
  - Read
  - Write
  - Glob
  - mcp__canon__create_spec
---

# Create New Spec

You are helping the user create a new spec document.

## Step 1: Gather Information

Ask the user for:
1. **Title** — what is this spec about?
2. **Type** — spec (default), proposal, design, or adr
3. **Team** — which team owns this?
4. **Tags** — relevant tags for discovery

## Step 2: Create the Spec

**With MCP:** Use `mcp__canon__create_spec` to create the file directly in the repo.

**Without MCP:** Create locally using `Write`:
- Path: `docs/specs/<slug>.md` (derived from title)
- Use the template format below

## Spec Template

```markdown
---
title: "<Title>"
type: spec
status: draft
owner: ""
team: "<team>"
review_status: draft
tags: [<tags>]
depends_on: []
created: ""
updated: ""
---

# <Title>

## 1. Background

Describe the context and motivation for this spec.

## 2. Requirements

### Acceptance Criteria

- [ ] First requirement

## 3. Design

Describe the technical approach.

## 4. Rollout Plan

Describe phased rollout and success criteria.
```

## Step 3: Guide Next Steps

After creation, suggest:
1. Fill in the Background section with context
2. Define specific acceptance criteria
3. Add design details
4. Run `/canon:review` when ready for review
