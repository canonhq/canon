---
name: canon-slack
description: "Help with Slack integration setup, configuration, and troubleshooting. Use when the user asks about Slack bot setup, notifications, or slash commands."
---

# Slack Integration

Help the user set up and configure Canon's Slack integration.

## Setup Checklist

1. **Create a Slack app** at https://api.slack.com/apps
2. **Configure bot scopes**: `chat:write`, `commands`, `app_mentions:read`, `im:history`, `users:read`
3. **Set environment variables**:
   - `SLACK_BOT_TOKEN` — xoxb- bot user OAuth token
   - `SLACK_SIGNING_SECRET` — request signature verification
   - `SLACK_APP_TOKEN` — xapp- socket mode token (optional, for dev)
4. **Add slash command**: `/canon` pointing to `https://your-domain/slack/events`
5. **Enable event subscriptions** for `app_mention` and `message.im`
6. **Configure CANON.yaml**:

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
    schedule: "0 9 * * 1"  # Mondays at 9am
```

## Slash Commands

| Command | Description |
|---------|-------------|
| `/canon search <query>` | Search specs |
| `/canon list` | List all specs |
| `/canon status [spec]` | Show coverage status |
| `/canon review <spec>` | Show review status |
| `/canon help` | Show all commands |

## Troubleshooting

- **Bot not responding**: Check `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` are set
- **Commands not appearing**: Ensure slash command URL points to `/slack/events`
- **Notifications not sending**: Check `slack.notifications` config in CANON.yaml
- **Socket mode issues**: `SLACK_APP_TOKEN` must start with `xapp-`
