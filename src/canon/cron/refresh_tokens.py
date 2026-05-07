"""Proactive OAuth token refresh — keeps Jira tokens alive before expiry.

Atlassian access tokens expire after 1 hour. This cron job refreshes them
at ~45 minutes to avoid mid-request 401 errors.

Run as: python -m canon.cron.refresh_tokens

For K8s CronJob: set CMD override to ["python", "-m", "canon.cron.refresh_tokens"]
Schedule: every 30 minutes (tokens expire at 60 min, refresh at 45 min threshold).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time

from .. import otel_logging
from ..alerts.cron_utils import tracked_cron
from ..billing.encryption import decrypt_api_key, encrypt_api_key
from ..db import close_pool, create_pool
from ..settings import Settings
from ..sync.jira_auth import refresh_jira_token

logger = logging.getLogger(__name__)

# Refresh tokens older than this (seconds). Atlassian access tokens expire at
# 3600s; refreshing at 2700s (45 min) gives a comfortable buffer.
REFRESH_THRESHOLD_SECONDS = 2700

# For integrations in error/needs_reauth, retry sooner (5 min) to speed recovery.
ERROR_RECOVERY_THRESHOLD_SECONDS = 300


@tracked_cron("refresh_integration_tokens")
async def run_refresh() -> int:
    """Refresh expiring Jira OAuth tokens. Returns count of tokens refreshed."""
    settings = Settings()

    if not settings.database_url:
        logger.error("DATABASE_URL is required for token refresh")
        sys.exit(1)

    if not settings.jira_oauth_client_id or not settings.jira_oauth_client_secret:
        logger.info("Jira OAuth client credentials not configured — skipping refresh")
        return 0

    encryption_key = settings.api_key_encryption_key
    if not encryption_key:
        logger.error("API_KEY_ENCRYPTION_KEY is required to decrypt integration configs")
        sys.exit(1)

    pool = await create_pool(settings.database_url)
    refreshed = 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, org_login, encrypted_config, provider_metadata, status
                FROM org_integrations
                WHERE provider = 'jira' AND status IN ('active', 'error', 'needs_reauth')
                """
            )

        now = time.time()

        for row in rows:
            org_login = row["org_login"]
            try:
                config = json.loads(decrypt_api_key(row["encrypted_config"], encryption_key))
            except Exception:
                logger.warning("Failed to decrypt Jira config for org %s", org_login)
                continue

            refresh_token = config.get("refresh_token", "")
            if not refresh_token:
                logger.info("No refresh_token stored for org %s — skipping", org_login)
                continue

            # Check if refresh is needed based on last refresh timestamp.
            # Use a shorter threshold for broken integrations to speed recovery.
            metadata = json.loads(row["provider_metadata"]) if row["provider_metadata"] else {}
            last_refreshed = metadata.get("token_refreshed_at", 0)
            age = now - last_refreshed
            threshold = (
                ERROR_RECOVERY_THRESHOLD_SECONDS
                if row["status"] in ("error", "needs_reauth")
                else REFRESH_THRESHOLD_SECONDS
            )
            if age < threshold:
                logger.debug(
                    "Jira token for org %s refreshed %ds ago — skipping",
                    org_login,
                    int(age),
                )
                continue

            # Refresh the token
            result = await refresh_jira_token(
                refresh_token=refresh_token,
                client_id=settings.jira_oauth_client_id,
                client_secret=settings.jira_oauth_client_secret,
            )

            if result is None:
                # Mark as needs_reauth so the UI shows a warning
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE org_integrations SET status = 'needs_reauth', updated_at = now() "
                        "WHERE id = $1",
                        row["id"],
                    )
                logger.warning(
                    "Jira token refresh failed for org %s — marked needs_reauth", org_login
                )
                continue

            # Persist new tokens and recover status if needed
            new_config = {
                **config,
                "access_token": result["access_token"],
                "refresh_token": result.get("refresh_token", refresh_token),
            }
            encrypted = encrypt_api_key(json.dumps(new_config), encryption_key)
            metadata["token_refreshed_at"] = now

            prev_status = row["status"]
            new_status = "active" if prev_status in ("error", "needs_reauth") else prev_status

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE org_integrations
                    SET encrypted_config = $1, provider_metadata = $2,
                        status = $3, updated_at = now()
                    WHERE id = $4
                    """,
                    encrypted,
                    json.dumps(metadata),
                    new_status,
                    row["id"],
                )

            refreshed += 1
            if prev_status != new_status:
                logger.info(
                    "Jira token refreshed for org %s — status recovered from %s to active",
                    org_login,
                    prev_status,
                )
            else:
                logger.info("Jira token refreshed for org %s", org_login)

    finally:
        await close_pool(pool)

    return refreshed


def main() -> None:
    """CLI entry point for the token refresh cron job."""
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
        refreshed = asyncio.run(run_refresh())
        logger.info("Token refresh complete: %d tokens refreshed", refreshed)
    finally:
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
