"""Content reconciliation cron job — syncs all specs from GitHub to Postgres.

Run as: python -m canon.cron.content_reconcile

For K8s CronJob: set CMD override to ["python", "-m", "canon.cron.content_reconcile"]
"""

from __future__ import annotations

import asyncio
import logging

from ..alerts.cron_utils import tracked_cron
from ..db import create_pool
from ..db.content_cache_store import ContentCacheStore
from ..db.registry import InstallationRegistry
from ..db.schema import ensure_schema
from ..github.client import GitHubClient
from ..settings import Settings
from ..sync.content_sync import ContentSyncEngine

logger = logging.getLogger(__name__)


@tracked_cron("content_reconcile")
async def run_content_reconciliation() -> dict:
    """Reconcile all specs from GitHub into the Postgres content cache.

    Returns summary stats.
    """
    settings = Settings()

    if not settings.gh_app_id or not settings.gh_private_key:
        raise RuntimeError("Missing GitHub App credentials for content reconciliation")

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for content reconciliation")

    pool = await create_pool(settings.database_url)
    await ensure_schema(pool, settings.database_url)

    try:
        content_store = ContentCacheStore(pool)
        registry = InstallationRegistry(pool)

        # Get all active installations
        installations_raw = await registry.get_active_installations()
        installations = [{"id": inst.installation_id, "repos": []} for inst in installations_raw]

        if not installations:
            logger.info("No active installations found, nothing to reconcile")
            return {"installations": 0, "synced": 0, "errors": 0}

        # Each installation needs its own GitHub client for correct auth.
        # reconcile_all handles per-installation client forking internally.
        client = GitHubClient(
            app_id=settings.gh_app_id,
            private_key=settings.gh_private_key,
            installation_id=str(installations[0]["id"]),
        )

        engine = ContentSyncEngine(content_store, client)

        logger.info("Starting content reconciliation for %d installations", len(installations))
        stats = await engine.reconcile_all(installations)

        if stats.errors:
            for err in stats.errors:
                logger.warning("Reconciliation error: %s", err)

        result = {
            "installations": len(installations),
            "synced": stats.specs_synced,
            "skipped": stats.specs_skipped,
            "deleted": stats.specs_deleted,
            "github_api_calls": stats.github_api_calls,
            "errors": len(stats.errors),
        }
        logger.info("Content reconciliation complete: %s", result)
        return result
    finally:
        from ..db import close_pool

        await close_pool(pool)


def main() -> None:
    from .. import otel_logging

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
        asyncio.run(run_content_reconciliation())
    finally:
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
