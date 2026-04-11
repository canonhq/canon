"""CronJob: delete audit events older than retention period.

Run as: python -m canon.cron.audit_retention

For K8s CronJob: set CMD override to ["python", "-m", "canon.cron.audit_retention"]
"""

from __future__ import annotations

import asyncio
import logging

from .. import otel_logging
from ..admin.audit import AuditStore
from ..alerts.cron_utils import tracked_cron
from ..db import close_pool, create_pool
from ..settings import Settings

logger = logging.getLogger(__name__)


@tracked_cron("audit_retention")
async def run_audit_retention() -> int:
    """Delete audit events older than the configured retention period.

    Returns the number of deleted rows.
    """
    settings = Settings()

    if not settings.database_url:
        logger.warning("No DATABASE_URL configured, skipping audit retention")
        return 0

    pool = await create_pool(settings.database_url)
    try:
        store = AuditStore(pool)
        days = settings.admin_audit_retention_days
        deleted = await store.delete_older_than(days=days)
        logger.info("Audit retention: deleted %d events older than %d days", deleted, days)
        return deleted
    finally:
        await close_pool(pool)


def main() -> None:
    """CLI entry point for the audit retention cron job."""
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
        asyncio.run(run_audit_retention())
    finally:
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
