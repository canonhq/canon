# Compliance Export Action

Export a compliance-grade audit trail of every acceptance criterion
across every spec, with realization evidence and last-modified
timestamps. **Pure parser, no Claude spend, no token required.** The
output uploads as a workflow artifact and (optionally) commits to a
long-lived `compliance/` branch for retention.

The hook the
[`enterprise-adoption-enablement`](https://github.com/canonhq/canon/blob/main/docs/specs/enterprise-adoption-enablement.md)
spec §8 calls out for regulated environments.

```
uses: canonhq/canon/actions/compliance-export@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `format` | no | `json` | `json` or `csv` |
| `output-path` | no | `compliance-report` | Path on the runner (extension auto-appended) |
| `artifact-name` | no | `canon-compliance-report` | Workflow artifact name |
| `spec` | no | `""` | Filter to a single spec file |
| `commit-to-branch` | no | `""` | Commit the report to this branch (empty = artifact only) |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `report-path` | Absolute path to the rendered report on the runner |
| `row-count` | Number of AC rows in the report |
| `spec-count` | Number of specs scanned (only populated for JSON format) |

## Schema

The JSON output is stable and versioned:

```json
{
  "schema_version": 1,
  "generated_at": "2026-04-11T12:00:00Z",
  "summary": {
    "rows": 1910,
    "specs": 43,
    "checked": 912,
    "unchecked": 998
  },
  "rows": [
    {
      "spec": "docs/specs/auth.md",
      "spec_title": "Auth Hardening",
      "spec_status": "in_progress",
      "owner": "alice",
      "team": "platform",
      "section_id": "1-oauth-login",
      "section_number": "1",
      "section_title": "OAuth Login",
      "section_status": "done",
      "ac_text": "OAuth client registered",
      "ac_checked": true,
      "ac_line": 12,
      "realizations": ["PR#42 src/auth/oauth.py:10-30"],
      "spec_last_modified": "2026-04-11T12:00:00+00:00"
    }
  ]
}
```

The CSV output flattens the same fields one row per AC, with the
`realizations` list joined by `; ` for spreadsheet import.

## Example: monthly artifact

The lightest setup. Generates a JSON report on the first of every
month and uploads it as an artifact for the auditors to download.

```yaml
# .github/workflows/canon-compliance.yml
name: Canon Compliance Export

on:
  schedule:
    - cron: "0 9 1 * *"   # 09:00 UTC on the 1st of each month
  workflow_dispatch:

jobs:
  export:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/compliance-export@v1
        with:
          format: json
```

The artifact is retained for 90 days by default and named
`canon-compliance-report`. Override with `artifact-name`.

## Example: persistent compliance branch

For organizations that need an immutable audit history beyond the
90-day artifact retention.

```yaml
jobs:
  export:
    runs-on: ubuntu-latest
    permissions:
      contents: write   # to commit to the compliance branch
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/compliance-export@v1
        with:
          format: json
          commit-to-branch: compliance/audit-trail
```

::: warning Compliance branch is force-pushed
The action force-pushes the latest report to keep the branch as a
single up-to-date source of truth, not an append-only history. If you
need true append-only, configure GitHub branch protection on the
compliance branch and write a follow-up workflow that commits new
files instead of replacing the existing one.
:::

## Underlying CLI

```bash
canon export --format json --output report.json
canon export --format csv --spec auth-hardening
```

## Permissions

- `contents: read` (always)
- `contents: write` (when `commit-to-branch` is set)

## Pitfalls

- **The artifact captures a point-in-time snapshot**. If your audit
  policy requires a continuous history, use `commit-to-branch` and
  pair it with branch protection.
- **The CSV format omits the spec count** in the action's output
  (because computing it requires re-parsing the file). Use JSON
  if you need that metadata in downstream steps.
- **Unchecked ACs have empty `realizations`**. That's expected — only
  realized ACs accumulate evidence comments. Auditors can filter on
  `ac_checked: false` to see what's still pending.
- **`spec_last_modified` requires git history**. The action uses
  `git log -1 --format=%cI` per spec; uncommitted files or shallow
  clones will produce empty values. The default `actions/checkout@v4`
  has enough history for this.
