# Coverage Delta Action

Compute the change in spec coverage between a PR's base and head refs
and post (or update) a sticky PR comment showing per-spec changes.
**No Claude spend, no token needed.** Pairs naturally with the
[coverage-report action](./coverage-report) — `coverage-report` is the
"snapshot" view, `coverage-delta` is the "what changed in this PR" view.

```
uses: canonhq/canon/actions/coverage-delta@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `base-ref` | no | `""` (PR base in PR context, `HEAD~1` otherwise) | Ref to compare against |
| `comment` | no | `true` | Post or update a sticky PR comment with the diff |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `base-coverage` | Overall coverage percentage on the base ref (0–100) |
| `head-coverage` | Overall coverage percentage on the head ref (0–100) |
| `delta-pct` | Coverage delta (`head - base`, can be negative) |
| `changed-spec-count` | Number of specs whose coverage changed |
| `base-report-path` | Absolute path to the JSON status report for the base ref |
| `head-report-path` | Absolute path to the JSON status report for the head ref |

## Example

```yaml
name: Canon Coverage Delta
on:
  pull_request:
    branches: [main]

jobs:
  coverage:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          # Full history so the base ref is reachable
          fetch-depth: 0
      - uses: canonhq/canon/actions/coverage-delta@v1
```

## What it does

1. Installs the Canon CLI
2. Resolves the base ref (PR base by default; `HEAD~1` outside a PR)
3. Runs `canon status --json` on the head commit
4. Detached-checkout to the base ref, runs `canon status --json` again,
   returns to head
5. Diffs the two reports per spec — added, removed, changed
6. Renders a markdown table showing base ACs → head ACs and the
   coverage percentage delta per spec
7. Posts (or updates) a sticky PR comment with the table, identified
   by the `<!-- canon:action:coverage-delta:rolling -->` magic marker
8. Always writes the same table to `$GITHUB_STEP_SUMMARY` whether or
   not the PR comment ships

## Permissions

```yaml
permissions:
  contents: read
  pull-requests: write   # only needed when comment: true
```

If you set `comment: false` the action only writes a step summary and
needs only `contents: read`.

## Idempotency

The PR comment uses a **sticky-comment** pattern: search for an
existing comment whose body starts with the
`<!-- canon:action:coverage-delta:rolling -->` marker and update it
in place. Subsequent runs replace the body rather than adding new
comments. To reset, delete the existing comment manually and the
next run will create a fresh one.

## Pitfalls

- **Base ref must be reachable**. The action fetches the base ref
  on demand, but if your PR was opened against a deleted branch the
  fetch will fail and the comparison emits an empty base report
  (showing every head spec as `added`).
- **Detached-checkout side effects**. The action saves the original
  commit and restores it before posting the comment, so subsequent
  steps in the same job see the head ref. But if the action errors
  mid-checkout, the runner is left detached — use `actions/checkout@v4`
  again as a safety net in any follow-up job that needs the head ref.
- **`canon status` must succeed on both refs**. If the base ref had
  malformed specs that this PR fixes, the base run will fail and the
  action falls back to an empty base report — every head spec then
  shows up as `added`. That's loud but correct: the PR introduced
  spec coverage where there was none before.
- **fetch-depth: 0 is required** to compare against arbitrary base
  refs. The default `actions/checkout@v4` only fetches the head and
  one parent; the action will try to fetch the base on demand but
  full history is the safest default.
