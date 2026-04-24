---
title: "GitHub Actions Suite"
status: draft
owner: ng
team: platform
ticket_project: null
created: 2026-04-11
updated: 2026-04-11
tags: [ci, automation, github-actions, drift-detection, marketplace, enterprise-adoption]
depends_on: [changelog-automation, enterprise-adoption-enablement]
---

# GitHub Actions Suite

A suite of reusable GitHub Actions and workflows that let users wire Canon into
their existing CI/CD pipelines without depending on the Canon GitHub App.

## 1. Background

Canon today ships a single composite action at `action/action.yml` — "Setup
Canon" — which scaffolds a new repo with `docs/specs/_template.md` and
`CANON.yaml`. It is published to `canonhq/canon` via `.github/scripts/export-oss.sh`
and `.github/workflows/sync-oss.yml` on every push to main.

The GitHub App handles conversational PR analysis, doc indexing, @canon
mentions, and realization tracking. But there are gaps:

| Gap | Consequence | Actions fill it because… |
|-----|-------------|--------------------------|
| No merge-gating | Users can't mark Canon checks as required on branch protection rules | Actions emit standard check-runs that branch protection can require |
| No cron semantics | Drift between code and specs accumulates silently | Actions run on `schedule:` with no backend dependency |
| Requires app install | Some orgs can't/won't install third-party apps | Actions run inside the user's own workflows with user-controlled permissions |
| Not composable | Teams can't add Canon to their existing multi-step pipelines | Actions compose via `uses:` and reusable workflows |

The primary user-requested feature is a **scheduled drift audit** that opens an
issue or PR when the agent detects that code has moved on but spec statuses
haven't. That is the anchor use case; the full suite builds out around it.

### Existing surface area

- **CLI commands available today** (in `src/canon/cli/`): `setup`, `login`,
  `logout`, `auth`, `tasks`, `status`, `start`, `done`, `sync`, `dedup`,
  `verify`, `audit`, `plan`, `db`, `agent_setup`.
- **CLI commands referenced by `docs-site/guides/ci-integration.md` but not
  implemented**: `canon lint`, `canon coverage --min`, `canon validate-config`.
  The existing guide is aspirational; this spec folds it in and either
  implements the missing commands or redirects to their actual equivalents.
- **Publishing pipeline**: `export-oss.sh` already copies `action/` → public
  repo. It will be extended to publish the new `actions/` tree and reusable
  workflows.
- **Docs site**: VitePress at `docs-site/`, with a `guides/` directory. New
  content will live under `docs-site/guides/github-actions/`.

### Architectural principle: route Claude through the backend

Actions that need Claude intelligence (`audit` being the canonical case) must
**not** require users to supply their own `ANTHROPIC_API_KEY`. Instead, actions
authenticate to the Canon backend with a `CANON_TOKEN`, and the backend
performs any Claude calls on the user's behalf. This keeps cost and policy
under Canon's control, aligns with the managed-cloud pricing model, and means
OSS users can opt into a "bring-your-own-key" fallback only if they want to
self-host the full pipeline.

## 2. Goals & Non-Goals

**Goals**

- Ship a suite of Canon-aware GitHub Actions covering drift detection, PR-time
  verification, spec linting, coverage reporting, ticket sync, release notes,
  and housekeeping.
- Preserve the existing `action.yml` as the top-level "Setup Canon" marketplace
  listing, with new actions nested under `actions/<name>/action.yml`.
- Publish all actions and reusable workflows to the public `canonhq/canon` repo
  via the existing `sync-oss` pipeline, under floating major-version tags
  (`v1`) and semver patch tags (`v1.2.3`) per marketplace convention.
- Document every action in a new `docs-site/guides/github-actions/` section and
  fold the stale `ci-integration.md` guide into it.
- Provide two reusable workflows (`pr-checks.yml`, `weekly-audit.yml`) that
  bundle the most common action combinations behind a single `uses:` line.

**Non-Goals**

