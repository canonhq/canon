"""Tests for AgentStore data access layer."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from canon.db.agent_store import (
    AgentEvent,
    AgentStore,
    CoverageSnapshot,
    RealizationRecord,
    SyncStateRecord,
)


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock pool whose acquire() returns an async context manager yielding mock_conn."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


def _make_event_row(**overrides):
    defaults = {
        "id": 1,
        "repo": "org/repo",
        "event_type": "pr_comment",
        "pr_number": 42,
        "issue_number": None,
        "actor": "canon[bot]",
        "detail": "{}",
        "created_at": None,
    }
    return {**defaults, **overrides}


def _make_realization_row(**overrides):
    defaults = {
        "id": 1,
        "repo": "org/repo",
        "spec_path": "docs/specs/payments.md",
        "section_id": "2-retry",
        "ac_text": "Exponential backoff with jitter",
        "status": "realized",
        "pr_number": 42,
        "pr_url": "https://github.com/org/repo/pull/42",
        "evidence_files": "[]",
        "assessed_at": None,
    }
    return {**defaults, **overrides}


def _make_sync_state_row(**overrides):
    defaults = {
        "id": 1,
        "repo": "org/repo",
        "spec_path": "docs/specs/auth.md",
        "section_id": "1-login",
        "ticket_id": "PROJ-123",
        "last_synced_at": None,
        "last_status": "in_progress",
    }
    return {**defaults, **overrides}


class TestLogEvent:
    async def test_inserts_event(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_event_row()
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        result = await store.log_event(
            "org/repo",
            "pr_comment",
            pr_number=42,
            actor="canon[bot]",
        )

        assert isinstance(result, AgentEvent)
        assert result.repo == "org/repo"
        assert result.event_type == "pr_comment"
        mock_conn.fetchrow.assert_awaited_once()

    async def test_passes_detail_as_json(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_event_row(detail='{"key": "value"}')
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        await store.log_event(
            "org/repo",
            "pr_comment",
            detail={"key": "value"},
        )

        call_args = mock_conn.fetchrow.call_args
        # The detail JSON is the 7th positional arg (sql, repo, event_type, pr_number, issue_number, actor, detail)
        assert json.loads(call_args[0][6]) == {"key": "value"}


class TestGetEvents:
    async def test_returns_events(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            _make_event_row(id=1),
            _make_event_row(id=2, event_type="doc_pr"),
        ]
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        results = await store.get_events("org/repo")

        assert len(results) == 2
        assert results[0].id == 1
        assert results[1].event_type == "doc_pr"

    async def test_filters_by_event_type(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [_make_event_row()]
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        await store.get_events("org/repo", event_type="pr_comment")

        call_args = mock_conn.fetch.call_args
        assert "event_type" in call_args[0][0]


class TestUpsertRealization:
    async def test_upserts_realization(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_realization_row()
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        result = await store.upsert_realization(
            "org/repo",
            "docs/specs/payments.md",
            "2-retry",
            "Exponential backoff with jitter",
            status="realized",
            pr_number=42,
            pr_url="https://github.com/org/repo/pull/42",
            evidence_files=[{"path": "src/retry.py", "start_line": 42, "end_line": 60}],
        )

        assert isinstance(result, RealizationRecord)
        assert result.status == "realized"
        assert result.pr_number == 42
        mock_conn.fetchrow.assert_awaited_once()


class TestGetRealizations:
    async def test_returns_all_for_spec(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            _make_realization_row(id=1, status="realized"),
            _make_realization_row(id=2, status="not_addressed"),
        ]
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        results = await store.get_realizations("org/repo", "docs/specs/payments.md")

        assert len(results) == 2

    async def test_filters_by_section(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [_make_realization_row()]
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        await store.get_realizations(
            "org/repo",
            "docs/specs/payments.md",
            section_id="2-retry",
        )

        call_args = mock_conn.fetch.call_args
        assert "section_id" in call_args[0][0]


class TestGetRealizationSummary:
    async def test_returns_counts(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {"status": "realized", "cnt": 3},
            {"status": "not_addressed", "cnt": 1},
        ]
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        result = await store.get_realization_summary("org/repo", "docs/specs/payments.md")

        assert result == {"realized": 3, "not_addressed": 1}


class TestUpsertSyncState:
    async def test_upserts_sync_state(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_sync_state_row()
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        result = await store.upsert_sync_state(
            "org/repo",
            "docs/specs/auth.md",
            "1-login",
            "PROJ-123",
            status="in_progress",
        )

        assert isinstance(result, SyncStateRecord)
        assert result.ticket_id == "PROJ-123"


class TestGetSyncState:
    async def test_returns_records(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            _make_sync_state_row(id=1, ticket_id="PROJ-123"),
            _make_sync_state_row(id=2, ticket_id="PROJ-456"),
        ]
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        results = await store.get_sync_state("org/repo", "docs/specs/auth.md")

        assert len(results) == 2
        assert results[0].ticket_id == "PROJ-123"
        assert results[1].ticket_id == "PROJ-456"


def _make_coverage_row(**overrides):
    from datetime import date, datetime

    defaults = {
        "id": 1,
        "snapshot_date": date(2026, 2, 19),
        "org": "test-org",
        "repo": "test-org/repo",
        "team": "payments",
        "spec_path": "docs/specs/payments.md",
        "total_sections": 5,
        "done_sections": 3,
        "total_ac": 10,
        "done_ac": 7,
        "realized_ac": 4,
        "created_at": datetime(2026, 2, 19, 5, 0),
    }
    return {**defaults, **overrides}


class TestUpsertCoverageSnapshot:
    async def test_upserts_snapshot(self):
        from datetime import date

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_coverage_row()
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        result = await store.upsert_coverage_snapshot(
            date(2026, 2, 19),
            "test-org",
            "test-org/repo",
            "docs/specs/payments.md",
            team="payments",
            total_sections=5,
            done_sections=3,
            total_ac=10,
            done_ac=7,
            realized_ac=4,
        )

        assert isinstance(result, CoverageSnapshot)
        assert result.total_sections == 5
        assert result.realized_ac == 4
        mock_conn.fetchrow.assert_awaited_once()

    async def test_sql_uses_on_conflict(self):
        from datetime import date

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_coverage_row()
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        await store.upsert_coverage_snapshot(
            date(2026, 2, 19), "test-org", "test-org/repo", "docs/specs/payments.md"
        )

        sql = mock_conn.fetchrow.call_args[0][0]
        assert "ON CONFLICT" in sql
        assert "coverage_snapshots" in sql


class TestGetCoverageSummary:
    async def test_returns_aggregate(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "total_specs": 3,
            "total_sections": 15,
            "done_sections": 10,
            "total_ac": 30,
            "done_ac": 20,
            "realized_ac": 12,
        }
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        result = await store.get_coverage_summary("test-org")

        assert result["total_specs"] == 3
        assert result["realized_ac"] == 12

    async def test_filters_by_repo(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "total_specs": 1,
            "total_sections": 5,
            "done_sections": 3,
            "total_ac": 10,
            "done_ac": 7,
            "realized_ac": 4,
        }
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        await store.get_coverage_summary("test-org", repo="test-org/repo")

        sql = mock_conn.fetchrow.call_args[0][0]
        assert "repo" in sql


class TestGetCoverageTrend:
    async def test_returns_time_series(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "snapshot_date": "2026-02-18",
                "total_sections": 10,
                "done_sections": 5,
                "total_ac": 20,
                "done_ac": 10,
                "realized_ac": 6,
            },
            {
                "snapshot_date": "2026-02-19",
                "total_sections": 10,
                "done_sections": 7,
                "total_ac": 20,
                "done_ac": 14,
                "realized_ac": 8,
            },
        ]
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        result = await store.get_coverage_trend("test-org", days=7)

        assert len(result) == 2
        assert result[0]["date"] == "2026-02-18"
        assert result[1]["realized_ac"] == 8

    async def test_filters_by_team(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        store = AgentStore(_mock_pool_with_conn(mock_conn))

        await store.get_coverage_trend("test-org", team="payments")

        sql = mock_conn.fetch.call_args[0][0]
        assert "team" in sql
