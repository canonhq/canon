---
name: issue-triage
description: AI-powered GitHub issue triage — classification, spec matching, and automatic spec creation
---

# Issue Triage Extension

This extension classifies incoming GitHub issues and relates them to Canon specs.

## What It Does

1. **Classifies** issues into categories: `feature-request`, `bug-report`, `question`, `duplicate`, `support`
2. **Matches** issues to existing spec sections by relevance
3. **Labels** issues with canon-prefixed labels based on classification
4. **Comments** on issues with triage results and related spec links
5. **Creates specs** (optional) — opens draft spec PRs for unmatched feature requests

## Configuration

Add to your `CANON.yaml`:

```yaml
triage:
  enabled: true
  auto_create_specs: false
  classify_labels: true
  ignore_labels: ["wontfix", "invalid"]
  ignore_authors: []
  confidence_threshold: 0.7
```

## CLI Usage

```bash
# Classify an issue (dry run)
canon triage --issue 42 --dry-run

# Classify and apply labels + comment
canon triage --issue 42 --apply

# Classify, apply, and create spec PR if feature-request
canon triage --issue 42 --apply --create-spec
```

## GitHub Action

```yaml
on:
  issues:
    types: [opened]

jobs:
  triage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/issue-triage@v1
        with:
          canon-token: ${{ secrets.CANON_TOKEN }}
          auto-create: false
```