- Replace the GitHub App. Actions complement it; many users will run both.
- Build a separate marketplace listing per action. Everything ships under the
  single `canonhq/canon` repo.
- Implement multi-platform CI support (CircleCI, GitLab CI, Azure Pipelines) —
  out of scope for v1, tracked separately.

## 3. Requirements

### 3.1 Directory Restructure and Setup Action Preservation
<!-- canon:system:3.1 status:todo -->

<!-- canon:ticket:github:541 -->
Move from a single top-level `action/action.yml` to a suite layout. The
top-level `action.yml` (note: at repo root, not under `action/`) remains the
"Setup Canon" marketplace listing so existing users' `uses: canonhq/canon@v1`
references keep working.

#### Acceptance Criteria

- [ ] Repo root has `action.yml` for "Setup Canon" with unchanged inputs
  (`team`, `ticket-system`, `create-pr`) and branding.
- [ ] The old `action/action.yml` is **removed entirely** (no deprecation
  stub). Existing consumers of `uses: canonhq/canon@v1` continue to work
  because the top-level `action.yml` is what the bare `@v1` reference
  resolves to; users referencing `canonhq/canon/action@v1` (the awkward
  nested path) must migrate, and the MVP docs call this out.
- [ ] New directory `actions/<name>/` exists for each action in this spec with
  its own `action.yml`.
- [ ] Existing consumers of `uses: canonhq/canon@v1` continue to work after the
  move (integration test against a fixture consumer workflow).
- [ ] `export-oss.sh` is updated to sync both the top-level `action.yml` and
  the `actions/` tree, with matching file modes.

### 3.2 Canon Backend Authentication for Actions
<!-- canon:system:3.2 status:todo -->

<!-- canon:ticket:github:542 -->
Actions that need Claude intelligence route through the Canon backend using a
`CANON_TOKEN` secret, not a user-supplied Anthropic key.

#### Acceptance Criteria

- [ ] Every Claude-consuming action accepts a `canon-token` input that defaults
  to `${{ secrets.CANON_TOKEN }}`.
- [ ] Every Claude-consuming action accepts an optional `canon-api-url` input
  (default `https://api.canonhq.co`) to point at a self-hosted Canon backend.
  This ships in MVP, not deferred.
- [ ] Actions fail fast with a clear error message when the token is missing or
  invalid, pointing to docs on how to obtain one (managed or self-hosted).
- [ ] The Canon CLI (`canon login --token $CANON_TOKEN --api-url $CANON_API_URL`)
  accepts a non-interactive token login suitable for CI environments, with
  an optional API URL override for self-hosters.
- [ ] The backend `/v1/audit`, `/v1/verify` (or equivalent) endpoints accept a
  CANON_TOKEN-authenticated request, run Claude, and return structured results
  to the action caller.
- [ ] No action in this spec requires `ANTHROPIC_API_KEY` as a mandatory input.
- [ ] Docs include a "Self-hosted Canon" section showing how to point actions
  at a self-hosted backend via the `canon-api-url` input, including the
  minimum backend endpoints the self-hosted deployment must expose.

### 3.3 `audit` Action — Scheduled Drift Detection
<!-- canon:system:3.3 status:todo -->

<!-- canon:ticket:github:543 -->
Runs `canon audit` against the repo on a cron schedule (or manual dispatch) and
reports drift between code and spec statuses. This is the anchor use case.

#### Acceptance Criteria

- [ ] `actions/audit/action.yml` exists as a composite action.
- [ ] Inputs: `canon-token` (required), `specs` (glob, default `docs/specs/**`),
  `dry-run` (default `true`), `sync` (default `false`), `mode`
  (`issue`|`pr`|`summary`, default `issue`), `rolling-issue-title` (default
  `"Canon weekly audit"`).
- [ ] Runs `canon audit --dry-run` when `dry-run: true`, parses structured
  output, and exits successfully with no report when zero drift is detected.
