"""Tests for the expired key cleanup cron job."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from canon.cron.cleanup_keys import run_cleanup


class TestRunCleanup:
    async def test_deletes_expired_keys(self):
        mock_pool = AsyncMock()
        mock_user_store = AsyncMock()
        mock_user_store.delete_expired_keys = AsyncMock(return_value=5)

        with (
            patch(
                "canon.cron.cleanup_keys.Settings",
                return_value=type("S", (), {"database_url": "postgres://test"})(),
            ),
            patch("canon.cron.cleanup_keys.create_pool", return_value=mock_pool),
            patch("canon.cron.cleanup_keys.close_pool", return_value=None),
            patch("canon.cron.cleanup_keys.UserStore", return_value=mock_user_store),
        ):
            count = await run_cleanup()

        assert count == 5
        mock_user_store.delete_expired_keys.assert_awaited_once()

    async def test_exits_when_no_database_url(self):
        with (
            patch(
                "canon.cron.cleanup_keys.Settings",
                return_value=type("S", (), {"database_url": ""})(),
            ),
            pytest.raises(SystemExit),
        ):
            await run_cleanup()
