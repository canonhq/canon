# GitHub Actions

Canon ships a suite of GitHub Actions you can drop into your existing
CI/CD pipelines. They complement the [GitHub App](../github-app)
without requiring it — you can use Actions, the App, or both.

## Why Actions?

The GitHub App handles conversational PR analysis, doc indexing,
`@canon` mentions, and realization tracking. Actions fill four gaps the
App can't cover by design:

| Gap | Why Actions help |
|-----|------------------|
| **Merge gating** | Actions emit standard check-runs that branch-protection rules can mark **required**. The App posts comments; Actions block merges. |
| **Cron semantics** | Actions run on `schedule:` triggers without any backend dependency. The drift `audit` action is the canonical use case. |
| **No app install** | Some orgs can't or won't install third-party apps. Actions run inside your own workflows with permissions you control. |
| **Composability** | Actions plug into your existing multi-step pipelines with `uses:` and reusable workflows — no separate integration to maintain. |

## The suite at a glance

| Action | Purpose | Needs Canon backend? |
|--------|---------|----------------------|
| [`canonhq/canon@v1`](./setup) — **Setup Canon** | Initialize a new repo with `CANON.yaml` and the spec template | No |
| [`canonhq/canon/actions/spec-lint@v1`](./spec-lint) | Validate spec file structure (frontmatter, sections, ACs) | No |
| [`canonhq/canon/actions/verify@v1`](./verify) | Static AC-vs-code verification with check-run emission | No |
| [`canonhq/canon/actions/coverage-report@v1`](./coverage-report) | Publish a coverage snapshot to a file, issue, or webhook | No |
| [`canonhq/canon/actions/coverage-delta@v1`](./coverage-delta) | Per-PR base-vs-head coverage diff with sticky comment | No |
| [`canonhq/canon/actions/audit@v1`](./audit) | Claude-powered drift detection — rolling issue, PR, or step summary | **Recommended** — `CANON_TOKEN` |
| [`canonhq/canon/actions/sync@v1`](./sync) | CI-side ticket sync (GitHub Issues / Jira / Linear) using workflow secrets | No |
| [`canonhq/canon/actions/release-notes@v1`](./release-notes) | Spec-driven release notes from git history — auto-update GitHub Release body | No |
| [`canonhq/canon/actions/plan@v1`](./plan) | Generate a task plan from a spec, open a tracking issue | No |
| [`canonhq/canon/actions/new-spec@v1`](./new-spec) | Scaffold a new spec from a template, open a PR | No |
| [`canonhq/canon/actions/dedup@v1`](./dedup) | Find and report duplicate tickets — scheduled cleanup hygiene | No |
| [`canonhq/canon/actions/stale-spec-check@v1`](./stale-spec-check) | Find specs whose code has churned but the spec hasn't | No |
| [`canonhq/canon/actions/compliance-export@v1`](./compliance-export) | Export an audit trail of every AC for regulated environments | No |
| [`canonhq/canon/actions/upgrade@v1`](./upgrade) | Bump the pinned canonhq CLI version (Dependabot-but-canon-aware) | No |

Reusable workflows bundle several actions into a single `uses:` line:

| Reusable workflow | Bundles |
|--------------------|---------|
| [`pr-checks.yml`](./recipes#pr-checks-bundle) | `spec-lint` + `verify` + `coverage-delta` |
| [`weekly-audit.yml`](./recipes#weekly-audit-bundle) | `audit` + `coverage-report` |

## The lint → verify → audit ladder

Three layers of checking, each cheaper than the next, each catching
different problems:

| Layer | What it checks | Speed | Claude? | When to run |
|-------|----------------|-------|---------|-------------|
| **`canon lint`** | Spec file structure: frontmatter, section numbering, AC format, comment syntax, `depends_on` resolvability | milliseconds | no | Every PR |
| **`canon verify`** | Whether ACs have grep-detectable evidence in the codebase | seconds | no | Every PR |
| **`canon audit`** | AI-evaluated drift between code reality and spec statuses | minutes | yes | Weekly cron |

The general rule: **lint + verify on PRs (cheap, blocking), audit on a
schedule (expensive, advisory)**. The [reusable `pr-checks` workflow](./recipes#pr-checks-bundle)
is the recommended PR-time bundle. The `audit` action will be the
recommended schedule-time job once it ships.

## Authentication

Most actions need no authentication beyond the workflow's built-in
`GITHUB_TOKEN`. Two exceptions:

- **`audit` action** (when shipped) needs a `CANON_TOKEN` GitHub secret
  that the action uses to call the Canon backend. Claude spend stays on
  your Canon org bill, not on a personal Anthropic account.
- **Self-hosted Canon backend**: pass `canon-api-url` to point any
  Claude-using action at your own deployment instead of
  `https://api.canonhq.co`.

To create a Canon token, run `canon auth tokens create --name <name>`
locally or use the dashboard. See [Self-hosting](../self-hosting) for
backend setup details.

## Quick start

The simplest possible setup — opt in to PR linting and verification with
one block in your repo's `.github/workflows/`:

```yaml
# .github/workflows/canon.yml
name: Canon PR Checks

on:
  pull_request:
    branches: [main]

jobs:
  canon:
    uses: canonhq/canon/.github/workflows/reusable/pr-checks.yml@v1
    with:
      fail-on-lint: error
```

That's it. On every PR you'll get two check-runs (`Spec Lint` and
`Verify ACs`) you can mark required in branch protection.

For more recipes — scheduled coverage snapshots, Slack notifications,
custom configurations — see the [recipes](./recipes) page.

## Versioning

The action suite is versioned **in lock-step with the Canon CLI**. Every
canon-private release tags the public `canonhq/canon` repo with the
matching `v<major>.<minor>.<patch>` and updates the floating `v<major>`
tag (e.g. `v1`). For predictable behavior, pin to a major version
(`canonhq/canon@v1`); for reproducible builds, pin to a specific
patch (`canonhq/canon@v1.46.0`).
