"""Tests for ErrorStore (error fingerprint → GitHub issue mapping)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from canon.db.error_store import ErrorIssueMapping, ErrorStore


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock pool whose acquire() returns an async context manager yielding mock_conn."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


def _make_error_row(**overrides):
    defaults = {
        "id": 1,
        "fingerprint": "fp123",
        "repo": "org/repo",
        "issue_number": 42,
        "issue_url": "https://github.com/org/repo/issues/42",
        "severity": "high",
        "first_seen_at": None,
        "last_seen_at": None,
        "occurrence_count": 3,
        "resolved_at": None,
    }
    return {**defaults, **overrides}


class TestGetByFingerprint:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None
        store = ErrorStore(_mock_pool_with_conn(mock_conn))

        result = await store.get_by_fingerprint("fp123", "org/repo")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_mapping_when_found(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_error_row()
        store = ErrorStore(_mock_pool_with_conn(mock_conn))

        result = await store.get_by_fingerprint("fp123", "org/repo")

        assert result is not None
        assert isinstance(result, ErrorIssueMapping)
        assert result.fingerprint == "fp123"
        assert result.repo == "org/repo"
        assert result.issue_number == 42
        assert result.severity == "high"
        assert result.occurrence_count == 3


class TestCreate:
    @pytest.mark.asyncio
    async def test_creates_mapping(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {"id": 1}
        store = ErrorStore(_mock_pool_with_conn(mock_conn))

        result = await store.create(
            fingerprint="fp123",
            repo="org/repo",
            issue_number=42,
            issue_url="https://github.com/org/repo/issues/42",
            severity="high",
        )

        assert isinstance(result, ErrorIssueMapping)
        assert result.id == 1
        assert result.fingerprint == "fp123"
        assert result.repo == "org/repo"
        assert result.issue_number == 42
        assert result.issue_url == "https://github.com/org/repo/issues/42"
        assert result.severity == "high"
        mock_conn.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_defaults_for_optional_fields(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {"id": 2}
        store = ErrorStore(_mock_pool_with_conn(mock_conn))

        result = await store.create(
            fingerprint="fp456",
            repo="org/repo",
            issue_number=100,
        )

        assert result.issue_url == ""
        assert result.severity == "medium"


class TestIncrementOccurrence:
    @pytest.mark.asyncio
    async def test_increments_count(self):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = None
        store = ErrorStore(_mock_pool_with_conn(mock_conn))

        await store.increment_occurrence("fp123", "org/repo")

        mock_conn.execute.assert_awaited_once()
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        assert "occurrence_count = occurrence_count + 1" in sql
        assert "last_seen_at = now()" in sql


class TestMarkResolved:
    @pytest.mark.asyncio
    async def test_marks_as_resolved(self):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = None
        store = ErrorStore(_mock_pool_with_conn(mock_conn))

        await store.mark_resolved("fp123", "org/repo")

        mock_conn.execute.assert_awaited_once()
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        assert "resolved_at = now()" in sql


class TestClearResolved:
    @pytest.mark.asyncio
    async def test_clears_resolved_flag(self):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = None
        store = ErrorStore(_mock_pool_with_conn(mock_conn))

        await store.clear_resolved("fp123", "org/repo")

        mock_conn.execute.assert_awaited_once()
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        assert "resolved_at = NULL" in sql
