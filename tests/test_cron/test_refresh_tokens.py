"""Tests for the OAuth token refresh cron job."""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canon.cron.refresh_tokens import (
    ERROR_RECOVERY_THRESHOLD_SECONDS,
    run_refresh,
)


def _make_settings(**overrides):
    defaults = {
        "database_url": "postgres://test",
        "jira_oauth_client_id": "client-id",
        "jira_oauth_client_secret": "client-secret",
        "api_key_encryption_key": "enc-key",
    }
    defaults.update(overrides)
    return type("S", (), defaults)()


def _make_row(
    *,
    org_login="acme",
    row_id=1,
    status="active",
    refresh_token="rt-123",
    last_refreshed=0,
    access_token="old-at",
):
    config = {"access_token": access_token, "refresh_token": refresh_token}
    metadata = {"token_refreshed_at": last_refreshed}
    return {
        "id": row_id,
        "org_login": org_login,
        "encrypted_config": json.dumps(config),  # will be "decrypted" by mock
        "provider_metadata": json.dumps(metadata),
        "status": status,
    }


def _make_pool(mock_conn):
    """Create a mock pool with the correct asynccontextmanager acquire pattern."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


class TestRunRefresh:
    async def test_skips_when_no_jira_credentials(self):
        with patch(
            "canon.cron.refresh_tokens.Settings",
            return_value=_make_settings(jira_oauth_client_id="", jira_oauth_client_secret=""),
        ):
            count = await run_refresh()
        assert count == 0

    async def test_exits_when_no_database_url(self):
        with (
            patch(
                "canon.cron.refresh_tokens.Settings",
                return_value=_make_settings(database_url=""),
            ),
            pytest.raises(SystemExit),
        ):
            await run_refresh()

    async def test_exits_when_no_encryption_key(self):
        with (
            patch(
                "canon.cron.refresh_tokens.Settings",
                return_value=_make_settings(api_key_encryption_key=""),
            ),
            pytest.raises(SystemExit),
        ):
            await run_refresh()

    async def test_refreshes_expired_token(self):
        """Token older than threshold gets refreshed and DB updated."""
        row = _make_row(last_refreshed=0)  # very old
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[row])
        mock_conn.execute = AsyncMock()

        mock_pool = _make_pool(mock_conn)

        new_tokens = {"access_token": "new-at", "refresh_token": "new-rt"}

        with (
            patch("canon.cron.refresh_tokens.Settings", return_value=_make_settings()),
            patch("canon.cron.refresh_tokens.create_pool", return_value=mock_pool),
            patch("canon.cron.refresh_tokens.close_pool", new=AsyncMock()),
            patch(
                "canon.cron.refresh_tokens.decrypt_api_key",
                return_value=row["encrypted_config"],
            ),
            patch("canon.cron.refresh_tokens.encrypt_api_key", return_value="encrypted"),
            patch(
                "canon.cron.refresh_tokens.refresh_jira_token",
                new=AsyncMock(return_value=new_tokens),
            ),
        ):
            count = await run_refresh()

        assert count == 1
        # DB should have been updated with new encrypted config
        assert mock_conn.execute.await_count >= 1

    async def test_skips_recently_refreshed_token(self):
        """Token refreshed within threshold is skipped."""
        row = _make_row(last_refreshed=time.time() - 60)  # 1 min ago
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[row])

        mock_pool = _make_pool(mock_conn)

        with (
            patch("canon.cron.refresh_tokens.Settings", return_value=_make_settings()),
            patch("canon.cron.refresh_tokens.create_pool", return_value=mock_pool),
            patch("canon.cron.refresh_tokens.close_pool", new=AsyncMock()),
            patch(
                "canon.cron.refresh_tokens.decrypt_api_key",
                return_value=row["encrypted_config"],
            ),
        ):
            count = await run_refresh()

        assert count == 0

    async def test_error_status_uses_shorter_threshold(self):
        """Integrations in error/needs_reauth use shorter refresh threshold."""
        # Token refreshed 6 min ago — should be skipped for active but refreshed for error
        row = _make_row(
            status="error",
            last_refreshed=time.time() - (ERROR_RECOVERY_THRESHOLD_SECONDS + 10),
        )
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[row])
        mock_conn.execute = AsyncMock()

        mock_pool = _make_pool(mock_conn)

        new_tokens = {"access_token": "new-at"}

        with (
            patch("canon.cron.refresh_tokens.Settings", return_value=_make_settings()),
            patch("canon.cron.refresh_tokens.create_pool", return_value=mock_pool),
            patch("canon.cron.refresh_tokens.close_pool", new=AsyncMock()),
            patch(
                "canon.cron.refresh_tokens.decrypt_api_key",
                return_value=row["encrypted_config"],
            ),
            patch("canon.cron.refresh_tokens.encrypt_api_key", return_value="encrypted"),
            patch(
                "canon.cron.refresh_tokens.refresh_jira_token",
                new=AsyncMock(return_value=new_tokens),
            ),
        ):
            count = await run_refresh()

        assert count == 1

    async def test_marks_needs_reauth_on_refresh_failure(self):
        """When refresh_jira_token returns None, status is set to needs_reauth."""
        row = _make_row(last_refreshed=0)
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[row])
        mock_conn.execute = AsyncMock()

        mock_pool = _make_pool(mock_conn)

        with (
            patch("canon.cron.refresh_tokens.Settings", return_value=_make_settings()),
            patch("canon.cron.refresh_tokens.create_pool", return_value=mock_pool),
            patch("canon.cron.refresh_tokens.close_pool", new=AsyncMock()),
            patch(
                "canon.cron.refresh_tokens.decrypt_api_key",
                return_value=row["encrypted_config"],
            ),
            patch(
                "canon.cron.refresh_tokens.refresh_jira_token",
                new=AsyncMock(return_value=None),
            ),
        ):
            count = await run_refresh()

        assert count == 0
        # Should have executed an UPDATE setting needs_reauth
        update_calls = [c for c in mock_conn.execute.call_args_list if "needs_reauth" in str(c)]
        assert len(update_calls) == 1

    async def test_skips_row_without_refresh_token(self):
        """Row with empty refresh_token is skipped."""
        row = _make_row(refresh_token="", last_refreshed=0)
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[row])

        mock_pool = _make_pool(mock_conn)

        with (
            patch("canon.cron.refresh_tokens.Settings", return_value=_make_settings()),
            patch("canon.cron.refresh_tokens.create_pool", return_value=mock_pool),
            patch("canon.cron.refresh_tokens.close_pool", new=AsyncMock()),
            patch(
                "canon.cron.refresh_tokens.decrypt_api_key",
                return_value=row["encrypted_config"],
            ),
        ):
            count = await run_refresh()

        assert count == 0

    async def test_decrypt_failure_skips_row(self):
        """If decryption fails for a row, it's skipped and others continue."""
        row = _make_row(last_refreshed=0)
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[row])

        mock_pool = _make_pool(mock_conn)

        with (
            patch("canon.cron.refresh_tokens.Settings", return_value=_make_settings()),
            patch("canon.cron.refresh_tokens.create_pool", return_value=mock_pool),
            patch("canon.cron.refresh_tokens.close_pool", new=AsyncMock()),
            patch(
                "canon.cron.refresh_tokens.decrypt_api_key",
                side_effect=ValueError("bad key"),
            ),
        ):
            count = await run_refresh()

        assert count == 0

    async def test_pool_closed_in_finally(self):
        """Pool is closed even if an error occurs."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=RuntimeError("db error"))
        mock_pool = _make_pool(mock_conn)
        mock_close = AsyncMock()

        with (
            patch("canon.cron.refresh_tokens.Settings", return_value=_make_settings()),
            patch("canon.cron.refresh_tokens.create_pool", return_value=mock_pool),
            patch("canon.cron.refresh_tokens.close_pool", mock_close),
            pytest.raises(RuntimeError, match="db error"),
        ):
            await run_refresh()

        mock_close.assert_awaited_once_with(mock_pool)
