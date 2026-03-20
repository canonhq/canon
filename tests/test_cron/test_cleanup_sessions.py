"""Tests for the expired session cleanup cron job."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from canon.cron.cleanup_sessions import run_cleanup


class TestRunCleanup:
    async def test_deletes_expired_sessions(self):
        mock_pool = AsyncMock()
        mock_session_store = AsyncMock()
        mock_session_store.delete_expired_sessions = AsyncMock(return_value=7)

        with (
            patch(
                "canon.cron.cleanup_sessions.Settings",
                return_value=type("S", (), {"database_url": "postgres://test"})(),
            ),
            patch("canon.cron.cleanup_sessions.create_pool", return_value=mock_pool),
            patch("canon.cron.cleanup_sessions.close_pool", return_value=None),
            patch("canon.cron.cleanup_sessions.SessionStore", return_value=mock_session_store),
        ):
            count = await run_cleanup()

        assert count == 7
        mock_session_store.delete_expired_sessions.assert_awaited_once()

    async def test_exits_when_no_database_url(self):
        with (
            patch(
                "canon.cron.cleanup_sessions.Settings",
                return_value=type("S", (), {"database_url": ""})(),
            ),
            pytest.raises(SystemExit),
        ):
            await run_cleanup()
