# Plan Action

Generate a task plan from a spec file and open a tracking issue with
one checkbox per acceptance criterion. Designed for `workflow_dispatch`
— pass a spec file path and an issue lands with the full
implementation breakdown.

```
uses: canonhq/canon/actions/plan@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `spec` | **yes** | — | Spec file path or substring match |
| `mode` | no | `issue` | `issue`, `summary`, or `file` |
| `issue-title` | no | (auto from spec) | Title of the tracking issue |
| `issue-labels` | no | `canon,plan` | Comma-separated labels |
| `assignees` | no | `""` | Comma-separated GitHub handles |
| `output-path` | no | `PLAN.md` | Path when `mode: file` |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `plan-path` | Path to the generated plan markdown on the runner |
| `task-count` | Number of tasks in the plan |

## Example

```yaml
name: Canon Plan
on:
  workflow_dispatch:
    inputs:
      spec:
        description: "Spec file path or substring"
        required: true
      assignees:
        description: "GitHub handles to assign (comma-separated)"
        required: false
        default: ""

jobs:
  plan:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/plan@v1
        with:
          spec: ${{ inputs.spec }}
          assignees: ${{ inputs.assignees }}
```

## What it generates

The action wraps `canon plan <spec>`, which produces a markdown task
list grouped by section. Each section becomes a top-level task with
its acceptance criteria as nested checkboxes. The first line of the
output is `# Task Plan: <Spec Title>` — the action uses that to
auto-derive the issue title when `issue-title` is not set.

## Modes

| Mode | Behavior |
|------|----------|
| `issue` (default) | Opens a new tracking issue with the plan body, the configured labels, and any assignees |
| `file` | Writes the plan to `output-path` and exits — useful for downstream tooling |
| `summary` | Writes only to `GITHUB_STEP_SUMMARY` for cheap manual inspection |

## Permissions

- `contents: read`
- `issues: write` (for `mode: issue`)

## Pitfalls

- **The spec must already exist**. This action does not create specs
  — it generates a plan from one. To scaffold a brand-new spec, use
  the [new-spec action](./new-spec).
- **No de-duplication**. Each run opens a new issue. If you want one
  rolling issue per spec, close stale plan issues manually or extend
  the action with a sticky-issue pattern matching by title.
