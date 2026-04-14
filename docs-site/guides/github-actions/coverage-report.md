# Coverage Report Action

Publish a Canon spec coverage snapshot. Three output modes:

- **`file`** — render markdown and commit to a branch (or open a PR)
- **`issue`** — update a single rolling tracking issue
- **`webhook`** — POST a Slack-compatible payload to a URL

Designed for scheduled runs but works on any trigger. **No Claude spend,
no token needed.**

```
uses: canonhq/canon/actions/coverage-report@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `output` | no | `file` | One of `file`, `issue`, `webhook` |
| `path` | no | `docs/coverage.md` | Output path for `file` mode |
| `commit-mode` | no | `pr` | `pr` (open a PR) or `direct` (push to default branch) |
| `branch-name` | no | `canon/coverage-report` | Branch name when `commit-mode: pr` |
| `issue-title` | no | `Canon coverage report` | Title of the rolling issue |
| `issue-labels` | no | `canon,coverage` | Labels applied to the rolling issue |
| `webhook-url` | no | `""` | Destination URL (required when `output: webhook`) |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `coverage-pct` | Overall coverage percentage (0–100) |
| `spec-count` | Total number of specs scanned |
| `ac-done` | Total ACs marked as realized |
| `ac-total` | Total ACs across all specs |
| `report-path` | Absolute path to the JSON report on the runner |

## Example: weekly markdown commit

```yaml
name: Canon Weekly Coverage
on:
  schedule:
    - cron: "0 9 * * 1"  # Mondays at 09:00 UTC
  workflow_dispatch:

jobs:
  report:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/coverage-report@v1
        with:
          output: file
          path: docs/coverage.md
          commit-mode: pr
```

## Example: rolling tracking issue

```yaml
- uses: canonhq/canon/actions/coverage-report@v1
  with:
    output: issue
    issue-title: "Canon weekly coverage"
    issue-labels: "canon,coverage,weekly"
```

## Example: Slack webhook

```yaml
- uses: canonhq/canon/actions/coverage-report@v1
  with:
    output: webhook
    webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

The Slack payload uses a green attachment when overall coverage is ≥70%
and amber otherwise. Custom thresholds and templates are tracked for a
later version.

## Step summary

Every run writes a markdown table to `$GITHUB_STEP_SUMMARY` regardless
of output mode, so the GitHub UI always shows the latest snapshot —
even when the action posts to an external destination.

## Idempotency

`issue` mode uses a **rolling-issue** pattern: it searches for an open
issue with the configured title and updates it in place rather than
creating a new one each run. To reset, close the existing issue and
the next run will open a fresh one.

`file` + `commit-mode: pr` reuses the same branch (`canon/coverage-report`
by default) so subsequent runs update the existing PR with
`--force-with-lease`.

## Pitfalls

- **`commit-mode: direct` requires write access to the default branch**.
  Most repos with branch protection will reject this. Use `pr` mode
  unless you know the receiving branch accepts unprotected pushes.
- **Webhook payloads cap at the top 10 specs** to keep Slack messages
  readable. The full list still lands in `$GITHUB_STEP_SUMMARY`.
- **`output: file` with no spec changes is a no-op**: the action checks
  `git diff` and exits cleanly when nothing would change.
