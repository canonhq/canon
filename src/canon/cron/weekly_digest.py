"""Weekly SRE digest cron job.

Usage: python -m canon.cron.weekly_digest
"""

from __future__ import annotations

import asyncio
import logging

from canon import analytics, otel_logging
from canon.alerts.cron_utils import tracked_cron
from canon.alerts.digest import WeeklyDigest, format_digest_message
from canon.alerts.slack import SlackAlerter
from canon.settings import Settings

logger = logging.getLogger(__name__)


@tracked_cron("weekly_sre_digest")
async def run_weekly_digest() -> dict:
    settings = Settings()

    if not settings.slack_alerts_enabled:
        logger.info("Slack alerts not configured — skipping weekly digest")
        return {"skipped": True}

    if not settings.sre_weekly_digest_enabled:
        logger.info("Weekly digest disabled — skipping")
        return {"skipped": True}

    # TODO: Query PostHog API for actual metrics once dashboard is set up.
    # For now, this creates the skeleton that will be filled in with real data.
    digest = WeeklyDigest(
        total_errors_this_week=0,
        total_errors_last_week=0,
        top_errors=[],
        new_errors_count=0,
        cron_success_rate=100.0,
        webhook_p95_ms=0,
        open_triage_issues=0,
    )

    message = format_digest_message(digest)
    alerter = SlackAlerter(webhook_url=settings.slack_alerts_webhook_url)
    try:
        await alerter.send_text(message)
    finally:
        await alerter.close()

    logger.info("Weekly SRE digest sent to Slack")
    return {"sent": True}


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
        result = asyncio.run(run_weekly_digest())
        logger.info("Weekly digest complete: %s", result)
    finally:
        analytics.shutdown()
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
