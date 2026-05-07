"""Per-team weekly digest builder and dispatcher for Slack."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from .blocks import (
    context_block,
    divider,
    header_block,
    section_block,
)
from .spec_loader import SpecInfo

logger = logging.getLogger(__name__)


@dataclass
class TeamDigestConfig:
    """Configuration for a team's digest channel."""

    channel: str
    schedule: str = "monday 09:00"


def build_digest_blocks(
    team: str,
    specs: list[SpecInfo],
    coverage_pct: int,
    coverage_delta: int,
) -> list[dict]:
    """Build weekly digest blocks for a team."""
    now = datetime.now(UTC)
    week_label = now.strftime("Week of %b %d, %Y")

    # Filter to team's specs
    team_specs = [s for s in specs if s.team == team]

    delta_emoji = (
        ":chart_with_upwards_trend:"
        if coverage_delta > 0
        else (":chart_with_downwards_trend:" if coverage_delta < 0 else "")
    )
    delta_text = (
        f" ({'+' if coverage_delta > 0 else ''}{coverage_delta}% from last week)"
        if coverage_delta
        else ""
    )

    blocks: list[dict] = [
        header_block(f":newspaper: Weekly Spec Digest — {team.title()} Team"),
        context_block([f"_{week_label}_"]),
        section_block(f"*Coverage:* {coverage_pct}%{delta_text} {delta_emoji}"),
    ]

    # Completed sections
    completed = []
    for spec in team_specs:
        for sec in spec.sections:
            if sec.status == "done":
                completed.append(f'- :white_check_mark: {spec.slug} §{sec.id} — "{sec.title}"')
    if completed:
        blocks.append(divider())
        blocks.append(section_block("*Completed:*"))
        blocks.append(section_block("\n".join(completed[:10])))

    # In progress
    in_progress = []
    for spec in team_specs:
        for sec in spec.sections:
            if sec.status == "in_progress":
                in_progress.append(
                    f"- :large_blue_circle: {spec.slug} §{sec.id} — {sec.acs_done}/{sec.acs_total} ACs done"
                )
    if in_progress:
        blocks.append(divider())
        blocks.append(section_block("*In Progress:*"))
        blocks.append(section_block("\n".join(in_progress[:10])))

    # New specs
    new_specs = [s for s in team_specs if s.status == "draft"]
    if new_specs:
        blocks.append(divider())
        blocks.append(section_block("*New Specs:*"))
        lines = [f"- :new: {s.slug} — draft by {s.owner}" for s in new_specs]
        blocks.append(section_block("\n".join(lines[:5])))

    return blocks


async def dispatch_team_digests(
    slack_client: object,
    team_configs: dict[str, TeamDigestConfig],
    specs: list[SpecInfo],
    coverage_by_team: dict[str, int] | None = None,
    previous_coverage: dict[str, int] | None = None,
) -> list[str]:
    """Send digest messages to each configured team's Slack channel.

    Teams without configuration are silently skipped.
    Returns list of team names that were successfully posted.
    """
    coverage_by_team = coverage_by_team or {}
    previous_coverage = previous_coverage or {}
    posted: list[str] = []

    for team_name, config in team_configs.items():
        if not config.channel:
            continue

        coverage_pct = coverage_by_team.get(team_name, 0)
        prev_pct = previous_coverage.get(team_name, coverage_pct)
        delta = coverage_pct - prev_pct

        blocks = build_digest_blocks(team_name, specs, coverage_pct, delta)

        try:
            await slack_client.chat_postMessage(  # type: ignore[attr-defined]
                channel=config.channel,
                blocks=blocks,
                text=f"Weekly Spec Digest — {team_name.title()} Team",
            )
            posted.append(team_name)
            logger.info("Posted digest for team %s to %s", team_name, config.channel)
        except Exception:
            logger.error(
                "Failed to post digest for team %s to %s",
                team_name,
                config.channel,
                exc_info=True,
            )

    return posted


def should_send_digest(schedule: str) -> bool:
    """Check if the digest should be sent based on current UTC day/time.

    Schedule format: "monday 09:00" (day-of-week + 24h UTC time).
    Returns True if the current UTC day, hour, and minute match exactly.
    """
    now = datetime.now(UTC)
    parts = schedule.lower().split()
    if len(parts) != 2:
        return False

    day_name, time_str = parts
    if now.strftime("%A").lower() != day_name:
        return False

    try:
        hour, minute = time_str.split(":")
        return now.hour == int(hour) and now.minute == int(minute)
    except (ValueError, IndexError):
        return False
