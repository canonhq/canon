# Verify Action

Static verification of acceptance criteria against the codebase. Greps
for keywords from each unchecked AC and classifies it as `likely`
realized, `not_started`, or `unknown`. **No Claude spend, no token
needed.**

```
uses: canonhq/canon/actions/verify@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `section` | no | `""` | Filter to a single section ID (e.g. `2-oauth`) |
| `fail-on` | no | `never` | Threshold: `error` (any `not_started`), `warning` (any `not_started` or `unknown`), or `never` (informational) |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `total` | Total unchecked ACs evaluated |
| `likely-count` | ACs with code evidence |
| `not-started-count` | ACs with no detectable evidence |
| `unknown-count` | ACs whose status couldn't be determined |
| `report-path` | Absolute path to the JSON verify report on the runner |

## Example

```yaml
name: Verify ACs
on:
  pull_request:
    branches: [main]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/verify@v1
        with:
          fail-on: never
```

## What it does

For every unchecked AC in every spec, `canon verify`:

1. Extracts keywords from the AC text (filters stop-words, limits to 5)
2. `grep`s for each keyword in `src/` and `frontend/src/`
3. Marks the AC as:
   - `likely` if any keyword matches
   - `not_started` if no keywords match
   - `unknown` if no useful keywords could be extracted

This is a **fast heuristic**, not a guarantee. For high-confidence
evaluation use [`canon audit`](./index#the-lint-verify-audit-ladder)
once it ships.

## Step summary

The action emits a `Canon Verify` summary with a count table and a
per-AC breakdown showing status, source spec (`file:line`), section
title, and AC text — so reviewers can jump straight to the spec
location for any AC that didn't auto-detect.

## Pitfalls

- **Heuristic-grade**: AC text must contain words distinctive enough
  for grep. ACs phrased as pure prose (e.g. "the system handles errors
  gracefully") will reliably mark `unknown`.
- **Default `fail-on: never`**: by design — verify is informational
  unless you opt in. Set `fail-on: error` if you want strict gating.
- **Doesn't see `'use cache'` or other framework-specific symbols**:
  the keyword extractor strips most punctuation. If your codebase
  relies on directives, write ACs that name function or class names.
