"""Tests for the audit retention cron job."""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, patch

from canon.cron.audit_retention import run_audit_retention


def _make_settings(**overrides):
    defaults = {
        "database_url": "postgres://test",
        "admin_audit_retention_days": 90,
    }
    defaults.update(overrides)
    return type("S", (), defaults)()


class TestRunAuditRetention:
    async def test_deletes_old_events(self):
        mock_pool = AsyncMock()
        mock_store = AsyncMock()
        mock_store.delete_older_than = AsyncMock(return_value=42)

        with (
            patch(
                "canon.cron.audit_retention.Settings",
                return_value=_make_settings(),
            ),
            patch("canon.cron.audit_retention.create_pool", return_value=mock_pool),
            patch("canon.cron.audit_retention.close_pool", new=AsyncMock()),
            patch("canon.cron.audit_retention.AuditStore", return_value=mock_store),
        ):
            count = await run_audit_retention()

        assert count == 42
        mock_store.delete_older_than.assert_awaited_once_with(days=90)

    async def test_returns_zero_when_no_database_url(self):
        with patch(
            "canon.cron.audit_retention.Settings",
            return_value=_make_settings(database_url=""),
        ):
            count = await run_audit_retention()

        assert count == 0

    async def test_uses_configured_retention_days(self):
        mock_pool = AsyncMock()
        mock_store = AsyncMock()
        mock_store.delete_older_than = AsyncMock(return_value=10)

        with (
            patch(
                "canon.cron.audit_retention.Settings",
                return_value=_make_settings(admin_audit_retention_days=30),
            ),
            patch("canon.cron.audit_retention.create_pool", return_value=mock_pool),
            patch("canon.cron.audit_retention.close_pool", new=AsyncMock()),
            patch("canon.cron.audit_retention.AuditStore", return_value=mock_store),
        ):
            count = await run_audit_retention()

        assert count == 10
        mock_store.delete_older_than.assert_awaited_once_with(days=30)

    async def test_pool_closed_on_error(self):
        mock_pool = AsyncMock()
        mock_store = AsyncMock()
        mock_store.delete_older_than = AsyncMock(side_effect=RuntimeError("db down"))
        mock_close = AsyncMock()

        with (
            patch(
                "canon.cron.audit_retention.Settings",
                return_value=_make_settings(),
            ),
            patch("canon.cron.audit_retention.create_pool", return_value=mock_pool),
            patch("canon.cron.audit_retention.close_pool", mock_close),
            patch("canon.cron.audit_retention.AuditStore", return_value=mock_store),
            contextlib.suppress(RuntimeError),
        ):
            await run_audit_retention()

        mock_close.assert_awaited_once_with(mock_pool)
