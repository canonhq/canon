# Release Notes Action

Generate spec-driven release notes from git history. On `release`
events, **updates the GitHub Release body** with a markdown summary of
every spec section that transitioned to `done` between the previous
tag and the new one. Also runnable on `workflow_dispatch` for manual
release prep — in that mode it can write to a file or step summary
instead of mutating the release.

```
uses: canonhq/canon/actions/release-notes@v1
```

::: tip Coordinates with `changelog-automation`
This action generates the **GitHub Release body from spec state** —
which sections completed, with realization-evidence links. The
[changelog-automation](https://github.com/canonhq/canon/blob/main/docs/specs/changelog-automation.md)
spec covers a different surface: the docs-site changelog page rendered
from conventional commits. Use both — they're complementary.
:::

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `from-ref` | no | (auto: previous tag) | Git ref to compare from |
| `to-ref` | no | (auto: release tag or HEAD) | Git ref to compare to |
| `output` | no | `release-body` | `release-body`, `file`, or `summary` |
| `output-path` | no | `RELEASE_NOTES.md` | File path when `output: file` |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `completed-count` | Spec sections that transitioned to `done` |
| `new-specs-count` | New spec files added in the release window |
| `notes-path` | Absolute path to the rendered markdown release notes |
| `json-path` | Absolute path to the JSON release-notes payload |

## Example: auto-update GitHub Release body

The recommended setup. Triggered on every published release, finds
the previous tag automatically, updates the release body in place.

```yaml
# .github/workflows/canon-release-notes.yml
name: Canon Release Notes

on:
  release:
    types: [published]

jobs:
  notes:
    runs-on: ubuntu-latest
    permissions:
      contents: write   # release body update
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # need history to reach previous tag
      - uses: canonhq/canon/actions/release-notes@v1
```

## Example: write to a file for review

For teams that want a human to review the notes before they ship.

```yaml
name: Draft Release Notes

on:
  workflow_dispatch:
    inputs:
      from:
        description: "Previous tag"
        required: true
      to:
        description: "Target tag (default HEAD)"
        required: false
        default: "HEAD"

jobs:
  draft:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: canonhq/canon/actions/release-notes@v1
        with:
          from-ref: ${{ inputs.from }}
          to-ref: ${{ inputs.to }}
          output: file
          output-path: docs/release-notes/${{ inputs.to }}.md
      - uses: actions/upload-artifact@v4
        with:
          name: release-notes
          path: docs/release-notes/${{ inputs.to }}.md
```

## What it generates

The notes are grouped into three sections (any of which may be
empty):

### Completed

For every spec section whose status transitioned **into `done`**
between the two refs:

- The section title with its spec context
- The previous status (`todo`, `in_progress`, `(new)` for sections
  that didn't exist at `from-ref`)
- New realization-evidence comments that landed (PR# / file / lines)

### New specs

Spec files that exist at `to-ref` but didn't at `from-ref`. Each
listed with its current status.

### Removed specs

Spec files that existed at `from-ref` but no longer at `to-ref`.
Useful for catching accidental deletions and for explicit sunsets.

## Underlying CLI

The action wraps `canon release-notes`, a new CLI subcommand. You can
preview the notes locally before pushing the release tag:

```bash
canon release-notes --from v1.45.0 --to HEAD
```

For machine-readable output:

```bash
canon release-notes --from v1.45.0 --json --output release-notes.json
```

## Permissions

| Mode | Required permissions |
|------|---------------------|
| `release-body` | `contents: write` (to update the release) |
| `file` | `contents: read` (or `write` if you commit it back later) |
| `summary` | `contents: read` |

## Pitfalls

- **`fetch-depth: 0` is mandatory**. The action needs full history
  to walk both refs via `git show`. Without it the previous tag is
  unreachable and the action fails.
- **`output: release-body` is gated to `release` triggers**. Calling
  it from `workflow_dispatch` or `push` will fail loudly with an
  error message — use `output: file` or `output: summary` for
  non-release triggers.
- **Status comments must use the canon syntax**. Sections without a
  `<!-- canon:system:N status:done -->` comment won't be detected
  even if their content reads as "done." Lint your specs first.
- **Realization evidence is informational**. The action lists new
  `<!-- canon:realized-in -->` comments that landed in this window
  per completed section, but it doesn't fail if a section completed
  without any. That's a `verify`/`audit` job, not a release-notes
  job.
- **Refs must be reachable**. If your release was cherry-picked from
  a branch and the previous tag isn't an ancestor of the new one,
  pass `--from` explicitly.
