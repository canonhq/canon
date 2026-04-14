# Upgrade Action

Bump the pinned `canonhq` CLI version in your repo's dependency
manifest, run any pending database migrations, and open a PR with the
result. Think Dependabot-but-canon-aware. Designed for monthly cron
or manual dispatch.

```
uses: canonhq/canon/actions/upgrade@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `target` | no | `latest` | Target version (`latest` queries PyPI, or pass an explicit semver) |
| `manifest` | no | (auto-detect) | Explicit path to the manifest file |
| `run-migrations` | no | `true` | Run `canon db migrate` after the bump |
| `branch-name` | no | `canon/upgrade` | Branch name for the upgrade PR |
| `open-pr` | no | `true` | Open a PR vs commit directly |
| `python-version` | no | `3.12` | |

## Outputs

| Name | Description |
|------|-------------|
| `from-version` | Previous canonhq version |
| `to-version` | New canonhq version |
| `pr-url` | URL of the opened PR (when `open-pr: true`) |

## Auto-detected manifests

In order, the action checks:

1. `pyproject.toml`
2. `requirements.txt`
3. `requirements/base.txt`

The first one found wins. Pass `manifest:` explicitly if your repo
uses a different layout (e.g. `requirements/prod.txt`).

## How the bump works

The action greps for any `canonhq` pin matching `canonhq[~=<>!]+X.Y.Z`
and rewrites it to `canonhq==<target>`. This is intentionally narrow:

- Single-pin lines like `canonhq==1.46.0` get bumped cleanly.
- Range pins like `canonhq>=1.0.0,<2.0.0` get **collapsed** to a
  single equality pin. If you want to preserve a range, opt out by
  not running this action and updating manually.
- Lines with no canonhq pin produce a warning and the action exits
  cleanly without committing.

## Example: monthly cron

```yaml
# .github/workflows/canon-upgrade.yml
name: Canon Monthly Upgrade

on:
  schedule:
    - cron: "0 9 1 * *"   # 1st of every month at 09:00 UTC
  workflow_dispatch:

jobs:
  upgrade:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: canonhq/canon/actions/upgrade@v1
```

## Example: pin to a specific version

Useful when you want to bump everyone in your fleet to the same
version after testing it on one repo.

```yaml
- uses: canonhq/canon/actions/upgrade@v1
  with:
    target: "1.50.0"
```

## What lands in the PR

A single commit titled `chore(canon): upgrade canonhq to <target>`
containing the manifest change. The PR body links to the docs and
includes a review checklist:

- [ ] CI is green on this branch
- [ ] No breaking changes called out in the canonhq changelog
- [ ] Local `canon lint` and `canon verify` still pass

## Database migrations

When `run-migrations: true` (the default) the action runs
`canon db migrate` after the version bump. The migrate command is
idempotent — safe to run even when no migrations are pending. If
the consumer's deployment doesn't have database access (typical for
self-hosted Canon installs), the action degrades gracefully and
emits a warning rather than failing.

## Permissions

| Mode | Required permissions |
|------|---------------------|
| `open-pr: true` | `contents: write`, `pull-requests: write` |
| `open-pr: false` | `contents: write` |

## Pitfalls

- **Range pins get collapsed to equality pins**. If your project uses
  loose constraints intentionally (e.g. to allow safe minor bumps via
  Dependabot), this action will narrow them. Skip this action and
  let Dependabot handle the bump if you prefer that workflow.
- **Migrations are best-effort**. The action doesn't fail when
  `canon db migrate` errors out — it emits a warning and continues
  to the PR. If your deployment depends on successful migrations,
  add a follow-up CI job that runs them in a real environment.
- **Open PRs with the same branch name are reused**. The action
  uses `--force-with-lease` and updates the existing PR rather than
  opening a new one. To start fresh, close the existing PR and
  delete the branch.
- **No automated test of the new version**. The action installs the
  bumped wheel and runs `canon --help`, but it doesn't run your
  test suite. Use the PR's normal CI to validate the upgrade.
