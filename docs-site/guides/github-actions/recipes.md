# Recipes

Copy-paste workflow recipes for common Canon Action setups. Each recipe
is self-contained — drop it into your `.github/workflows/` directory
and adjust to taste.

## PR checks bundle

The recommended PR-time setup. Runs `spec-lint` and `verify` in parallel
on every PR via the [`pr-checks.yml`](https://github.com/canonhq/canon/blob/v1/.github/workflows/reusable/pr-checks.yml)
reusable workflow.

```yaml
# .github/workflows/canon-pr.yml
name: Canon PR Checks

on:
  pull_request:
    branches: [main]

jobs:
  canon:
    uses: canonhq/canon/.github/workflows/reusable/pr-checks.yml@v1
    with:
      fail-on-lint: error
      fail-on-verify: never
```

The two underlying jobs (`Spec Lint` and `Verify ACs`) emit standard
check-runs you can mark **required** in branch protection rules.

### Tightening the gate

Once your specs are clean, tighten the verify threshold to fail PRs
that introduce uncovered ACs:

```yaml
    with:
      fail-on-lint: error
      fail-on-verify: warning  # any not_started or unknown blocks the merge
```

## Per-PR coverage delta comment

Post a sticky comment on every PR showing the base-vs-head coverage
diff, broken out per spec.

```yaml
# .github/workflows/canon-coverage-delta.yml
name: Canon Coverage Delta

on:
  pull_request:
    branches: [main]

jobs:
  delta:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # need history to reach the base ref
      - uses: canonhq/canon/actions/coverage-delta@v1
```

The action posts a single comment with a magic marker and updates it
in place on subsequent runs. To suppress the comment and rely on the
step summary instead, set `comment: false`.

## Weekly coverage report — markdown PR

Render a coverage snapshot to `docs/coverage.md` every Monday and open
a PR with the changes. Reviewers see exactly what moved.

```yaml
# .github/workflows/canon-coverage.yml
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

## Weekly coverage report — rolling issue

If you'd rather track coverage in a single tracking issue than churn
the repo with PRs, use `output: issue`. Each run updates the same issue
in place.

```yaml
name: Canon Weekly Coverage Issue

on:
  schedule:
    - cron: "0 9 * * 1"
  workflow_dispatch:

jobs:
  report:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/coverage-report@v1
        with:
          output: issue
          issue-title: "Canon weekly coverage"
          issue-labels: "canon,coverage"
```

## Weekly drift audit — rolling issue

Detect drift between code and spec statuses every week. Updates a
single tracking issue in place rather than spamming with new issues.

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

The first run opens an issue titled "Canon weekly audit" with a
markdown breakdown of every recommendation. Subsequent runs update
the same issue in place. To reset, close the existing issue and the
next run will open a fresh one.

## Slack coverage notification

Post a coverage summary to a Slack channel via incoming webhook. Use
this when you want push notifications without polluting your repo.

```yaml
name: Canon Coverage Notification

on:
  schedule:
    - cron: "0 9 * * 1"

jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/coverage-report@v1
        with:
          output: webhook
          webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

Set `SLACK_WEBHOOK_URL` as a repository secret pointing at a Slack
incoming webhook for the destination channel.

## Weekly audit bundle

Run the audit action and the coverage-report action together on a
single weekly cron via the `weekly-audit.yml` reusable workflow:

```yaml
# .github/workflows/canon-weekly.yml
name: Canon Weekly

on:
  schedule:
    - cron: "0 9 * * 1"  # Mondays at 09:00 UTC
  workflow_dispatch:

jobs:
  canon:
    uses: canonhq/canon/.github/workflows/reusable/weekly-audit.yml@v1
    with:
      audit-mode: issue
      coverage-output: issue
    secrets:
      CANON_TOKEN: ${{ secrets.CANON_TOKEN }}
```

Both jobs run in parallel and post to their respective rolling
issues. To use webhook-based coverage notifications instead of an
issue, set `coverage-output: webhook` and pass `coverage-webhook-url`.

## Auto-generate release notes on tag

Update the GitHub Release body automatically with a markdown summary
of every spec section that transitioned to `done` since the previous
tag. Triggered on `release: published`.

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
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # required to reach the previous tag
      - uses: canonhq/canon/actions/release-notes@v1
```

The action detects the previous tag automatically via
`git describe --tags --abbrev=0 HEAD^` and walks the spec tree at
both refs to find completed sections.

## CI-side ticket sync

Sync spec sections to GitHub Issues / Jira / Linear from your own
workflow rather than via the Canon server proxy. Dry-run on PRs,
apply on push to main.

```yaml
# .github/workflows/canon-sync.yml
name: Canon Ticket Sync

on:
  pull_request:
    branches: [main]
    paths:
      - "docs/specs/**"
      - "CANON.yaml"
  push:
    branches: [main]
    paths:
      - "docs/specs/**"
      - "CANON.yaml"

jobs:
  sync:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/sync@v1
        with:
          direction: both
        env:
          # GitHub Issues uses GITHUB_TOKEN automatically; for Jira or
          # Linear, pass the secret here:
          # JIRA_TOKEN: ${{ secrets.JIRA_TOKEN }}
          # LINEAR_API_KEY: ${{ secrets.LINEAR_API_KEY }}
```

The action defaults to dry-run on PR triggers (with a sticky comment
showing the would-be sync plan) and to apply mode on push triggers.

## Scaffold a new spec via dispatch

Workflow_dispatch trigger that lets PMs and engineers scaffold a spec
without learning the CLI. The action opens a PR with the new file
ready for editing.

```yaml
# .github/workflows/canon-new-spec.yml
name: Canon New Spec

on:
  workflow_dispatch:
    inputs:
      title:
        description: "Spec title"
        required: true
      type:
        description: "Document type"
        required: false
        default: "spec"
        type: choice
        options: [spec, proposal, design, adr]
      owner:
        description: "Owner GitHub handle"
        required: false
      team:
        description: "Owning team"
        required: false

jobs:
  scaffold:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/new-spec@v1
        with:
          title: ${{ inputs.title }}
          type: ${{ inputs.type }}
          owner: ${{ inputs.owner }}
          team: ${{ inputs.team }}
```

## Generate a task plan from a spec

Pair the new-spec action with the plan action so authors can scaffold
a spec, fill it in, then dispatch a plan that opens a tracking issue.

```yaml
# .github/workflows/canon-plan.yml
name: Canon Plan

on:
  workflow_dispatch:
    inputs:
      spec:
        description: "Spec file path or substring (e.g. auth-hardening)"
        required: true
      assignees:
        description: "GitHub handles to assign (comma-separated)"
        required: false

jobs:
  plan:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/plan@v1
        with:
          spec: ${{ inputs.spec }}
          assignees: ${{ inputs.assignees }}
```

## Weekly stale spec check

Find specs whose realization files have churned but the spec hasn't
been updated. Cheap git heuristic; pairs naturally with the audit
action on the same schedule.

```yaml
# .github/workflows/canon-stale.yml
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
          stale-days: 90
          code-churn-threshold: 50
```

The action handles the `fetch-depth: 0` checkout automatically. To
run alongside the audit + coverage-report bundle, add it as a third
job in the same workflow file.

## Weekly dedup hygiene

Detect duplicate tickets created by spec sync and report them via a
rolling issue. Start in dry-run mode and switch to apply once
trusted.

```yaml
# .github/workflows/canon-dedup.yml
name: Canon Dedup

on:
  schedule:
    - cron: "0 9 * * 1"
  workflow_dispatch:

jobs:
  dedup:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/dedup@v1
        # apply: "true"   # uncomment once you trust the dry-run output
```

## Monthly compliance export

Generate a monthly audit trail of every AC across every spec.
Uploads as a workflow artifact and (optionally) commits to a
long-lived `compliance/` branch for retention.

```yaml
# .github/workflows/canon-compliance.yml
name: Canon Compliance Export

on:
  schedule:
    - cron: "0 9 1 * *"   # 1st of every month at 09:00 UTC
  workflow_dispatch:

jobs:
  export:
    runs-on: ubuntu-latest
    permissions:
      contents: write   # only needed if commit-to-branch is set
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/compliance-export@v1
        with:
          format: json
          commit-to-branch: compliance/audit-trail   # optional
```

The artifact is named `canon-compliance-report` by default and
retained for 90 days.

## Monthly canonhq upgrade

Auto-bump the pinned canonhq CLI version on a monthly cron, run
migrations, and open a PR for review.

```yaml
# .github/workflows/canon-upgrade.yml
name: Canon Monthly Upgrade

on:
  schedule:
    - cron: "0 9 1 * *"
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

The action auto-detects `pyproject.toml` or `requirements.txt`,
queries PyPI for the latest version, runs `canon db migrate`, and
opens a PR titled `chore(canon): upgrade canonhq to <version>`.

## Bootstrap a new repo

Add Canon to a fresh repo on demand. Trigger via `workflow_dispatch`
once and merge the resulting PR.

```yaml
name: Bootstrap Canon

on:
  workflow_dispatch:
    inputs:
      team:
        description: "Team that owns this repo"
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

## Lint-only on spec changes

Cheapest possible Canon hookup — only runs when a spec file changes,
fails the build on parser errors:

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

## Combining with your own jobs

Canon Actions slot into existing workflows alongside your tests and
linters. Example: a single `ci.yml` that runs ruff, pytest, and Canon
checks together.

```yaml
name: CI

on:
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .[dev]
      - run: ruff check
      - run: pytest

  canon:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/spec-lint@v1
        with:
          fail-on: error
      - uses: canonhq/canon/actions/verify@v1
        with:
          fail-on: never
```

The two jobs run in parallel and report independently — a Canon failure
won't mask a test failure or vice versa.
