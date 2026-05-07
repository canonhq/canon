"""One-time-prompt state for Slack DM nudges (e.g., link your GitHub)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PromptStore:
    """Tracks whether the bot has sent a particular nudge to a user before.

    Backed by the `slack_dm_prompts` table. Failures here are best-effort:
    a missing prompt record means the bot will nudge the user, which is
    safer than a stuck-state where the user never gets prompted.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def has_been_prompted(self, workspace_id: str, user_id: str, prompt_type: str) -> bool:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchval(
                    """
                    SELECT sent_at FROM slack_dm_prompts
                    WHERE workspace_id = $1 AND user_id = $2 AND prompt_type = $3
                    """,
                    workspace_id,
                    user_id,
                    prompt_type,
                )
            return row is not None
        except Exception:
            logger.warning(
                "PromptStore.has_been_prompted failed for %s/%s/%s",
                workspace_id,
                user_id,
                prompt_type,
                exc_info=True,
            )
            return False  # safer to re-prompt than silently swallow

    async def mark_prompted(self, workspace_id: str, user_id: str, prompt_type: str) -> None:
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO slack_dm_prompts (workspace_id, user_id, prompt_type)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (workspace_id, user_id, prompt_type) DO NOTHING
                    """,
                    workspace_id,
                    user_id,
                    prompt_type,
                )
        except Exception:
            logger.warning(
                "PromptStore.mark_prompted failed for %s/%s/%s",
                workspace_id,
                user_id,
                prompt_type,
                exc_info=True,
            )
