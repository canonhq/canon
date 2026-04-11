"""Cleanup stale sessions — deletes sessions that expired more than 30 days ago.

Run as: python -m canon.cron.cleanup_sessions

For K8s CronJob: set CMD override to ["python", "-m", "canon.cron.cleanup_sessions"]
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .. import otel_logging
from ..alerts.cron_utils import tracked_cron
from ..db import SessionStore, close_pool, create_pool
from ..settings import Settings

logger = logging.getLogger(__name__)


@tracked_cron("cleanup_expired_sessions")
async def run_cleanup() -> int:
    """Delete expired sessions.  Returns the number of sessions deleted."""
    settings = Settings()

    if not settings.database_url:
        logger.error("DATABASE_URL is required for session cleanup")
        sys.exit(1)

    pool = await create_pool(settings.database_url)
    try:
        session_store = SessionStore(pool)
        deleted = await session_store.delete_expired_sessions()
        return deleted
    finally:
        await close_pool(pool)


def main() -> None:
    """CLI entry point for the expired session cleanup cron job."""
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
        logger.info("Expired session cleanup complete: %d sessions deleted", deleted)
    finally:
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
