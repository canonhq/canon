"""Cleanup expired API keys — deletes keys that expired 30+ days ago.

Run as: python -m canon.cron.cleanup_keys

For K8s CronJob: set CMD override to ["python", "-m", "canon.cron.cleanup_keys"]
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .. import otel_logging
from ..alerts.cron_utils import tracked_cron
from ..db import UserStore, close_pool, create_pool
from ..settings import Settings

logger = logging.getLogger(__name__)


@tracked_cron("cleanup_expired_api_keys")
async def run_cleanup() -> int:
    """Delete expired API keys.  Returns the number of keys deleted."""
    settings = Settings()

    if not settings.database_url:
        logger.error("DATABASE_URL is required for key cleanup")
        sys.exit(1)

    pool = await create_pool(settings.database_url)
    try:
        user_store = UserStore(pool)
        deleted = await user_store.delete_expired_keys()
        return deleted
    finally:
        await close_pool(pool)


def main() -> None:
    """CLI entry point for the expired key cleanup cron job."""
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

    try:
        deleted = asyncio.run(run_cleanup())
        logger.info("Expired key cleanup complete: %d keys deleted", deleted)
    finally:
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
