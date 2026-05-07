---
description: "Check Slack integration status and configuration"
---

# Slack Status

Check the status of Canon's Slack integration and show current configuration.

## Arguments

$ARGUMENTS

## Instructions

1. Check if Slack environment variables are configured (`SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`)
2. Read the `slack:` section from CANON.yaml if it exists
3. Report the configuration status:
   - Bot enabled/disabled
   - Default channel
   - Notifications enabled
   - Quiet hours configured
   - Digest schedule
4. If arguments contain "setup", invoke the `canon-slack` skill for setup guidance
