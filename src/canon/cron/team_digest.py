"""Team digest delivery cron job.

Sends per-team weekly spec digests to configured Slack channels
based on team_digests in CANON.yaml.

Usage: python -m canon.cron.team_digest
"""

from __future__ import annotations

import asyncio
import logging

from canon import analytics, otel_logging
from canon.alerts.cron_utils import tracked_cron
from canon.settings import Settings

logger = logging.getLogger(__name__)


@tracked_cron("team_digest_delivery")
async def run_team_digest() -> dict:
    settings = Settings()

    if not settings.slack_bot_token:
        logger.info("Slack bot not configured — skipping team digest")
        return {"skipped": True}

    from canon.slack import SLACK_AVAILABLE, SpecLoader, build_digest_blocks

    if not SLACK_AVAILABLE:
        logger.info("canon-slack extension not installed — skipping team digest")
        return {"skipped": True, "reason": "extension_not_installed"}

    from canon.config.parse import parse_canon_yaml
    from canon.github.client import GitHubClient

    client = GitHubClient(
        app_id=settings.github_app_id,
        private_key=settings.github_private_key,
        installation_id=settings.github_installation_id,
    )

    # Load CANON.yaml to get team_digests config
    team_digests: dict = {}
    for config_name in ("CANON.yaml", "SPECWRIGHT.yaml"):
        try:
            content, _sha = await client.get_file_content(
                settings.github_owner, settings.github_repo, config_name
            )
            result = parse_canon_yaml(content)
            if result.config and result.config.slack and result.config.slack.digest:
                team_digests = {
                    name: cfg
                    for name, cfg in (result.config.slack.digest.team_digests or {}).items()
                }
            break
        except Exception:
            continue
    if not team_digests:
        logger.info("No team_digests configured — skipping")
        return {"skipped": True, "reason": "no_config"}

    # Load specs
    loader = SpecLoader(
        github_client=client, owner=settings.github_owner, repo=settings.github_repo
    )
    await loader.load()

    if loader.has_load_error:
        logger.error("Failed to load specs: %s", loader.load_error)
        return {"error": loader.load_error}

    from slack_sdk.web.async_client import AsyncWebClient

    slack_client = AsyncWebClient(token=settings.slack_bot_token)

    sent = 0
    errors = 0

    for team_name, team_config in team_digests.items():
        channel = getattr(team_config, "channel", "")
        if not channel:
            logger.warning("No channel configured for team %s", team_name)
            continue

        stats = loader.coverage_stats(team=team_name)
        blocks = build_digest_blocks(
            team=team_name,
            specs=loader.specs,
            coverage_pct=stats["pct_done"],
            coverage_delta=0,
        )

        try:
            await slack_client.chat_postMessage(
                channel=channel,
                blocks=blocks,
                text=f"Weekly spec digest for {team_name}",
            )
            sent += 1
            logger.info("Sent digest for team %s to %s", team_name, channel)
        except Exception:
            errors += 1
            logger.warning("Failed to send digest for team %s", team_name, exc_info=True)

    analytics.track(
        "team_digest_sent",
        properties={
            "teams_configured": len(team_digests),
            "sent": sent,
            "errors": errors,
        },
    )

    logger.info("Team digest delivery: %d sent, %d errors", sent, errors)
    return {"sent": sent, "errors": errors}


def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if settings.posthog_logs_enabled:
        otel_logging.init(
            settings.posthog_key,
            min_level=settings.posthog_logs_min_level,
            posthog_host=settings.posthog_host,
        )

    import importlib.metadata
    import socket

    try:
        app_version = importlib.metadata.version("canonhq")
    except importlib.metadata.PackageNotFoundError:
        app_version = "dev"

    analytics.init(
        settings.posthog_key,
        settings.posthog_host,
        super_properties={
            "service": "canon-cron",
            "environment": settings.environment,
            "version": app_version,
            "hostname": socket.gethostname(),
        },
    )

    try:
        result = asyncio.run(run_team_digest())
        logger.info("Team digest complete: %s", result)
    finally:
        analytics.shutdown()
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
