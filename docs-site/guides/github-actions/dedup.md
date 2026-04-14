# Dedup Action

Find and report duplicate tickets created by spec sync. Designed for
scheduled runs — opens (or updates) a rolling tracking issue listing
proposed cleanups when duplicates are detected. Wraps the existing
`canon dedup` CLI which auto-detects the configured ticket system.

```
uses: canonhq/canon/actions/dedup@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `apply` | no | `false` | Apply the cleanup automatically (vs. dry-run + report) |
| `spec` | no | `""` | Filter to a single spec file |
| `mode` | no | `issue` | `issue` or `summary` |
| `rolling-issue-title` | no | `Canon dedup report` | Title of the rolling issue |
| `rolling-issue-labels` | no | `canon,dedup` | Labels for the rolling issue |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `log-path` | Absolute path to the captured dedup log on the runner |
| `applied` | Whether the action ran in apply mode (`true` / `false`) |

## Example: weekly dry-run report

```yaml
name: Canon Dedup Report
on:
  schedule:
    - cron: "0 9 * * 1"
  workflow_dispatch:

jobs:
  dedup:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/dedup@v1
```

## Example: nightly auto-apply

```yaml
name: Canon Dedup Apply
on:
  schedule:
    - cron: "0 5 * * *"

jobs:
  dedup:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/dedup@v1
        with:
          apply: "true"
```

## What it does

1. Installs the Canon CLI
2. Runs `canon dedup --dry-run` (or `canon dedup` when `apply: true`)
3. Captures the full CLI output to a log file at `log-path`
4. Always writes a step summary with the captured log inside a
   collapsed `<details>` block
5. In `mode: issue`, opens or updates a rolling tracking issue
   identified by the `<!-- canon:action:dedup:rolling -->` magic
   marker — but only if the log mentions the words "duplicate" or
   "dedup" so quiet runs don't churn the issue

## Permissions

| Mode | Required permissions |
|------|---------------------|
| `mode: issue` | `contents: read`, `issues: write` |
| `mode: summary` | `contents: read` |

When `apply: true`, the action also needs whatever permissions the
underlying ticket system requires (typically `issues: write` and
`pull-requests: write` for GitHub Issues, or environment-supplied
credentials for Jira/Linear via the `sync` action's pattern).

## Pitfalls

- **`apply: true` mutates real tickets**. Start with the default
  dry-run mode, review the rolling issue, and only enable apply
  once you trust the dedup logic on your data.
- **The "duplicates detected" check is heuristic**. The action
  greps the log for `duplicate|dedup` to decide whether to update
  the rolling issue. If you have a customized log format, the
  filter may false-fire. File an issue and we'll widen the regex.
- **`canon dedup` requires a ticket adapter**. If your repo's
  CANON.yaml doesn't configure a ticket system, the CLI exits with
  an error and the action surfaces it via the step summary.
