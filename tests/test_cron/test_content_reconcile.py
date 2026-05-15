"""Tests for the content reconciliation cron job."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from canon.cron.content_reconcile import run_content_reconciliation


def _make_settings(**overrides):
    defaults = {
        "gh_app_id": "123",
        "gh_private_key": "key",
        "database_url": "postgres://test",
    }
    defaults.update(overrides)
    return type("S", (), defaults)()


@dataclass
class FakeSyncStats:
    specs_synced: int = 3
    specs_skipped: int = 1
    specs_deleted: int = 0
    github_api_calls: int = 10
    errors: list[str] = field(default_factory=list)


@dataclass
class FakeInstallation:
    installation_id: int = 100
    org_login: str = "acme"


class TestRunContentReconciliation:
    async def test_raises_without_github_credentials(self):
        with (
            patch(
                "canon.cron.content_reconcile.Settings",
                return_value=_make_settings(gh_app_id="", gh_private_key=""),
            ),
            pytest.raises(RuntimeError, match="Missing GitHub App credentials"),
        ):
            await run_content_reconciliation()

    async def test_raises_without_database_url(self):
        with (
            patch(
                "canon.cron.content_reconcile.Settings",
                return_value=_make_settings(database_url=""),
            ),
            pytest.raises(RuntimeError, match="DATABASE_URL is required"),
        ):
            await run_content_reconciliation()

    async def test_returns_zeros_when_no_installations(self):
        mock_pool = AsyncMock()
        mock_registry = AsyncMock()
        mock_registry.get_active_installations = AsyncMock(return_value=[])

        with (
            patch(
                "canon.cron.content_reconcile.Settings",
                return_value=_make_settings(),
            ),
            patch("canon.cron.content_reconcile.create_pool", return_value=mock_pool),
            patch("canon.cron.content_reconcile.ensure_schema", new=AsyncMock()),
            patch("canon.cron.content_reconcile.ContentCacheStore"),
            patch(
                "canon.cron.content_reconcile.InstallationRegistry",
                return_value=mock_registry,
            ),
            patch("canon.db.close_pool", new=AsyncMock()),
        ):
            result = await run_content_reconciliation()

        assert result == {"installations": 0, "synced": 0, "errors": 0}

    async def test_reconciles_active_installations(self):
        mock_pool = AsyncMock()
        mock_registry = AsyncMock()
        mock_registry.get_active_installations = AsyncMock(
            return_value=[FakeInstallation(installation_id=100)]
        )

        mock_engine = AsyncMock()
        mock_engine.reconcile_all = AsyncMock(return_value=FakeSyncStats())

        with (
            patch(
                "canon.cron.content_reconcile.Settings",
                return_value=_make_settings(),
            ),
            patch("canon.cron.content_reconcile.create_pool", return_value=mock_pool),
            patch("canon.cron.content_reconcile.ensure_schema", new=AsyncMock()),
            patch("canon.cron.content_reconcile.ContentCacheStore"),
            patch(
                "canon.cron.content_reconcile.InstallationRegistry",
                return_value=mock_registry,
            ),
            patch("canon.cron.content_reconcile.GitHubClient"),
            patch(
                "canon.cron.content_reconcile.ContentSyncEngine",
                return_value=mock_engine,
            ),
            patch("canon.db.close_pool", new=AsyncMock()),
        ):
            result = await run_content_reconciliation()

        assert result["installations"] == 1
        assert result["synced"] == 3
        assert result["skipped"] == 1
        assert result["deleted"] == 0
        assert result["errors"] == 0
        mock_engine.reconcile_all.assert_awaited_once()

    async def test_reports_reconciliation_errors(self):
        mock_pool = AsyncMock()
        mock_registry = AsyncMock()
        mock_registry.get_active_installations = AsyncMock(return_value=[FakeInstallation()])

        stats = FakeSyncStats(errors=["repo acme/foo: 404 not found"])
        mock_engine = AsyncMock()
        mock_engine.reconcile_all = AsyncMock(return_value=stats)

        with (
            patch(
                "canon.cron.content_reconcile.Settings",
                return_value=_make_settings(),
            ),
            patch("canon.cron.content_reconcile.create_pool", return_value=mock_pool),
            patch("canon.cron.content_reconcile.ensure_schema", new=AsyncMock()),
            patch("canon.cron.content_reconcile.ContentCacheStore"),
            patch(
                "canon.cron.content_reconcile.InstallationRegistry",
                return_value=mock_registry,
            ),
            patch("canon.cron.content_reconcile.GitHubClient"),
            patch(
                "canon.cron.content_reconcile.ContentSyncEngine",
                return_value=mock_engine,
            ),
            patch("canon.db.close_pool", new=AsyncMock()),
        ):
            result = await run_content_reconciliation()

        assert result["errors"] == 1

    async def test_pool_closed_on_error_in_try_block(self):
        """close_pool is called when an error occurs inside the try block."""
        mock_pool = AsyncMock()
        mock_registry = AsyncMock()
        mock_registry.get_active_installations = AsyncMock(side_effect=RuntimeError("db error"))
        mock_close = AsyncMock()

        with (
            patch(
                "canon.cron.content_reconcile.Settings",
                return_value=_make_settings(),
            ),
            patch("canon.cron.content_reconcile.create_pool", return_value=mock_pool),
            patch("canon.cron.content_reconcile.ensure_schema", new=AsyncMock()),
            patch("canon.cron.content_reconcile.ContentCacheStore"),
            patch(
                "canon.cron.content_reconcile.InstallationRegistry",
                return_value=mock_registry,
            ),
            patch("canon.db.close_pool", mock_close),
            contextlib.suppress(RuntimeError),
        ):
            await run_content_reconciliation()

        mock_close.assert_awaited_once_with(mock_pool)