- [ ] In `mode: issue`, opens a single **rolling** issue titled by
  `rolling-issue-title`. Subsequent runs update the same issue rather than
  opening duplicates (idempotency via title match or a pinned marker comment).
- [ ] In `mode: pr`, opens a PR with proposed `<!-- status: ... -->` and
  realization comment updates when `sync: true`.
- [ ] In `mode: summary`, writes to `$GITHUB_STEP_SUMMARY` only (no issue, no
  PR).
- [ ] Action outputs: `drift-count`, `report-url`, `exit-code` consumable by
  downstream steps.
- [ ] Documented example cron: weekly on Mondays at 9am UTC.

### 3.4 `verify` Action — PR-Time Static Verification
<!-- canon:system:3.4 status:todo -->

<!-- canon:ticket:github:544 -->
Runs `canon verify` on a PR and emits a check-run that branch protection can
mark required. No Claude spend, no token required.

#### Acceptance Criteria

- [ ] `actions/verify/action.yml` exists as a composite action.
- [ ] Inputs: `specs` (glob, default `docs/specs/**`), `fail-on`
  (`error`|`warning`|`never`, default `error`).
- [ ] Emits a GitHub check-run named "Canon / verify" with the PR SHA, pass/fail
  status, and a summary of evaluated ACs.
- [ ] On failure, step summary lists failing ACs with file:line references to
  the spec sections.
- [ ] No network calls beyond installing the Canon CLI.
- [ ] Runs in < 60s on a 100-spec repo fixture.

### 3.5 `spec-lint` Action — Frontmatter & Structure Validation
<!-- canon:system:3.5 status:todo -->

<!-- canon:ticket:github:545 -->
Validates spec file structure: frontmatter schema, section numbering, AC
checkbox format, status comment syntax, dependency resolvability. Pure parser,
no network.

**Naming — lint vs verify vs audit.** Canon has three static/dynamic layers
that must stay clearly separated by name; all three are kept, no renames:

| Command | Layer | Speed | Claude |
|---------|-------|-------|--------|
| `canon lint` (new, §3.5) | Spec file structure & format | ms | no |
| `canon verify` (exists) | Spec ACs vs. codebase, static | seconds | no |
| `canon audit` (exists) | Spec ACs vs. codebase, AI-evaluated | minutes | yes |

Docs must explain the ladder explicitly so users know which to wire into PR
checks (lint + verify) vs. scheduled runs (audit).

#### Acceptance Criteria

- [ ] `actions/spec-lint/action.yml` exists as a composite action.
- [ ] A `canon lint` CLI command is added to `src/canon/cli/lint.py` that
  wraps the existing parser and reports structured errors (JSON + human
  output).
- [ ] Lint rules validate: required frontmatter fields (`title`, `status`,
  `owner`), valid status enum, section number monotonicity, AC checkbox
  regex, `<!-- canon:... -->` comment syntax, `depends_on` references that
  resolve to existing spec files.
- [ ] Action inputs: `specs` (glob, default `docs/specs/**`), `warnings-as-errors`
  (default `false`).
- [ ] Emits a check-run "Canon / spec-lint".
- [ ] Unit tests cover each lint rule with positive and negative fixtures.
- [ ] Docs include the lint/verify/audit disambiguation table above in the
  new github-actions guide index.

### 3.6 `coverage-report` Action — Scheduled Coverage Snapshot
<!-- canon:system:3.6 status:todo -->

<!-- canon:ticket:github:546 -->
Publishes a coverage snapshot on a schedule. Outputs to committed markdown, a
rolling tracking issue, or a webhook.

#### Acceptance Criteria

- [ ] `actions/coverage-report/action.yml` exists as a composite action.
- [ ] Inputs: `output` (`file`|`issue`|`webhook`, default `file`), `path`
  (default `docs/coverage.md`), `issue-title`, `webhook-url` (secret).
