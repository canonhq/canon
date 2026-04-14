# Sync Action

Sync spec sections with the configured ticket system (GitHub Issues,
Jira, or Linear) from CI. Useful when your org wants ticket-system
credentials to live as **GitHub secrets in your own workflow** rather
than being held server-side by the Canon managed cloud.

```
uses: canonhq/canon/actions/sync@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `direction` | no | `both` | `forward` (specs → tickets), `reverse` (tickets → specs), or `both` |
| `specs` | no | `""` | Substring filter for spec file paths |
| `dry-run` | no | `""` | Force dry-run mode (default: dry-run on PRs, apply on push) |
| `comment` | no | `true` | Post a sticky PR comment with the sync plan when running on a PR |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `exit-code` | Exit code from `canon sync` (0 = success) |
| `dry-run-used` | Whether the run was a dry-run (`true` / `false`) |
| `log-path` | Absolute path to the captured sync log on the runner |

## Example: bidirectional sync on push to main

```yaml
name: Canon Ticket Sync

on:
  push:
    branches: [main]
    paths:
      - "docs/specs/**"
      - "CANON.yaml"

jobs:
  sync:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      issues: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/sync@v1
        with:
          direction: both
        env:
          # GitHub Issues uses the workflow's built-in token automatically.
          # For Jira or Linear, pass the secret here.
          # JIRA_TOKEN: ${{ secrets.JIRA_TOKEN }}
          # LINEAR_API_KEY: ${{ secrets.LINEAR_API_KEY }}
```

## Example: dry-run preview on PRs

```yaml
name: Canon Ticket Sync (dry-run)

on:
  pull_request:
    branches: [main]
    paths:
      - "docs/specs/**"
      - "CANON.yaml"

jobs:
  sync:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write   # for the sticky comment
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/sync@v1
        # dry-run defaults on for PR triggers, so no input is needed
```

The action posts a sticky `<!-- canon:action:sync:rolling -->` comment
on the PR with the would-be-sync plan and updates it in place on
subsequent runs.

## How it routes

The `sync` action always runs the CLI in **`--local` mode**, which
bypasses the Canon server proxy and talks to the ticket system
directly using credentials from the workflow environment:

- **GitHub Issues**: uses the workflow's built-in `GITHUB_TOKEN`
- **Jira**: reads `JIRA_TOKEN` (and any other env vars Canon's Jira
  adapter expects — see the [ticket sync guide](../ticket-sync))
- **Linear**: reads `LINEAR_API_KEY`

This is the right model when:

- You don't want the Canon managed cloud holding your Jira/Linear
  credentials
- You're self-hosting Canon and don't run the server-proxy adapter
- You want every sync to be visible as a workflow run in your own
  GitHub Actions UI

## Step summary

Every run writes the sync command line, the chosen mode (dry-run or
apply), the spec filter (if any), and the last 200 lines of CLI output
to `$GITHUB_STEP_SUMMARY`. The full log is preserved at the path
exposed via the `log-path` output.

## Permissions

| Mode | Required permissions |
|------|---------------------|
| `direction: forward` (or `both`) on push | `contents: read`, `issues: write`, `pull-requests: write` |
| `direction: reverse` (or `both`) on push | `contents: write`, `issues: read`, `pull-requests: read` |
| Dry-run on PR with `comment: true` | `contents: read`, `pull-requests: write` |

## Pitfalls

- **Dry-run is the default on PRs for a reason**. The forward path
  creates real tickets and the reverse path mutates spec files. You
  almost always want a human review before either happens. Override
  with `dry-run: false` only if you trust the trigger.
- **`--local` is non-negotiable**. The action always passes `--local`
  because the alternative — server-proxy mode — requires Canon-side
  credentials that aren't available in CI. If you want the proxy
  flow, install the Canon backend and let the `audit` action call it
  via `canon-token`.
- **Reverse sync on PRs is rarely useful**. The point of `reverse` is
  to pull ticket-system updates back into specs, which then need to
  be committed. On a PR you can preview the changes, but applying
  them requires a follow-up commit. Most teams run forward on PRs
  (for visibility) and reverse on a schedule (in `weekly-audit.yml`).
