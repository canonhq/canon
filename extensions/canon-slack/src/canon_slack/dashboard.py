"""Dashboard block builder and auto-refresh for /canon dashboard."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .blocks import (
    action_buttons,
    context_block,
    divider,
    header_block,
    progress_bar,
    section_block,
    status_emoji,
)
from .spec_loader import SpecInfo

logger = logging.getLogger(__name__)


def build_dashboard_blocks(
    specs: list[SpecInfo],
    stats: dict,
    org_name: str = "Canon",
) -> list[dict]:
    """Build the full dashboard message blocks."""
    now = datetime.now(UTC).strftime("%b %d, %Y at %I:%M %p UTC")

    blocks: list[dict] = [
        header_block(f":bar_chart: Spec Dashboard — {org_name}"),
        context_block([f"_Updated: {now}_"]),
    ]

    # Coverage score
    pct_done = stats["pct_done"]
    color = (
        ":large_green_circle:"
        if pct_done >= 70
        else ":yellow_circle:"
        if pct_done >= 40
        else ":red_circle:"
    )
    blocks.append(section_block(f"*Specs Complete:* {pct_done}% {color}"))

    # Coverage by team
    if stats["teams"]:
        blocks.append(divider())
        blocks.append(section_block("*Coverage by Team:*"))
        for team in stats["teams"]:
            team_specs = [s for s in specs if s.team == team]
            done = sum(1 for s in team_specs if s.status in ("done", "approved"))
            total = len(team_specs)
            bar = progress_bar(done, total)
            blocks.append(section_block(f"{team}  {bar}"))

    # Recently updated
    recent = sorted(
        [s for s in specs if s.updated],
        key=lambda s: s.updated,
        reverse=True,
    )[:5]
    if recent:
        blocks.append(divider())
        blocks.append(section_block("*Recently Updated:*"))
        lines = []
        for s in recent:
            emoji = status_emoji(s.status)
            lines.append(f"- {emoji} {s.slug} — {s.status}")
        blocks.append(section_block("\n".join(lines)))

    # Refresh button
    blocks.append(action_buttons([("Refresh", "dashboard_refresh", "refresh")]))

    return blocks


async def auto_refresh_dashboard(
    slack_client: object,
    channel: str,
    pinned_ts: str | None,
    specs: list[SpecInfo],
    stats: dict,
) -> str | None:
    """Update the existing pinned dashboard message, or post a new one.

    Returns the message timestamp of the updated/posted message.
    """
    blocks = build_dashboard_blocks(specs, stats)
    text = "Canon Spec Dashboard (auto-refresh)"

    try:
        if pinned_ts:
            await slack_client.chat_update(  # type: ignore[attr-defined]
                channel=channel,
                ts=pinned_ts,
                blocks=blocks,
                text=text,
            )
            return pinned_ts
        else:
            result = await slack_client.chat_postMessage(  # type: ignore[attr-defined]
                channel=channel,
                blocks=blocks,
                text=text,
            )
            return result.get("ts")
    except Exception:
        logger.error("Auto-refresh dashboard failed for channel %s", channel, exc_info=True)
        return None