- [ ] Uses `canon status --json` as the data source; no Claude spend.
- [ ] In `output: file` mode, commits `docs/coverage.md` to a branch and opens
  a PR (or commits directly, controlled by a `commit-mode` input).
- [ ] In `output: issue` mode, updates a rolling issue idempotently.
- [ ] In `output: webhook` mode, POSTs a JSON payload compatible with Slack's
  incoming-webhook format.

### 3.7 `coverage-delta` Action — PR-Time Coverage Diff
<!-- canon:system:3.7 status:todo -->

<!-- canon:ticket:github:547 -->
Comments on PRs with the delta in spec coverage between base and head refs.

#### Acceptance Criteria

- [ ] `actions/coverage-delta/action.yml` exists as a composite action.
- [ ] Runs `canon status --json` against the base ref and head ref, diffs them,
  and writes a sticky PR comment with per-spec deltas.
- [ ] Comment is idempotent — subsequent runs update the same comment rather
  than piling on.
- [ ] No Claude spend. No required token (uses `GITHUB_TOKEN`).
- [ ] Fails gracefully and emits a neutral check when no specs changed.

### 3.8 `sync` Action — CI-Side Ticket Sync
<!-- canon:system:3.8 status:todo -->

<!-- canon:ticket:github:548 -->
Runs `canon sync` in CI so that orgs wanting their ticket-system credentials to
live in GitHub secrets (not the Canon backend) can still get bidirectional
sync.

#### Acceptance Criteria

- [ ] `actions/sync/action.yml` exists as a composite action.
- [ ] Inputs: `canon-token`, `direction` (`forward`|`reverse`|`both`, default
  `both`), `dry-run` (default on PRs, off on main), `specs` glob.
- [ ] On PRs, defaults to `--dry-run` and posts the would-be-sync plan as a PR
  comment.
- [ ] On main, runs the real sync and writes a step summary of created/updated
  tickets.
- [ ] Accepts ticket-system credentials via standard env var names
  (`JIRA_TOKEN`, `LINEAR_API_KEY`, etc.) passed through the action's `env:`.

### 3.9 `release-notes` Action — Spec-Driven Release Notes
<!-- canon:system:3.9 status:todo -->

<!-- canon:ticket:github:549 -->
On release tag, generate release notes from specs that reached `done` status in
the version range, linked to realization evidence. Coordinates with the
`changelog-automation` spec: that spec generates the docs-site changelog from
conventional commits; this action generates the GitHub Release body from spec
state.

#### Acceptance Criteria

- [ ] `actions/release-notes/action.yml` exists as a composite action.
- [ ] Inputs: `from-tag`, `to-tag` (default: previous tag → current tag),
  `output` (`release-body`|`file`, default `release-body`), `template` path
  (optional).
- [ ] Walks spec files, finds those whose `status` transitioned to `done`
  between the two tags (using git blame or status-change log), groups by
  system/section, renders as markdown with realization links.
- [ ] In `output: release-body` mode, updates the GitHub Release body via the
  GitHub API.
- [ ] Explicitly defers changelog-style commit summaries to
  `changelog-automation`; no overlap.

### 3.10 Reusable Workflow — `pr-checks.yml`
<!-- canon:system:3.10 status:todo -->

<!-- canon:ticket:github:550 -->
A reusable workflow that bundles `verify` + `spec-lint` + `coverage-delta` for
one-line opt-in.

#### Acceptance Criteria

- [ ] `.github/workflows/reusable/pr-checks.yml` exists with
  `workflow_call:` trigger.
- [ ] Exposes inputs for the glob, fail thresholds, and token.
- [ ] Documented usage: `uses: canonhq/canon/.github/workflows/reusable/pr-checks.yml@v1`.
- [ ] Smoke-tested against a fixture consumer repo in CI.

### 3.11 Reusable Workflow — `weekly-audit.yml`
<!-- canon:system:3.11 status:todo -->

<!-- canon:ticket:github:551 -->
A reusable workflow that bundles `audit` + `coverage-report` + `stale-spec-check`
+ `dedup` on a weekly cron.

