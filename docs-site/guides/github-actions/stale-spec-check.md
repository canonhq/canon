# Stale Spec Check Action

Find specs whose realization-evidence files have churned but the spec
itself hasn't been touched. **Pure git heuristic** — no Claude spend,
no token required. Pairs with the [audit action](./audit) as the
cheap-and-fast complement: audit asks "did the code drift from the
spec?" via Claude; stale-spec-check asks the cheaper "is the spec
older than its evidence?" question via git timestamps.

```
uses: canonhq/canon/actions/stale-spec-check@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `stale-days` | no | `90` | Spec untouched for at least this many days |
| `code-churn-threshold` | no | `50` | Combined changed lines across realization files |
| `mode` | no | `issue` | `issue` or `summary` |
| `rolling-issue-title` | no | `Canon stale spec check` | Title of the rolling issue |
| `rolling-issue-labels` | no | `canon,stale` | Labels |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `stale-count` | Number of stale specs found |
| `report-path` | Absolute path to the JSON stale report on the runner |

## How a spec is "stale"

A spec is flagged as stale when **all three** of these are true:

1. The spec file hasn't been touched in `stale-days` (default 90)
2. At least one file referenced in its
   `<!-- canon:realized-in -->` comments has been touched within
   those same `stale-days`
3. The combined number of changed lines across the realization files
   exceeds `code-churn-threshold` (default 50)

This catches the most common drift pattern: a feature ships, the
code keeps evolving, but the spec captures the original requirements
and never gets updated. The thresholds are deliberately conservative
to avoid noise — tune them down for high-velocity teams.

## Example

```yaml
name: Canon Stale Specs
on:
  schedule:
    - cron: "0 9 * * 1"
  workflow_dispatch:

jobs:
  stale:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: canonhq/canon/actions/stale-spec-check@v1
        with:
          stale-days: 60
          code-churn-threshold: 100
```

The action checks out the repo with `fetch-depth: 0` automatically
(it needs full history for git-log timestamps).

## Underlying CLI

You can run the same heuristic locally:

```bash
canon stale --stale-days 90 --code-churn-threshold 50
canon stale --json   # for machine-readable output
```

## What it generates

The rolling issue lists every stale spec with:

- The spec path and title
- The owner (with `@` mention if set in frontmatter)
- How many days the spec has been untouched
- How many lines have churned across the realization files
- How recently the most recent realization-file change landed
- The list of churning files (top 8, with overflow line)

## Permissions

- `contents: read`
- `issues: write` (for `mode: issue`)

## Pitfalls

- **fetch-depth: 0 is mandatory**. The action handles this for you,
  but if you wrap it in a workflow that does its own checkout, make
  sure you don't shadow it with a shallow clone.
- **Specs with no realization comments are never flagged**. By
  design — without realization evidence there's no signal to compare
  against. Either add evidence (manually or via `canon audit`) or
  use a different freshness check.
- **Force-pushed history breaks the heuristic**. The action uses
  `git log` timestamps, so if your release branch was force-pushed
  with a fresh history the spec age may look much newer than it is.
- **Renamed files lose history**. If a realization file was renamed
  via `git mv`, the file age will reset to the rename commit. The
  CLI uses the realization comment's literal path so it won't follow
  renames automatically — update the spec when you rename files.
