"""Tests for the weekly SRE digest cron job."""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, patch

from canon.cron.weekly_digest import run_weekly_digest


def _make_settings(**overrides):
    defaults = {
        "slack_alerts_enabled": True,
        "sre_weekly_digest_enabled": True,
        "slack_alerts_webhook_url": "https://hooks.slack.com/test",
    }
    defaults.update(overrides)
    return type("S", (), defaults)()


class TestRunWeeklyDigest:
    async def test_skips_when_slack_alerts_disabled(self):
        with patch(
            "canon.cron.weekly_digest.Settings",
            return_value=_make_settings(slack_alerts_enabled=False),
        ):
            result = await run_weekly_digest()

        assert result == {"skipped": True}

    async def test_skips_when_digest_disabled(self):
        with patch(
            "canon.cron.weekly_digest.Settings",
            return_value=_make_settings(sre_weekly_digest_enabled=False),
        ):
            result = await run_weekly_digest()

        assert result == {"skipped": True}

    async def test_sends_digest_to_slack(self):
        mock_alerter = AsyncMock()
        mock_alerter.send_text = AsyncMock()
        mock_alerter.close = AsyncMock()

        with (
            patch(
                "canon.cron.weekly_digest.Settings",
                return_value=_make_settings(),
            ),
            patch(
                "canon.cron.weekly_digest.SlackAlerter",
                return_value=mock_alerter,
            ),
            patch("canon.cron.weekly_digest.format_digest_message", return_value="digest text"),
            patch("canon.cron.weekly_digest.analytics"),
        ):
            result = await run_weekly_digest()

        assert result == {"sent": True}
        mock_alerter.send_text.assert_awaited_once_with("digest text")
        mock_alerter.close.assert_awaited_once()

    async def test_tracks_analytics_event(self):
        mock_alerter = AsyncMock()
        mock_alerter.send_text = AsyncMock()
        mock_alerter.close = AsyncMock()

        with (
            patch(
                "canon.cron.weekly_digest.Settings",
                return_value=_make_settings(),
            ),
            patch(
                "canon.cron.weekly_digest.SlackAlerter",
                return_value=mock_alerter,
            ),
            patch("canon.cron.weekly_digest.format_digest_message", return_value="msg"),
            patch("canon.cron.weekly_digest.analytics") as mock_analytics,
        ):
            await run_weekly_digest()

        mock_analytics.track.assert_called_once_with(
            "weekly_digest_sent",
            properties={"alerts_count": 0},
        )

    async def test_closes_alerter_even_on_send_failure(self):
        mock_alerter = AsyncMock()
        mock_alerter.send_text = AsyncMock(side_effect=RuntimeError("webhook down"))
        mock_alerter.close = AsyncMock()

        with (
            patch(
                "canon.cron.weekly_digest.Settings",
                return_value=_make_settings(),
            ),
            patch(
                "canon.cron.weekly_digest.SlackAlerter",
                return_value=mock_alerter,
            ),
            patch("canon.cron.weekly_digest.format_digest_message", return_value="msg"),
            patch("canon.cron.weekly_digest.analytics"),
            contextlib.suppress(RuntimeError),
        ):
            await run_weekly_digest()

        mock_alerter.close.assert_awaited_once()
