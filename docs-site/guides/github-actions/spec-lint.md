# Spec Lint Action

Static structural validation for spec files. Checks frontmatter schema,
section numbering, AC checkbox format, status comment syntax, and
`depends_on` resolvability. **Pure parser, network-free, no Claude
spend, no token needed.**

```
uses: canonhq/canon/actions/spec-lint@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `specs` | no | `""` (read from `CANON.yaml`) | Glob filter for spec files |
| `warnings-as-errors` | no | `false` | Treat lint warnings as errors |
| `fail-on` | no | `error` | Threshold: `error`, `warning`, or `never` |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `error-count` | Number of lint errors found |
| `warning-count` | Number of lint warnings found |
| `report-path` | Absolute path to the JSON lint report on the runner |

## Example

```yaml
name: Spec Lint
on:
  pull_request:
    paths:
      - "docs/specs/**"
      - "CANON.yaml"

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/spec-lint@v1
        with:
          fail-on: error
```

## What it checks

| Rule | Severity | What triggers it |
|------|----------|------------------|
| `frontmatter.title` | error | Empty `title` field |
| `frontmatter.owner` | warning | Empty `owner` field |
| `frontmatter.team` | warning | Empty `team` field |
| `frontmatter.created` / `frontmatter.updated` | warning | Not a `YYYY-MM-DD` date |
| `section.numbering` | warning | Top-level sections not monotonically increasing |
| `ac.missing` | warning | Section is `todo`/`in_progress` but has no acceptance criteria |
| `comment.unknown` | warning | `<!-- canon:... -->` comment with an unknown keyword (typos, malformed comments) |
| `depends_on.unresolved` | warning | `depends_on` entry that doesn't match any discovered spec |
| `parser` | warning/error | Anything the spec parser itself reports (unknown statuses, malformed frontmatter, etc.) |

Lint **skips text inside markdown inline code spans and fenced code
blocks**, so docs that describe canon comment syntax don't false-positive.

## Step summary

The action writes a markdown table to `$GITHUB_STEP_SUMMARY` listing
every issue with severity, rule, file, line, and message — so failures
show up directly in the GitHub UI without diving into raw logs.

## Pitfalls

- **`fail-on: warning` is opinionated**: it treats `ac.missing` warnings
  as failures, which can be loud on repos with lots of placeholder
  sections. Start with `fail-on: error` and tighten over time.
- **No filesystem changes**: `spec-lint` is read-only. It won't fix
  issues automatically — that's a separate workflow.
