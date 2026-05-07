"""Slack thread source — searches messages in channels the asking user is a member of."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from canon_slack.work_context.models import WorkContextItem

logger = logging.getLogger(__name__)


_MAX_PARALLEL_CHANNEL_FETCHES = 8
_MESSAGES_PER_CHANNEL = 50


def _matches_query(text: str, query_tokens: set[str]) -> bool:
    """True if any query token appears in the message text (case-insensitive)."""
    if not query_tokens:
        return True
    lowered = text.lower()
    return any(t in lowered for t in query_tokens)


class SlackThreadSource:
    """Returns recent Slack messages matching the query, scoped to channels the asking
    user is a member of.

    Uses `conversations_history` per channel (bot-token compatible, requires
    `channels:history` and `groups:history` scopes) plus client-side keyword filtering.
    Slack's `search.messages` API would be more efficient but requires a user token.
    """

    name = "slack_thread"

    def __init__(self, slack_client: Any, workspace_id: str, user_id: str) -> None:
        self._slack = slack_client
        self._workspace_id = workspace_id
        self._user_id = user_id

    def enabled_for_org(self, org_id: str) -> bool:
        # Skip cleanly when no slack client is wired (tests, non-Slack
        # deployments). Without this the coordinator runs us, fetch raises
        # AttributeError on None, and we log a warning on every request.
        return self._slack is not None

    async def fetch(self, query: str, recency_days: int, cap: int) -> list[WorkContextItem]:
        # 1. Get the user's channel IDs
        try:
            convs = await self._slack.users_conversations(
                user=self._user_id,
                types="public_channel,private_channel",
                limit=200,
            )
            user_channel_ids = [c["id"] for c in convs.get("channels", [])]
        except Exception:
            logger.warning(
                "SlackThreadSource: users_conversations failed for %s",
                self._user_id,
                exc_info=True,
            )
            return []

        if not user_channel_ids:
            return []

        # 2. Fetch recent history per channel in parallel (bounded)
        oldest_ts = (datetime.now(UTC) - timedelta(days=recency_days)).timestamp()
        query_tokens = {t for t in query.lower().split() if len(t) > 2}

        sem = asyncio.Semaphore(_MAX_PARALLEL_CHANNEL_FETCHES)

        async def _fetch_channel(channel_id: str) -> list[WorkContextItem]:
            async with sem:
                try:
                    history = await self._slack.conversations_history(
                        channel=channel_id,
                        oldest=str(oldest_ts),
                        limit=_MESSAGES_PER_CHANNEL,
                    )
                except Exception:
                    logger.debug(
                        "SlackThreadSource: conversations_history failed for %s",
                        channel_id,
                        exc_info=True,
                    )
                    return []

            channel_messages: list[WorkContextItem] = []
            for m in history.get("messages", []):
                text = m.get("text") or ""
                if not _matches_query(text, query_tokens):
                    continue
                ts_str = m.get("ts")
                if not ts_str:
                    continue
                try:
                    ts_float = float(ts_str)
                    permalink = m.get("permalink") or _build_permalink(
                        self._workspace_id, channel_id, ts_str
                    )
                    channel_messages.append(
                        WorkContextItem(
                            source=self.name,
                            title=f"#{channel_id}",  # channel name resolved later if needed
                            summary=text[:300],
                            url=permalink,
                            timestamp=datetime.fromtimestamp(ts_float, tz=UTC),
                            metadata={
                                "channel_id": channel_id,
                                "user_id": m.get("user"),
                            },
                        )
                    )
                except Exception:
                    logger.debug("Skipping malformed slack message", exc_info=True)
            return channel_messages

        results = await asyncio.gather(
            *[_fetch_channel(cid) for cid in user_channel_ids],
            return_exceptions=False,
        )

        # Flatten + sort by timestamp desc + cap
        all_items: list[WorkContextItem] = [
            item for channel_items in results for item in channel_items
        ]
        all_items.sort(key=lambda i: i.timestamp, reverse=True)
        return all_items[:cap]


def _build_permalink(workspace_id: str, channel_id: str, ts: str) -> str:
    """Best-effort permalink synthesis when message lacks one."""
    # Slack permalink format: https://<workspace>.slack.com/archives/<channel>/p<ts-no-dot>
    if not workspace_id:
        return ""
    ts_compact = ts.replace(".", "")
    return f"https://{workspace_id}.slack.com/archives/{channel_id}/p{ts_compact}"
