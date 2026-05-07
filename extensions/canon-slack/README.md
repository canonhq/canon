# Canon Slack Extension

Interactive Slack bot for Canon — slash commands, @canon mentions, proactive notifications, dashboards, and team digests.

## Features

- **/canon slash commands** — search specs, check coverage, review status
- **@canon mentions** — natural language queries answered by Claude
- **Proactive notifications** — spec status changes, coverage regressions, stale warnings
- **Dashboards** — spec health overview in Slack channels
- **Team digests** — weekly coverage summaries per team
- **Multi-workspace** — OAuth install flow for managed deployments

## Installation

```bash
canon extension add /path/to/extensions/canon-slack
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SLACK_BOT_TOKEN` | Yes | xoxb- bot user OAuth token |
| `SLACK_SIGNING_SECRET` | Yes | Request signature verification |
| `SLACK_APP_TOKEN` | No | xapp- socket mode token (dev) |

### CANON.yaml

```yaml
slack:
  default_channel: "#canon-specs"
  notifications:
    on_status_change: true
    on_coverage_regression: true
    on_stale_warning: true
  quiet_hours:
    start: "22:00"
    end: "08:00"
    timezone: "America/New_York"
  digest:
    enabled: true
    schedule: "0 9 * * 1"
```

## Architecture

The Slack runtime module lives in Canon core (`src/canon/slack/`) and is activated when `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` environment variables are set. This extension provides IDE-side components (skills and commands) for helping users set up and manage their Slack integration.

In a future phase, the Python runtime code will be fully extracted from core into this extension using Python entry points, enabling Slack to be an optional pip-installable dependency.
