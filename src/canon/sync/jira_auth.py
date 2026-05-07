"""Shared Jira OAuth token refresh logic.

Used by the token refresh cron, the integration test endpoint, and the Jira sync adapter.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"


async def refresh_jira_token(
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> dict | None:
    """Exchange a Jira refresh token for new access + refresh tokens.

    Returns the token response dict on success, None on failure.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            ATLASSIAN_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
        )

    if resp.status_code != 200:
        logger.warning(
            "Jira token refresh failed: HTTP %d — %s",
            resp.status_code,
            resp.text[:200],
        )
        return None

    return resp.json()
