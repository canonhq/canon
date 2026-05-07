"""Unit tests for TicketRefStatusStore using mock asyncpg pool."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from canon.db.ticket_ref_status_store import TicketRefStatusStore


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    pool.acquire = _acquire
    pool.execute = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    return pool


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.transaction.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    return conn


@pytest.fixture
def mock_pool(mock_conn):
    return _mock_pool_with_conn(mock_conn)


@pytest.fixture
def store(mock_pool):
    return TicketRefStatusStore(mock_pool)


class TestGet:
    async def test_returns_none_when_row_missing(self, store, mock_pool):
        mock_pool.fetchrow.return_value = None
        assert await store.get(1, "github", "org/repo#1") is None

    async def test_returns_dict_when_row_exists(self, store, mock_pool):
        mock_pool.fetchrow.return_value = {
            "id": 7,
            "installation_id": 1,
            "system": "github",
            "ticket_ref": "org/repo#1",
            "status": "broken",
            "consecutive_failures": 3,
            "last_error_kind": "not_found",
            "last_error_message": "not found",
            "first_failure_at": datetime.now(UTC),
            "last_check_at": datetime.now(UTC),
            "last_recheck_at": None,
            "dismissed_at": None,
            "dismissed_by": None,
        }
        row = await store.get(1, "github", "org/repo#1")
        assert row is not None
        assert row["status"] == "broken"
        assert row["consecutive_failures"] == 3


class TestRecordFailure:
    async def test_first_failure_inserts_with_count_1(self, store, mock_pool):
        mock_pool.fetchrow.return_value = {"status": "ok", "consecutive_failures": 1}
        result = await store.record_failure(
            installation_id=1,
            system="github",
            ticket_ref="org/repo#1",
            error_kind="not_found",
            error_message="ticket #1 not found",
        )
        assert result["status"] == "ok"
        assert result["consecutive_failures"] == 1
        # Verify INSERT ... ON CONFLICT was used
        sql_used = mock_pool.fetchrow.await_args[0][0]
        assert "INSERT INTO ticket_ref_status" in sql_used
        assert "ON CONFLICT" in sql_used

    async def test_third_failure_flips_to_broken(self, store, mock_pool):
        # The store's own SQL handles the threshold; we verify the
        # returned shape exposes that state to callers
        mock_pool.fetchrow.return_value = {"status": "broken", "consecutive_failures": 3}
        result = await store.record_failure(
            installation_id=1,
            system="github",
            ticket_ref="org/repo#1",
            error_kind="not_found",
            error_message="not found",
        )
        assert result["status"] == "broken"


class TestMarkOk:
    async def test_clears_broken_to_ok(self, store, mock_pool):
        await store.mark_ok(installation_id=1, system="github", ticket_ref="org/repo#1")
        sql_used = mock_pool.execute.await_args[0][0]
        assert "INSERT INTO ticket_ref_status" in sql_used
        assert "ON CONFLICT" in sql_used
        # Ensure mark_ok never touches dismissed rows
        assert "WHERE ticket_ref_status.status <> 'dismissed'" in sql_used

    async def test_resets_failure_count(self, store, mock_pool):
        await store.mark_ok(installation_id=1, system="github", ticket_ref="org/repo#1")
        sql_used = mock_pool.execute.await_args[0][0]
        assert "consecutive_failures = 0" in sql_used


class TestDismiss:
    async def test_sets_dismissed_status_and_user(self, store, mock_pool):
        await store.dismiss(
            installation_id=1,
            system="github",
            ticket_ref="org/repo#1",
            dismissed_by="auth0|123",
        )
        sql_used = mock_pool.execute.await_args[0][0]
        assert "status = 'dismissed'" in sql_used
        assert "dismissed_by" in sql_used


class TestForceRecheck:
    async def test_clears_last_recheck_at(self, store, mock_pool):
        await store.force_recheck(installation_id=1, system="github", ticket_ref="org/repo#1")
        sql_used = mock_pool.execute.await_args[0][0]
        assert "last_recheck_at = NULL" in sql_used


class TestListBroken:
    async def test_returns_rows_for_installation(self, store, mock_pool):
        mock_pool.fetch.return_value = [
            {"installation_id": 1, "ticket_ref": "org/repo#1", "status": "broken"},
            {"installation_id": 1, "ticket_ref": "org/repo#2", "status": "broken"},
        ]
        rows = await store.list_broken(installation_id=1)
        assert len(rows) == 2

    async def test_filters_by_status(self, store, mock_pool):
        mock_pool.fetch.return_value = []
        await store.list_broken(installation_id=1, status="dismissed")
        sql_used = mock_pool.fetch.await_args[0][0]
        assert "status = $2" in sql_used
