"""Tests for coverage snapshot cron job."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from canon.cron.coverage_snapshot import run_coverage_snapshot


class TestRunCoverageSnapshot:
    async def test_exits_without_credentials(self):
        """Should exit when GitHub credentials are missing."""
        with patch("canon.cron.coverage_snapshot.Settings") as MockSettings:
            MockSettings.return_value = MagicMock(
                gh_app_id="",
                gh_private_key="",
                gh_installation_id="",
                database_url="",
            )
            with pytest.raises(SystemExit):
                await run_coverage_snapshot()

    async def test_exits_without_database(self):
        """Should exit when DATABASE_URL is missing."""
        with patch("canon.cron.coverage_snapshot.Settings") as MockSettings:
            MockSettings.return_value = MagicMock(
                gh_app_id="123",
                gh_private_key="key",
                gh_installation_id="456",
                database_url="",
            )
            with pytest.raises(SystemExit):
                await run_coverage_snapshot()
