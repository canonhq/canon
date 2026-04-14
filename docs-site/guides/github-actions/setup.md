# Setup Canon Action

Initialize Canon in a repository — drops in `CANON.yaml` and the spec
template, optionally as a PR.

```
uses: canonhq/canon@v1
```

This is the top-level action; the bare `canonhq/canon@v1` reference
resolves to it.

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `team` | no | `""` | Team name written into `CANON.yaml` |
| `ticket-system` | no | `github` | One of `github`, `jira`, `linear` |
| `create-pr` | no | `true` | Open a PR with the setup files (vs. committing directly) |
| `python-version` | no | `3.12` | Python runtime for the install step |
| `canon-version` | no | `>=1.0.0,<2.0.0` | pip version constraint for the Canon CLI |

## Example

Run setup once when bootstrapping a new repo:

```yaml
name: Setup Canon
on:
  workflow_dispatch:
    inputs:
      team:
        description: "Team name"
        required: true

jobs:
  setup:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon@v1
        with:
          team: ${{ inputs.team }}
          ticket-system: github
```

## What it does

1. Installs the Canon CLI via `pip install canonhq`
2. Runs `canon setup --non-interactive --team <team> --ticket-system <ts>`
3. If `create-pr: true`, creates a `canon/setup` branch with the new
   files and opens a PR titled `chore: initialize Canon`

## Permissions

When `create-pr: true`, the workflow needs `contents: write` and
`pull-requests: write`.

## Pitfalls

- **Already-initialized repos**: `canon setup` is idempotent — re-running
  it on a repo that already has `CANON.yaml` is a no-op. The PR step will
  skip if no files changed.
- **`team` is optional but recommended**: Without it, downstream actions
  that filter by team (e.g. `coverage-report` per-team digests) won't
  have an owner to attribute against.