#### Acceptance Criteria

- [ ] `.github/workflows/reusable/weekly-audit.yml` exists with both
  `workflow_call:` and an example `schedule:` trigger in docs.
- [ ] Exposes inputs for the cron expression, canon-token, and per-step toggles.
- [ ] Documented usage includes a full copy-paste consumer example.

### 3.12 `plan` Action — Generate Tasks from a Spec
<!-- canon:system:3.12 status:todo -->

<!-- canon:ticket:github:552 -->
`workflow_dispatch`-triggered action that takes a spec file and opens a
tracking issue (or sub-issues) containing tasks extracted by `canon plan`.

#### Acceptance Criteria

- [ ] `actions/plan/action.yml` exists as a composite action.
- [ ] Inputs: `spec` (path, required), `mode` (`issue`|`sub-issues`, default
  `issue`), `assignees` (comma-separated), `labels`.
- [ ] Runs `canon plan <spec>` and parses its output.
- [ ] In `mode: issue`, opens one tracking issue with a checkbox per AC.
- [ ] In `mode: sub-issues`, opens a parent issue and child issues linked via
  task-list syntax.

### 3.13 `new-spec` Action — Scaffold a Spec from a Prompt
<!-- canon:system:3.13 status:todo -->

<!-- canon:ticket:github:553 -->
`workflow_dispatch`-triggered action that scaffolds a new spec file and opens a
PR. Lowers the barrier for non-technical authors.

#### Acceptance Criteria

- [ ] `actions/new-spec/action.yml` exists as a composite action.
- [ ] Inputs: `title` (required), `type` (`feature`|`adr`|`proposal`, default
  `feature`), `owner`, `team`.
- [ ] Copies `docs/specs/_template.md` to a slugified filename, fills
  frontmatter, opens a PR.
- [ ] Optionally, if `canon-token` is provided, calls the backend to generate a
  draft Background and Acceptance Criteria from the title.

### 3.14 `compliance-export` Action — Audit Trail Export
<!-- canon:system:3.14 status:todo -->

<!-- canon:ticket:github:554 -->
Exports a compliance-grade audit trail of every AC → status → evidence PR/file
for regulated environments. Addresses the compliance hook noted in
`enterprise-adoption-enablement.md` §8.

#### Acceptance Criteria

- [ ] `actions/compliance-export/action.yml` exists as a composite action.
- [ ] Inputs: `format` (`json`|`csv`, default `json`), `output-path`,
  `commit-to-branch` (optional).
- [ ] Walks all specs, emits one row per AC with: spec path, section id, AC
  text, status, realization PRs, file references, last-updated date.
- [ ] Uploads as a workflow artifact by default.
- [ ] Optionally commits to a `compliance/` branch for long-term retention.

### 3.15 `dedup` Action — Scheduled Ticket Deduplication
<!-- canon:system:3.15 status:todo -->

<!-- canon:ticket:github:555 -->
Runs `canon dedup --dry-run` on a schedule and opens a PR with proposed cleanup.

#### Acceptance Criteria

- [ ] `actions/dedup/action.yml` exists as a composite action.
- [ ] Inputs: `canon-token`, `apply` (default `false`), `specs` glob.
- [ ] When `apply: false`, writes a step summary of proposed dedups.
- [ ] When `apply: true`, runs the real dedup and opens a PR (if any writes
  happened) with a before/after summary.

### 3.16 `upgrade` Action — Canon Version Bump
<!-- canon:system:3.16 status:todo -->

<!-- canon:ticket:github:556 -->
Monthly or manually-triggered action that bumps the pinned `canonhq` CLI
version, runs `canon db migrate` if needed, and opens a PR.

#### Acceptance Criteria

- [ ] `actions/upgrade/action.yml` exists as a composite action.
- [ ] Inputs: `target` (`latest`|semver string, default `latest`),
  `run-migrations` (default `true`).
