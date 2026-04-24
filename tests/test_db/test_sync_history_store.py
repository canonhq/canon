"""Tests for SyncHistoryStore data access layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from canon.db.sync_history_store import SyncHistoryStore


def _make_store():
    """Create a SyncHistoryStore with a mocked asyncpg pool."""
    mock_conn = AsyncMock()
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    store = SyncHistoryStore(mock_pool)
    return store, mock_conn


class TestCreateRun:
    @pytest.mark.asyncio
    async def test_returns_uuid_string(self):
        store, conn = _make_store()
        conn.execute = AsyncMock()

        run_id = await store.create_run(
            org_login="acme",
            repo="acme/web",
            system="jira",
            direction="push",
        )

        # Should return a valid UUID string
        assert isinstance(run_id, str)
        assert len(run_id) == 36  # UUID format: 8-4-4-4-12

    @pytest.mark.asyncio
    async def test_passes_correct_sql_params(self):
        store, conn = _make_store()
        conn.execute = AsyncMock()

        await store.create_run(
            org_login="acme",
            repo="acme/web",
            spec_path="docs/specs/auth.md",
            system="jira",
            direction="push",
            trigger="webhook",
            triggered_by="user-1",
            metadata={"key": "value"},
        )

        conn.execute.assert_awaited_once()
        sql = conn.execute.call_args[0][0]
        assert "INSERT INTO sync_runs" in sql

        args = conn.execute.call_args[0]
        # args[1] = run_id (UUID), args[2] = org_login, ...
        assert args[2] == "acme"
        assert args[3] == "acme/web"
        assert args[4] == "docs/specs/auth.md"
        assert args[5] == "jira"
        assert args[6] == "push"
        assert args[7] == "webhook"
        assert args[8] == "user-1"
        assert '"key"' in args[9]  # JSON string

    @pytest.mark.asyncio
    async def test_defaults_trigger_to_manual(self):
        store, conn = _make_store()
        conn.execute = AsyncMock()

        await store.create_run(
            org_login="acme",
            repo="acme/web",
            system="linear",
            direction="pull",
        )

        args = conn.execute.call_args[0]
        assert args[7] == "manual"  # trigger default

    @pytest.mark.asyncio
    async def test_none_metadata_becomes_empty_json(self):
        store, conn = _make_store()
        conn.execute = AsyncMock()

        await store.create_run(
            org_login="acme",
            repo="acme/web",
            system="jira",
            direction="push",
            metadata=None,
        )

        args = conn.execute.call_args[0]
        assert args[9] == "{}"


class TestCompleteRun:
    @pytest.mark.asyncio
    async def test_returns_true_on_update_1(self):
        store, conn = _make_store()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        result = await store.complete_run(
            "run-uuid",
            status="completed",
            created_count=3,
            updated_count=2,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_update_0(self):
        store, conn = _make_store()
        conn.execute = AsyncMock(return_value="UPDATE 0")

        result = await store.complete_run("nonexistent-id", status="completed")

        assert result is False

    @pytest.mark.asyncio
    async def test_passes_all_counts(self):
        store, conn = _make_store()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        await store.complete_run(
            "run-uuid",
            status="completed",
            created_count=1,
            updated_count=2,
            closed_count=3,
            reopened_count=4,
            skipped_count=5,
            error_count=6,
        )

        args = conn.execute.call_args[0]
        sql = args[0]
        assert "UPDATE sync_runs" in sql
        assert args[1] == "run-uuid"
        assert args[2] == "completed"
        assert args[3] == 1  # created_count
        assert args[4] == 2  # updated_count
        assert args[5] == 3  # closed_count
        assert args[6] == 4  # reopened_count
        assert args[7] == 5  # skipped_count
        assert args[8] == 6  # error_count


class TestGetRun:
    @pytest.mark.asyncio
    async def test_returns_dict_when_found(self):
        store, conn = _make_store()
        row = {"id": "run-1", "org_login": "acme", "status": "completed"}
        conn.fetchrow = AsyncMock(return_value=row)

        result = await store.get_run("run-1")

        assert result == {"id": "run-1", "org_login": "acme", "status": "completed"}

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        store, conn = _make_store()
        conn.fetchrow = AsyncMock(return_value=None)

        result = await store.get_run("nonexistent")

        assert result is None


class TestListRuns:
    @pytest.mark.asyncio
    async def test_basic_list(self):
        store, conn = _make_store()
        rows = [
            {"id": "run-1", "org_login": "acme", "status": "completed"},
            {"id": "run-2", "org_login": "acme", "status": "running"},
        ]
        conn.fetch = AsyncMock(return_value=rows)

        result = await store.list_runs("acme")

        assert len(result) == 2
        assert result[0]["id"] == "run-1"
        assert result[1]["id"] == "run-2"

    @pytest.mark.asyncio
    async def test_filters_by_repo(self):
        store, conn = _make_store()
        conn.fetch = AsyncMock(return_value=[])

        await store.list_runs("acme", repo="acme/web")

        sql = conn.fetch.call_args[0][0]
        assert "repo = $2" in sql
        # org_login=$1, repo=$2, limit=$3
        args = conn.fetch.call_args[0]
        assert args[1] == "acme"
        assert args[2] == "acme/web"

    @pytest.mark.asyncio
    async def test_filters_by_system_direction_status(self):
        store, conn = _make_store()
        conn.fetch = AsyncMock(return_value=[])

        await store.list_runs("acme", system="jira", direction="push", status="completed")

        sql = conn.fetch.call_args[0][0]
        assert "system = $2" in sql
        assert "direction = $3" in sql
        assert "status = $4" in sql

    @pytest.mark.asyncio
    async def test_cursor_pagination(self):
        store, conn = _make_store()
        conn.fetch = AsyncMock(return_value=[])
        cursor_ts = datetime(2025, 1, 1, tzinfo=UTC)

        await store.list_runs("acme", cursor=cursor_ts)

        sql = conn.fetch.call_args[0][0]
        assert "started_at < $2" in sql
        args = conn.fetch.call_args[0]
        assert args[2] == cursor_ts

    @pytest.mark.asyncio
    async def test_limit_is_passed(self):
        store, conn = _make_store()
        conn.fetch = AsyncMock(return_value=[])

        await store.list_runs("acme", limit=10)

        sql = conn.fetch.call_args[0][0]
        assert "LIMIT $2" in sql
        args = conn.fetch.call_args[0]
        assert args[2] == 10

    @pytest.mark.asyncio
    async def test_all_filters_combined(self):
        store, conn = _make_store()
        conn.fetch = AsyncMock(return_value=[])
        since = datetime(2025, 1, 1, tzinfo=UTC)
        until = datetime(2025, 6, 1, tzinfo=UTC)
        cursor = datetime(2025, 3, 1, tzinfo=UTC)

        await store.list_runs(
            "acme",
            repo="acme/web",
            system="jira",
            direction="push",
            status="completed",
            since=since,
            until=until,
            cursor=cursor,
            limit=25,
        )

        sql = conn.fetch.call_args[0][0]
        # All conditions should be present
        assert "org_login = $1" in sql
        assert "repo = $2" in sql
        assert "system = $3" in sql
        assert "direction = $4" in sql
        assert "status = $5" in sql
        assert "started_at >= $6" in sql
        assert "started_at <= $7" in sql
        assert "started_at < $8" in sql
        assert "LIMIT $9" in sql


class TestEvents:
    @pytest.mark.asyncio
    async def test_add_event_returns_uuid(self):
        store, conn = _make_store()
        conn.execute = AsyncMock()

        event_id = await store.add_event(
            "run-1",
            event_type="ticket_created",
            section_title="Auth",
            ticket_id="PROJ-123",
            ticket_url="https://jira.example.com/PROJ-123",
        )

        assert isinstance(event_id, str)
        assert len(event_id) == 36

    @pytest.mark.asyncio
    async def test_add_event_passes_correct_sql(self):
        store, conn = _make_store()
        conn.execute = AsyncMock()

        await store.add_event(
            "run-1",
            event_type="ticket_created",
            section_title="Auth",
            section_number="1.2",
            ticket_id="PROJ-123",
            ticket_url="https://jira.example.com/PROJ-123",
            detail={"priority": "high"},
        )

        sql = conn.execute.call_args[0][0]
        assert "INSERT INTO sync_events" in sql
        args = conn.execute.call_args[0]
        assert args[2] == "run-1"  # run_id
        assert args[3] == "ticket_created"  # event_type
        assert args[4] == "Auth"  # section_title
        assert args[5] == "1.2"  # section_number
        assert args[6] == "PROJ-123"  # ticket_id

    @pytest.mark.asyncio
    async def test_add_events_batch_returns_count(self):
        store, conn = _make_store()
        conn.executemany = AsyncMock()

        events = [
            {"event_type": "ticket_created", "section_title": "Auth"},
            {"event_type": "ticket_updated", "section_title": "Billing"},
            {"event_type": "ticket_closed", "section_title": "Settings"},
        ]

        count = await store.add_events_batch("run-1", events)

        assert count == 3
        conn.executemany.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_events_batch_empty_list(self):
        store, _conn = _make_store()

        count = await store.add_events_batch("run-1", [])

        assert count == 0

    @pytest.mark.asyncio
    async def test_get_run_events_returns_list(self):
        store, conn = _make_store()
        rows = [
            {"id": "ev-1", "event_type": "ticket_created"},
            {"id": "ev-2", "event_type": "ticket_updated"},
        ]
        conn.fetch = AsyncMock(return_value=rows)

        result = await store.get_run_events("run-1")

        assert len(result) == 2
        assert result[0]["id"] == "ev-1"

    @pytest.mark.asyncio
    async def test_get_run_events_filtered_by_type(self):
        store, conn = _make_store()
        rows = [{"id": "ev-1", "event_type": "ticket_created"}]
        conn.fetch = AsyncMock(return_value=rows)

        result = await store.get_run_events("run-1", event_type="ticket_created")

        sql = conn.fetch.call_args[0][0]
        assert "event_type = $2" in sql
        assert len(result) == 1


class TestStats:
    @pytest.mark.asyncio
    async def test_returns_correct_aggregates(self):
        store, conn = _make_store()
        stats_row = {
            "total_runs": 42,
            "total_created": 100,
            "total_updated": 50,
            "total_closed": 10,
            "total_errors": 5,
            "synced_repos": 3,
            "synced_specs": 7,
        }
        active_errors_row = {"active_errors": 2}

        conn.fetchrow = AsyncMock(side_effect=[stats_row, active_errors_row])

        result = await store.get_stats("acme")

        assert result["total_runs"] == 42
        assert result["total_created"] == 100
        assert result["total_updated"] == 50
        assert result["total_closed"] == 10
        assert result["total_errors"] == 5
        assert result["synced_repos"] == 3
        assert result["synced_specs"] == 7
        assert result["active_errors"] == 2

    @pytest.mark.asyncio
    async def test_handles_no_active_errors(self):
        store, conn = _make_store()
        stats_row = {
            "total_runs": 0,
            "total_created": 0,
            "total_updated": 0,
            "total_closed": 0,
            "total_errors": 0,
            "synced_repos": 0,
            "synced_specs": 0,
        }
        conn.fetchrow = AsyncMock(side_effect=[stats_row, None])

        result = await store.get_stats("acme")

        assert result["active_errors"] == 0


class TestSpecSyncStatus:
    @pytest.mark.asyncio
    async def test_returns_last_run_and_recent_errors(self):
        store, conn = _make_store()
        last_run_row = {
            "id": "run-1",
            "status": "completed",
            "started_at": datetime(2025, 6, 1, tzinfo=UTC),
        }
        error_row = {"recent_errors": 3}
        conn.fetchrow = AsyncMock(side_effect=[last_run_row, error_row])

        result = await store.get_spec_sync_status("acme", "acme", "web", "docs/specs/auth.md")

        assert result["last_run"]["id"] == "run-1"
        assert result["last_run"]["status"] == "completed"
        assert result["recent_errors"] == 3

        # Verify the repo was combined as "owner/repo_name"
        first_call_args = conn.fetchrow.call_args_list[0][0]
        assert first_call_args[2] == "acme/web"

    @pytest.mark.asyncio
    async def test_handles_no_data(self):
        store, conn = _make_store()
        conn.fetchrow = AsyncMock(side_effect=[None, None])

        result = await store.get_spec_sync_status("acme", "acme", "web", "docs/specs/auth.md")

        assert result["last_run"] is None
        assert result["recent_errors"] == 0


class TestCleanup:
    @pytest.mark.asyncio
    async def test_parses_delete_count(self):
        store, conn = _make_store()
        conn.execute = AsyncMock(return_value="DELETE 42")

        count = await store.cleanup_old_runs(retention_days=90)

        assert count == 42

    @pytest.mark.asyncio
    async def test_delete_zero(self):
        store, conn = _make_store()
        conn.execute = AsyncMock(return_value="DELETE 0")

        count = await store.cleanup_old_runs()

        assert count == 0

    @pytest.mark.asyncio
    async def test_handles_unexpected_result(self):
        store, conn = _make_store()
        conn.execute = AsyncMock(return_value="UNEXPECTED")

        count = await store.cleanup_old_runs()

        assert count == 0

    @pytest.mark.asyncio
    async def test_passes_retention_days_as_string(self):
        store, conn = _make_store()
        conn.execute = AsyncMock(return_value="DELETE 5")

        await store.cleanup_old_runs(retention_days=30)

        args = conn.execute.call_args[0]
        assert args[1] == "30"
