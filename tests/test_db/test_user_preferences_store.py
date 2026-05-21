"""Tests for UserPreferencesStore data access layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from canon.db.user_preferences_store import (
    ALLOWED_PREFERENCE_COLUMNS,
    UserPreferencesStore,
)


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


def _default_row(user_id: int = 1, org: str = "acme") -> dict:
    return {
        "user_id": user_id,
        "org_login": org,
        "slack_dm_enabled": True,
        "slack_dm_pr_comments": True,
        "slack_dm_spec_drift": True,
        "email_digest_cadence": "weekly",
        "email_pr_comments": False,
        "theme": "system",
        "timezone": "",
        "relative_time": True,
        "updated_at": datetime.now(UTC),
    }


class TestGet:
    async def test_returns_existing_row(self):
        mock_conn = AsyncMock()
        existing = _default_row()
        mock_conn.fetchrow = AsyncMock(return_value=existing)
        store = UserPreferencesStore(_mock_pool_with_conn(mock_conn))

        result = await store.get(user_id=1, org_login="acme")

        assert result["user_id"] == 1
        assert result["org_login"] == "acme"
        assert result["slack_dm_enabled"] is True

    async def test_creates_default_row_when_missing(self):
        mock_conn = AsyncMock()
        # First fetchrow (SELECT) returns None; second (INSERT...RETURNING) returns the new row
        mock_conn.fetchrow = AsyncMock(side_effect=[None, _default_row()])
        store = UserPreferencesStore(_mock_pool_with_conn(mock_conn))

        result = await store.get(user_id=1, org_login="acme")

        assert result["slack_dm_enabled"] is True
        assert mock_conn.fetchrow.await_count == 2
        insert_sql = mock_conn.fetchrow.await_args_list[1].args[0]
        assert "INSERT INTO user_preferences" in insert_sql


class TestUpdate:
    async def test_updates_single_field(self):
        mock_conn = AsyncMock()
        updated = {**_default_row(), "slack_dm_enabled": False}
        # get() finds existing, then update() returns the new row
        mock_conn.fetchrow = AsyncMock(side_effect=[_default_row(), updated])
        store = UserPreferencesStore(_mock_pool_with_conn(mock_conn))

        result = await store.update(user_id=1, org_login="acme", patch={"slack_dm_enabled": False})

        assert result["slack_dm_enabled"] is False
        update_sql = mock_conn.fetchrow.await_args_list[1].args[0]
        assert "UPDATE user_preferences" in update_sql
        assert "slack_dm_enabled = $" in update_sql
        # Sanity: untouched columns are not in the SET clause
        assert "theme = $" not in update_sql

    async def test_rejects_unknown_column(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=_default_row())
        store = UserPreferencesStore(_mock_pool_with_conn(mock_conn))

        with pytest.raises(ValueError, match="not_a_real_column"):
            await store.update(user_id=1, org_login="acme", patch={"not_a_real_column": True})

    async def test_lazy_creates_row_before_updating(self):
        """If the row doesn't exist yet, update() creates defaults first then patches."""
        mock_conn = AsyncMock()
        # get() returns None on first SELECT, creates defaults on INSERT, then update() applies patch
        mock_conn.fetchrow = AsyncMock(
            side_effect=[
                None,  # initial SELECT misses
                _default_row(),  # INSERT...DEFAULT VALUES
                {**_default_row(), "theme": "dark"},  # UPDATE
            ]
        )
        store = UserPreferencesStore(_mock_pool_with_conn(mock_conn))

        result = await store.update(user_id=1, org_login="acme", patch={"theme": "dark"})

        assert result["theme"] == "dark"
        assert mock_conn.fetchrow.await_count == 3

    async def test_no_patch_returns_existing(self):
        """An empty patch is a no-op that returns the current row unchanged."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=_default_row())
        store = UserPreferencesStore(_mock_pool_with_conn(mock_conn))

        result = await store.update(user_id=1, org_login="acme", patch={})

        assert result["theme"] == "system"
        # Only the get() SELECT runs; no UPDATE
        assert mock_conn.fetchrow.await_count == 1


class TestPerOrgIsolation:
    async def test_get_scopes_by_org_login(self):
        """SELECT must filter by both user_id and org_login."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=_default_row(org="acme"))
        store = UserPreferencesStore(_mock_pool_with_conn(mock_conn))

        await store.get(user_id=1, org_login="acme")

        select_sql = mock_conn.fetchrow.await_args_list[0].args[0]
        assert "user_id = $1" in select_sql
        assert "org_login = $2" in select_sql

    async def test_update_scopes_by_org_login(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(side_effect=[_default_row(), _default_row()])
        store = UserPreferencesStore(_mock_pool_with_conn(mock_conn))

        await store.update(user_id=1, org_login="acme", patch={"theme": "light"})

        update_sql = mock_conn.fetchrow.await_args_list[1].args[0]
        assert "WHERE user_id = $" in update_sql
        assert "AND org_login = $" in update_sql


class TestAllowedColumns:
    def test_allow_list_matches_spec(self):
        """Allow-list mirrors the spec's user_preferences column set."""
        # See docs/specs/profile-account-management.md §5
        expected = {
            "slack_dm_enabled",
            "slack_dm_pr_comments",
            "slack_dm_spec_drift",
            "email_digest_cadence",
            "email_pr_comments",
            "theme",
            "timezone",
            "relative_time",
        }
        assert expected == ALLOWED_PREFERENCE_COLUMNS
