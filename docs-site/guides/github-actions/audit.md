# Audit Action

Detect drift between code reality and spec statuses. Runs `canon audit`
on a schedule (or any trigger) and surfaces recommendations as a
**rolling tracking issue**, a **proposed-changes PR**, or a **step
summary**. The anchor use case for the suite — wires Canon into your
weekly CI cadence.

```
uses: canonhq/canon/actions/audit@v1
```

## How it routes Claude calls

The action picks the first available auth source:

| Priority | Source | Behavior |
|----------|--------|----------|
| 1 | `canon-token` input | Routes through the Canon backend; Claude spend bills against your Canon org. Recommended. |
| 2 | `anthropic-api-key` input | Direct call to Anthropic; spend hits your personal account. Useful for self-hosted Canon or evaluation. |
| 3 | (none) | Heuristic mode — grep-only, no Claude calls. Can suggest `in_progress` but can't confirm `done`. |

::: warning Backend routing requires Canon backend v1.47+
The Canon backend `/v1/actions/audit` endpoint ships in slice 5 of the
GitHub Actions Suite spec. Until that lands, `canon-token` is accepted
by the action and stored in the environment, but the CLI will still
fall back to the local Anthropic key path (or heuristic mode). See the
[backend API design doc](https://github.com/canonhq/canon/blob/main/docs/specs/canon-actions-backend-api.md)
for the contract.
:::

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `canon-token` | no | `""` | Canon platform token (preferred — routes via backend) |
| `canon-api-url` | no | `https://api.canonhq.co` | Self-hosted backend URL |
| `anthropic-api-key` | no | `""` | Direct Anthropic API key (fallback) |
| `specs` | no | `""` | Substring filter for spec file paths |
| `mode` | no | `issue` | One of `issue`, `pr`, `summary` |
| `rolling-issue-title` | no | `Canon weekly audit` | Title of the rolling issue |
| `rolling-issue-labels` | no | `canon,audit` | Comma-separated labels for the rolling issue |
| `pr-branch-name` | no | `canon/audit` | Branch name for `mode: pr` |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `drift-count` | Number of recommendations with a status change |
| `recommendation-count` | Total recommendations (status changes + AC-only) |
| `mode-used` | The audit mode the CLI ran in (`claude`, `heuristic`, `none`) |
| `report-path` | Absolute path to the JSON audit report on the runner |

## Example: weekly rolling-issue audit

The recommended setup. Runs every Monday morning, updates a single
tracking issue in place rather than spamming with new issues.

```yaml
# .github/workflows/canon-audit.yml
name: Canon Weekly Audit

on:
  schedule:
    - cron: "0 9 * * 1"  # Mondays at 09:00 UTC
  workflow_dispatch:

jobs:
  audit:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/audit@v1
        with:
          canon-token: ${{ secrets.CANON_TOKEN }}
          mode: issue
          rolling-issue-title: "Canon weekly audit"
```

## Example: nightly drift PR

Higher-friction but higher-leverage: every drift detection produces a
PR with the proposed status updates already applied. Reviewers approve
and merge.

```yaml
name: Canon Nightly Drift PR

on:
  schedule:
    - cron: "0 5 * * *"  # Every day at 05:00 UTC

jobs:
  audit:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/audit@v1
        with:
          canon-token: ${{ secrets.CANON_TOKEN }}
          mode: pr
          pr-branch-name: canon/audit-nightly
```

## Example: workflow_dispatch summary

Lightweight on-demand inspection. No issue, no PR — just a step
summary in the workflow run UI.

```yaml
name: Canon Audit (manual)
on: workflow_dispatch

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/audit@v1
        with:
          canon-token: ${{ secrets.CANON_TOKEN }}
          mode: summary
```

## What it does

1. Resolves auth (canon-token → anthropic-api-key → heuristic)
2. Runs `canon audit --dry-run --json` to collect recommendations
3. Renders a markdown body grouped by spec, with per-section status
   transitions, confidence levels, AC evaluations, and evidence pointers
4. Dispatches based on `mode`:
   - **issue**: searches for an open issue with the configured title;
     updates in place if found, creates a new one with the
     `<!-- canon:action:audit:rolling -->` marker if not
   - **pr**: re-runs `canon audit` (without `--dry-run`) to apply the
     recommendations to spec files, commits to a feature branch with
     `--force-with-lease`, opens or updates the PR
   - **summary**: emits step-summary table only; no issue or PR

## Step summary

Every run writes a markdown table to `$GITHUB_STEP_SUMMARY` regardless
of mode, listing each recommendation with spec, section, current
status, recommended status, confidence, and reasoning. This is the
fastest way to inspect a run from the GitHub UI.

## Permissions

| Mode | Required permissions |
|------|---------------------|
| `issue` | `contents: read`, `issues: write` |
| `pr` | `contents: write`, `pull-requests: write` |
| `summary` | `contents: read` |

## Idempotency

`mode: issue` uses a **rolling-issue** pattern — search by title,
update in place. To reset, close the existing issue and the next run
will create a fresh one.

`mode: pr` reuses the same branch (`canon/audit` by default) so
subsequent runs update the existing PR with `--force-with-lease`.

## Pitfalls

- **Don't pin `mode: pr` on a high-traffic schedule**. The PR rewrites
  spec files; landing it requires human review every time. Daily is
  the practical maximum.
- **Heuristic mode is informational only**. Without Claude it can flag
  `todo` sections that have grep matches, but it can't promote to
  `done` or evaluate ACs. Always run with a token in production.
- **Cost control**: every run hits Claude. Use `specs:` to scope
  audits to a subset for cheap incremental runs, and reserve full-repo
  audits for the weekly cron.
- **Drift count `0` does not mean "no recommendations"** — there can
  be AC-only updates with no status change. Check
  `recommendation-count` for the total signal.
