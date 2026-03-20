"""Tests for schema initialisation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from canon.db.schema import _load_sql, ensure_schema


class TestLoadSql:
    def test_bm25_sql_loads(self):
        bm25_sql = _load_sql("schema_bm25.sql")
        assert "paradedb.create_bm25" in bm25_sql
        assert "pg_search" in bm25_sql


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock pool whose acquire() returns an async context manager yielding mock_conn."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


class TestEnsureSchema:
    async def test_calls_alembic_then_bm25(self):
        """ensure_schema calls run_upgrade via to_thread, then applies BM25."""
        mock_conn = AsyncMock()
        mock_pool = _mock_pool_with_conn(mock_conn)

        with (
            patch("canon.db.schema.asyncio.to_thread") as mock_to_thread,
            patch("canon.db.schema._load_sql", return_value="CREATE INDEX bm25;"),
        ):
            await ensure_schema(mock_pool, "postgresql://localhost/canon")

        # Alembic upgrade was called with the database URL
        mock_to_thread.assert_awaited_once()
        call_args = mock_to_thread.call_args
        assert call_args[0][0].__name__ == "run_upgrade"
        assert call_args[0][1] == "postgresql://localhost/canon"

        # BM25 DDL was executed
        mock_conn.execute.assert_awaited_once_with("CREATE INDEX bm25;")

    async def test_bm25_failure_does_not_crash(self):
        """If BM25 DDL fails, ensure_schema still succeeds."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("pg_search not available"))
        mock_pool = _mock_pool_with_conn(mock_conn)

        with (
            patch("canon.db.schema.asyncio.to_thread"),
            patch("canon.db.schema._load_sql", return_value="CREATE INDEX bm25;"),
        ):
            # Should not raise
            await ensure_schema(mock_pool, "postgresql://localhost/canon")