- [ ] Detects the current pinned version from the consumer's own
  workflow/requirements file, bumps it, runs migrations, opens a PR.

### 3.17 `stale-spec-check` Action — Find Unreviewed Drift
<!-- canon:system:3.17 status:todo -->

<!-- canon:ticket:github:557 -->
Finds specs whose last commit is older than N days while their referenced code
paths have continued to change, and opens an issue asking the owner to review.

#### Acceptance Criteria

- [ ] `actions/stale-spec-check/action.yml` exists as a composite action.
- [ ] Inputs: `stale-days` (default `90`), `code-churn-threshold` (lines,
  default `50`).
- [ ] Uses `git log` to detect the heuristic; no Claude spend.
- [ ] Opens one rolling issue listing stale specs with owner @-mentions.

### 3.18 Docs Site — New `github-actions/` Guide Section
<!-- canon:system:3.18 status:todo -->

<!-- canon:ticket:github:558 -->
Create a dedicated docs section for the Actions suite and fold the existing
`ci-integration.md` guide into it.

#### Acceptance Criteria

- [ ] `docs-site/guides/github-actions/index.md` exists with an overview,
  "Actions vs. the GitHub App" comparison, and authentication setup.
- [ ] One page per action (`audit.md`, `verify.md`, `spec-lint.md`, etc.) with
  inputs, outputs, full example workflow, and common pitfalls.
- [ ] `docs-site/guides/github-actions/recipes.md` collects copy-paste recipes
  for common workflow combos.
- [ ] `docs-site/guides/ci-integration.md` is deleted or replaced with a
  redirect stub pointing to the new section. References to nonexistent CLI
  commands (`canon lint`, `canon coverage --min`, `canon validate-config`)
  are either implemented in §3.5 or removed.
- [ ] VitePress sidebar config is updated to show the new section.
- [ ] The existing `gen-refs` pipeline is not broken by the changes.

### 3.19 Publishing, Versioning, and Smoke Tests
<!-- canon:system:3.19 status:todo -->

<!-- canon:ticket:github:559 -->
Extend the existing `sync-oss` pipeline to publish the new actions with proper
version tagging, and add a post-sync smoke test.

#### Acceptance Criteria

- [ ] `.github/scripts/export-oss.sh` is updated to rsync the `actions/` tree
  and `.github/workflows/reusable/` into the public repo.
- [ ] Action releases are **synchronized with canon-private releases** — every
  canon-private semver bump (driven by Python Semantic Release) also tags
  the public repo with the matching `v<major>.<minor>.<patch>` and updates
  the floating `v<major>` tag. No independent action versioning.
- [ ] The release workflow refuses to tag the public repo if the fixture
  smoke test failed on the canon-private PR that introduced the change.
- [ ] A post-sync smoke-test workflow in the public repo invokes each action
  against a minimal fixture repo and fails the release if any action errors.
- [ ] The canon-private CI runs an equivalent fixture-based smoke test on PRs
  that touch `actions/` so regressions are caught pre-merge.

### 3.20 Testing Strategy
<!-- canon:system:3.20 status:done -->

#### Acceptance Criteria

