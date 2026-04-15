"""Slack user - GitHub identity mapping store."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class IdentityStore:
    """Maps Slack user IDs to GitHub logins.

    Stores mappings in-memory with optional DB persistence.
    When no DB pool is provided, mappings are ephemeral (lost on restart).
    """

    def __init__(self, db_pool: Any = None) -> None:
        self._pool = db_pool
        self._cache: dict[str, str] = {}  # slack_user_id -> github_login
        self._loaded = False

    async def _ensure_table(self) -> None:
        """Create the identity mapping table if it doesn't exist."""
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS slack_identity_map (
                    slack_user_id TEXT PRIMARY KEY,
                    github_login TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

    async def _load_from_db(self) -> None:
        """Load all mappings from DB into cache."""
        if self._pool is None or self._loaded:
            return
        try:
            await self._ensure_table()
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT slack_user_id, github_login FROM slack_identity_map"
                )
                for row in rows:
                    self._cache[row["slack_user_id"]] = row["github_login"]
            self._loaded = True
        except Exception:
            logger.warning("Failed to load identity mappings from DB", exc_info=True)

    async def link(self, slack_user_id: str, github_login: str) -> None:
        """Link a Slack user to a GitHub login."""
        self._cache[slack_user_id] = github_login
        if self._pool is not None:
            try:
                await self._ensure_table()
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO slack_identity_map (slack_user_id, github_login)
                        VALUES ($1, $2)
                        ON CONFLICT (slack_user_id) DO UPDATE SET github_login = $2
                        """,
                        slack_user_id,
                        github_login,
                    )
            except Exception:
                logger.warning("Failed to persist identity mapping", exc_info=True)

    async def unlink(self, slack_user_id: str) -> bool:
        """Remove a Slack-GitHub mapping. Returns True if a mapping existed."""
        removed = self._cache.pop(slack_user_id, None) is not None
        if self._pool is not None:
            try:
                await self._ensure_table()
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM slack_identity_map WHERE slack_user_id = $1",
                        slack_user_id,
                    )
            except Exception:
                logger.warning("Failed to remove identity mapping from DB", exc_info=True)
        return removed

    async def get_github_login(self, slack_user_id: str) -> str | None:
        """Get the GitHub login for a Slack user, or None."""
        await self._load_from_db()
        return self._cache.get(slack_user_id)

    async def get_github_login_for_slack(self, slack_user_id: str) -> str | None:
        """Alias for get_github_login (matches registry interface)."""
        return await self.get_github_login(slack_user_id)
