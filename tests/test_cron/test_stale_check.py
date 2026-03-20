"""Tests for stale check cron job."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from canon.cron.stale_check import run_stale_check


class TestRunStaleCheck:
    async def test_exits_without_credentials(self):
        """Should exit when GitHub credentials are missing."""
        with patch("canon.cron.stale_check.Settings") as MockSettings:
            MockSettings.return_value = MagicMock(
                gh_app_id="",
                gh_private_key="",
                gh_installation_id="",
                database_url="",
            )
            with pytest.raises(SystemExit):
                await run_stale_check()

    async def test_exits_without_database(self):
        """Should exit when DATABASE_URL is missing."""
        with patch("canon.cron.stale_check.Settings") as MockSettings:
            MockSettings.return_value = MagicMock(
                gh_app_id="123",
                gh_private_key="key",
                gh_installation_id="456",
                database_url="",
            )
            with pytest.raises(SystemExit):
                await run_stale_check()
