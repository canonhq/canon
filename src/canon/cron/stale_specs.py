"""Stale spec warning cron job.

Checks for specs that haven't been updated past a configurable threshold
and sends notifications to the configured Slack channel.

Usage: python -m canon.cron.stale_specs
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from canon import analytics, otel_logging
from canon.alerts.cron_utils import tracked_cron
from canon.settings import Settings

logger = logging.getLogger(__name__)

DEFAULT_STALE_DAYS = 30


@tracked_cron("stale_spec_check")
async def run_stale_check() -> dict:
    settings = Settings()

    if not settings.slack_bot_token:
        logger.info("Slack bot not configured — skipping stale spec check")
        return {"skipped": True}

    from canon.github.client import GitHubClient
    from canon.slack.spec_loader import SpecLoader

    client = GitHubClient(
        app_id=settings.github_app_id,
        private_key=settings.github_private_key,
        installation_id=settings.github_installation_id,
    )
    loader = SpecLoader(
        github_client=client, owner=settings.github_owner, repo=settings.github_repo
    )
    await loader.load()

    if loader.has_load_error:
        logger.error("Failed to load specs: %s", loader.load_error)
        return {"error": loader.load_error}

    now = datetime.now(UTC)
    stale_threshold = DEFAULT_STALE_DAYS
    stale_specs = []

    for spec in loader.specs:
        if spec.status in ("done", "approved", "archived"):
            continue
        if not spec.updated:
            continue
        try:
            updated_dt = datetime.fromisoformat(spec.updated.replace("Z", "+00:00"))
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=UTC)
            days_since = (now - updated_dt).days
            if days_since >= stale_threshold:
                stale_specs.append((spec, days_since))
        except (ValueError, TypeError):
            continue

    if not stale_specs:
        logger.info("No stale specs found (threshold: %dd)", stale_threshold)
        return {"stale_count": 0}

    # Load channel config from CANON.yaml
    from canon.config.parse import parse_canon_yaml

    default_channel = "#canon-specs"
    sre_channel = ""
    for config_name in ("CANON.yaml", "SPECWRIGHT.yaml"):
        try:
            content, _sha = await client.get_file_content(
                settings.github_owner, settings.github_repo, config_name
            )
            result = parse_canon_yaml(content)
            if result.config and result.config.slack:
                default_channel = result.config.slack.default_channel or default_channel
                sre_channel = result.config.slack.sre_channel or sre_channel
            break
        except Exception:
            continue

    # Send notifications
    from slack_sdk.web.async_client import AsyncWebClient

    from canon.slack.notifications import NotificationConfig, NotificationDispatcher

    slack_client = AsyncWebClient(token=settings.slack_bot_token)
    dispatcher = NotificationDispatcher(
        client=slack_client,
        default_channel=default_channel,
        sre_channel=sre_channel,
        config=NotificationConfig(),
    )

    sent = 0
    for spec, days in stale_specs:
        try:
            await dispatcher.send_stale_spec_warning(
                spec_title=spec.title,
                days_stale=days,
                threshold_days=stale_threshold,
                github_url=spec.github_url,
            )
            sent += 1
        except Exception:
            logger.warning("Failed to send stale warning for %s", spec.slug, exc_info=True)

    analytics.track(
        "stale_spec_check",
        properties={
            "stale_count": len(stale_specs),
            "notifications_sent": sent,
        },
    )

    logger.info("Stale spec check: %d stale, %d notified", len(stale_specs), sent)
    return {"stale_count": len(stale_specs), "sent": sent}


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
        result = asyncio.run(run_stale_check())
        logger.info("Stale spec check complete: %s", result)
    finally:
        analytics.shutdown()
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
