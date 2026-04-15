"""Proactive notification dispatch to Slack channels."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import time as dt_time
from typing import Any

from .blocks import (
    action_buttons,
    context_block,
    section_block,
    status_emoji,
)

logger = logging.getLogger(__name__)


@dataclass
class NotificationConfig:
    """Per-repo notification preferences from CANON.yaml."""

    spec_status_change: bool = True
    spec_created: bool = True
    coverage_regression: bool = True
    stale_spec_warning: bool = True
    pr_analysis_summary: bool = True
    ticket_sync_failure: bool = True
    review_requested: bool = True
    coverage_threshold: int = 80


def is_quiet_hours(
    now: dt_time,
    start: dt_time | None,
    end: dt_time | None,
) -> bool:
    """Check if current time falls within quiet hours."""
    if start is None or end is None:
        return False
    if start < end:
        return start <= now < end
    # Wraps midnight (e.g. 22:00 - 08:00)
    return now >= start or now < end


# Critical notification types that bypass quiet hours
_CRITICAL_TYPES = {"coverage_regression", "ticket_sync_failure"}


class NotificationDispatcher:
    """Sends proactive notifications to Slack channels."""

    def __init__(
        self,
        client: Any,
        default_channel: str = "",
        sre_channel: str = "",
        config: NotificationConfig | None = None,
        quiet_start: dt_time | None = None,
        quiet_end: dt_time | None = None,
        channel_overrides: dict[str, str] | None = None,
        activity_store: Any | None = None,
    ) -> None:
        self._client = client
        self._default_channel = default_channel
        self._sre_channel = sre_channel
        self._config = config or NotificationConfig()
        self._quiet_start = quiet_start
        self._quiet_end = quiet_end
        self._channel_overrides = channel_overrides or {}
        self._activity_store = activity_store

    def _is_quiet(self) -> bool:
        now = datetime.now(UTC).time()
        return is_quiet_hours(now, self._quiet_start, self._quiet_end)

    async def _post(
        self,
        channel: str,
        blocks: list[dict],
        text: str,
        notification_type: str,
        channel_override: str = "",
        spec_slug: str = "",
    ) -> None:
        # Priority: explicit override > CANON.yaml per-type channel > default
        target = channel_override or self._channel_overrides.get(notification_type, "") or channel
        if not target:
            logger.warning(
                "No channel configured for %s notification — dropping",
                notification_type,
            )
            return
        # Check if notification type is enabled
        if not getattr(self._config, notification_type, True):
            return
        # Check quiet hours (critical types bypass)
        if notification_type not in _CRITICAL_TYPES and self._is_quiet():
            return

        try:
            await self._client.chat_postMessage(channel=target, blocks=blocks, text=text)
        except Exception:
            logger.error(
                "Failed to post %s notification to %s",
                notification_type,
                target,
                exc_info=True,
            )
            if notification_type in _CRITICAL_TYPES:
                raise

    async def send_spec_status_change(
        self,
        spec_title: str,
        old_status: str,
        new_status: str,
        author: str,
        github_url: str,
        channel_override: str = "",
    ) -> None:
        """Notify when a spec status changes."""
        emoji = status_emoji(new_status)
        ctx_parts = [f"By: {author}"]
        if github_url:
            ctx_parts.append(f"<{github_url}|View on GitHub>")
        blocks = [
            section_block(
                f"{emoji} *Spec Status Changed*\n*{spec_title}*: {old_status} → {new_status}"
            ),
            context_block(ctx_parts),
        ]
        if github_url:
            blocks.append(action_buttons([("View on GitHub", "view_github", github_url)]))
        await self._post(
            self._default_channel,
            blocks,
            f"Spec {spec_title}: {old_status} → {new_status}",
            "spec_status_change",
            channel_override,
        )

    async def send_spec_created(
        self,
        spec_title: str,
        owner: str,
        github_url: str,
        channel_override: str = "",
    ) -> None:
        """Notify when a new spec is created."""
        blocks = [
            section_block(f":new: *New Spec Created*\n*{spec_title}* by {owner}"),
        ]
        if github_url:
            blocks.append(action_buttons([("View on GitHub", "view_github", github_url)]))
        await self._post(
            self._default_channel,
            blocks,
            f"New spec: {spec_title} by {owner}",
            "spec_created",
            channel_override,
        )

    async def send_coverage_regression(
        self,
        spec_title: str,
        coverage_pct: int,
        threshold: int,
        github_url: str,
        channel_override: str = "",
    ) -> None:
        """Notify on coverage regression (critical — bypasses quiet hours)."""
        blocks = [
            section_block(
                f":chart_with_downwards_trend: *Coverage Regression*\n"
                f"*{spec_title}* dropped to {coverage_pct}% (threshold: {threshold}%)"
            ),
        ]
        await self._post(
            self._sre_channel or self._default_channel,
            blocks,
            f"Coverage regression: {spec_title} at {coverage_pct}%",
            "coverage_regression",
            channel_override,
        )

    async def send_stale_spec_warning(
        self,
        spec_title: str,
        days_stale: int,
        threshold_days: int,
        github_url: str,
        channel_override: str = "",
    ) -> None:
        """Notify when a spec hasn't been updated past threshold."""
        blocks = [
            section_block(
                f":warning: *Stale Spec Warning*\n"
                f"*{spec_title}* — {days_stale}d since last update (threshold: {threshold_days}d)"
            ),
        ]
        await self._post(
            self._default_channel,
            blocks,
            f"Stale spec: {spec_title} ({days_stale}d)",
            "stale_spec_warning",
            channel_override,
        )

    async def send_pr_analysis_summary(
        self,
        pr_title: str,
        pr_number: int,
        specs_affected: list[str],
        acs_realized: int,
        github_url: str,
        channel_override: str = "",
    ) -> None:
        """Notify when a PR analysis completes."""
        specs_text = ", ".join(specs_affected) if specs_affected else "none"
        blocks = [
            section_block(
                f":mag: *PR Analysis Complete*\n"
                f"*#{pr_number} {pr_title}*\n"
                f"Specs affected: {specs_text} | ACs realized: {acs_realized}"
            ),
        ]
        if github_url:
            blocks.append(action_buttons([("View PR", "view_github", github_url)]))
        await self._post(
            self._default_channel,
            blocks,
            f"PR #{pr_number} analyzed: {len(specs_affected)} specs, {acs_realized} ACs",
            "pr_analysis_summary",
            channel_override,
        )

    async def send_ticket_sync_failure(
        self,
        system: str,
        error: str,
        channel_override: str = "",
    ) -> None:
        """Notify on ticket sync failure (critical — bypasses quiet hours)."""
        # Log full error server-side; only surface a safe summary to Slack
        # to avoid leaking credentials, connection strings, or internal hostnames.
        logger.error("Ticket sync failure [%s]: %s", system, error)
        safe_error = error[:80] if error else "unknown error"
        # Strip anything that looks like a URL or token
        if "://" in safe_error or "token" in safe_error.lower():
            safe_error = "Error (details in server logs)"
        blocks = [
            section_block(f":x: *Ticket Sync Failure*\nSystem: {system}\nError: {safe_error}"),
        ]
        await self._post(
            self._sre_channel or self._default_channel,
            blocks,
            f"Ticket sync failed: {system}",
            "ticket_sync_failure",
            channel_override,
        )

    async def send_review_requested(
        self,
        spec_title: str,
        requester: str,
        github_url: str,
        channel_override: str = "",
    ) -> None:
        """Notify when a spec review is requested."""
        blocks = [
            section_block(
                f":eyes: *Spec Review Requested*\n*{spec_title}* — requested by {requester}"
            ),
            action_buttons(
                [
                    ("Approve", "approve_spec", spec_title),
                    ("Request Changes", "request_changes", spec_title),
                    ("View on GitHub", "view_github", github_url),
                ]
            ),
        ]
        await self._post(
            self._default_channel,
            blocks,
            f"Review requested: {spec_title}",
            "review_requested",
            channel_override,
        )