- [x] Per-action CLI surfaces have unit tests; end-to-end tests use
  [nektos/act](https://github.com/nektos/act) via a workflow_dispatch
  runtime test suite gated behind a `runtime-test` PR label or a
  manual trigger.
<!-- canon:realized-in:PR#? file:.github/workflows/runtime-test-suite.yml -->
<!-- canon:realized-in:PR#? file:.github/workflows/ci.yml -->
- [x] A canonical fixture repo (`tests/fixtures/actions/sample-repo/`)
  with three specs (positive, negative, drift) and a realized
  `src/sample.py` is used by the canon-private smoke test job and
  by the post-sync smoke test in the public repo.
<!-- canon:realized-in:PR#? file:tests/fixtures/actions/sample-repo/CANON.yaml -->
- [x] CI runs each action against the fixture on Linux. macOS/Windows
  are out of scope (composite actions are runner-agnostic; the CLI
  is what needs platform coverage and pytest covers it).
<!-- canon:realized-in:PR#? file:.github/workflows/ci.yml -->
- [x] Every new `canon` CLI command added in this spec
  (`canon lint`, `canon login --token`, `canon release-notes`,
  `canon new`, `canon stale`, `canon export`) has its own
  `tests/test_cli/test_*.py` file with positive and negative
  fixtures.
<!-- canon:realized-in:PR#? file:tests/test_cli/test_lint.py -->
<!-- canon:realized-in:PR#? file:tests/test_cli/test_release_notes.py -->
<!-- canon:realized-in:PR#? file:tests/test_cli/test_new_spec.py -->
<!-- canon:realized-in:PR#? file:tests/test_cli/test_stale.py -->
<!-- canon:realized-in:PR#? file:tests/test_cli/test_export.py -->
- [x] Static action linting via `actionlint` runs on every PR as the
  fast first-line defense for shell syntax, expression, and field
  validation. Complements the slower nektos/act runtime test which
  is opt-in via PR label.
<!-- canon:realized-in:PR#? file:.github/workflows/ci.yml -->

## 4. Technical Design

<!-- canon:system:4 status:draft -->

### 4.1 Composite Action Pattern

Every action in this suite is a **composite** action, not a Docker or
JavaScript action. Rationale:

- Composite actions are pure YAML + shell, which mirrors the existing
  `action.yml` and keeps maintenance low.
- Users avoid pulling a Docker image on every run.
- The common sequence (`checkout` → `setup-python` → `pip install canonhq` →
  `canon <cmd>`) is identical across actions; only the command and input
  mapping differ.

A small `actions/_lib/install-canon/action.yml` helper action encapsulates the
install step so the other actions can `uses: ./actions/_lib/install-canon` and
stay DRY. This helper is internal and not documented as a public surface.

### 4.2 Canon Backend Routing for Claude Operations

Actions that need Claude (`audit`, optionally `new-spec` for AI-assisted
drafting) call the Canon backend rather than Anthropic directly:

```
GitHub Action
    │  CANON_TOKEN (GitHub secret)
    ▼
POST https://api.canonhq.co/v1/audit
    │  JSON body: { repo, specs, diff, mode: "dry-run" }
    ▼
Canon backend
    │  Authenticated via CANON_TOKEN
    │  Calls Claude with user's spec context
    ▼
Returns structured JSON: { drift: [...], proposed_updates: [...] }
    │
    ▼
Action parses and emits issue/PR/summary
```

The `canon audit` CLI already runs Claude today; the action delegates to the
CLI, and the CLI either (a) calls the backend when `CANON_TOKEN` is set, or
(b) falls back to a local Anthropic key when running self-hosted. This
CLI-level switch is the single integration point — actions don't know about
it.

### 4.3 Check-Run Emission and Required-Status Semantics

Actions that participate in PR gating (`verify`, `spec-lint`, `coverage-delta`)
emit GitHub check-runs via the REST API (`POST /repos/{owner}/{repo}/check-runs`)
using the built-in `GITHUB_TOKEN`. The check-run name is stable ("Canon /
verify") so that branch protection rules reference the same name across runs.

### 4.4 Rolling-Issue Idempotency Pattern

Actions that create tracking issues (`audit` in issue mode, `coverage-report`,
`stale-spec-check`) use a **rolling-issue** pattern:

1. On start, the action searches for an existing open issue with the configured
   title (or a pinned magic comment marker `<!-- canon:action:<name>:rolling -->`).
2. If found, the action updates the issue body in place.
3. If not found, the action opens a new issue with the marker.
4. Issue closure is left to users — the action never closes an issue it
   created, only updates it.

This avoids issue-spam on weekly cron schedules.

### 4.5 Error Handling and Graceful Degradation

- **Missing token**: actions that require a `CANON_TOKEN` fail fast with a
  clear pointer to docs. They do **not** silently skip work.
- **CLI errors**: captured and echoed to `$GITHUB_STEP_SUMMARY` with the exit
  code and stderr. The action exit code propagates.
- **No specs detected**: neutral result (check-run conclusion `neutral`), not
  failure. A repo bootstrapping Canon shouldn't be penalized.
- **GitHub API rate limits**: all REST calls use the standard `GITHUB_TOKEN`,
  not a PAT; hitting a rate limit produces a neutral result with a summary
  message rather than a hard failure.

## 5. Rollout Plan

<!-- canon:system:5 status:draft -->

### Phase 1 — MVP (systems §3.1–§3.6, §3.10, §3.18, §3.19, §3.20 partial)

Ship the foundation plus the highest-leverage actions:

- Directory restructure (§3.1)
- Backend auth wiring (§3.2)
- `audit` (§3.3) — the anchor use case
- `verify` (§3.4) and `spec-lint` (§3.5) — merge-gating differentiators
- `coverage-report` (§3.6) — cheap win
- Reusable `pr-checks.yml` (§3.10)
- New docs section (§3.18), fold in `ci-integration.md`
- Publishing pipeline updates (§3.19)
- Fixture repo + basic integration tests (§3.20)

Tag as `v1.0.0`, float `v1`.

### Phase 2 — V1.1 (systems §3.7–§3.9, §3.11)

- `coverage-delta` (§3.7)
- `sync` (§3.8)
- `release-notes` (§3.9), coordinated with `changelog-automation`
- Reusable `weekly-audit.yml` (§3.11)

Tag as `v1.1.0`.

### Phase 3 — V1.2 (systems §3.12–§3.17)

- `plan`, `new-spec`, `compliance-export`, `dedup`, `upgrade`,
  `stale-spec-check`

Tag as `v1.2.0`.

### Validation gates between phases

Each phase completes only when:

1. All ACs in that phase's systems are marked `[x]` with realization evidence.
2. The fixture-repo smoke test passes for every action in the phase.
3. A dogfood check passes: canon-private itself consumes the new actions from
   the public repo (pinned to the new tag) in at least one of its own
   workflows.
4. Docs for each shipped action are live on canonhq.co/docs.

## 6. Open Questions

All originally-logged open questions have been resolved during planning and
are recorded here for traceability:

- ~~**Marketplace listing structure**~~ — **Resolved**: single listing under
  `canonhq/canon`; do not promote a second listing.
- ~~**Self-hosted backend support**~~ — **Resolved**: `canon-api-url` input
  ships in MVP (§3.2), not deferred.
- ~~**`canon lint` vs `canon verify` disambiguation**~~ — **Resolved**: keep
  both and introduce `lint` as the pure-parser layer. §3.5 documents the
  three-layer ladder (lint → verify → audit). No renames.
- ~~**Action naming convention**~~ — **Resolved**: bare names
  (`actions/audit`, not `actions/canon-audit`); the `canonhq/canon/actions/`
  prefix already namespaces them.
- ~~**Retention of the old `action/action.yml`**~~ — **Resolved**: remove
  entirely (§3.1). No deprecation stub. Existing `uses: canonhq/canon@v1`
  references keep working because the top-level `action.yml` is what bare
  `@v1` resolves to.
- ~~**Release cadence**~~ — **Resolved**: synchronized with canon-private
  (§3.19). Every canon-private semver tag produces a matching public-repo
  tag and floating `v<major>` update.

### Remaining live questions (not blocking MVP)

- **Backend API contract for `/v1/audit` and `/v1/verify`**: needs its own
  design doc before §3.2 is implementable. The CLI already runs Claude
  locally; the backend route is new. Track as a follow-up spec.
- **PR comment format for `coverage-delta`** (§3.7): should we render as a
  bare markdown table, or use the same sticky-comment format the GitHub App
  uses so users get a consistent look whether they run the app, the action,
  or both? Lean toward consistent-with-app.
