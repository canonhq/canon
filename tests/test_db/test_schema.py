"""Tests for schema initialisation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from canon.db.schema import _load_sql, ensure_schema


class TestLoadSql:
    def test_returns_non_empty_string(self):
        sql = _load_sql()
        assert isinstance(sql, str)
        assert "CREATE TABLE" in sql

    def test_contains_extensions(self):
        sql = _load_sql()
        assert "CREATE EXTENSION IF NOT EXISTS vector" in sql

    def test_contains_tables(self):
        sql = _load_sql()
        assert "spec_documents" in sql
        assert "spec_sections" in sql

    def test_vector_dimension_1024(self):
        sql = _load_sql()
        assert "vector(1024)" in sql
        assert "vector(1536)" not in sql

    def test_bm25_sql_separate(self):
        bm25_sql = _load_sql("schema_bm25.sql")
        assert "paradedb.create_bm25" in bm25_sql
        assert "pg_search" in bm25_sql

    def test_agent_sql_loads(self):
        agent_sql = _load_sql("schema_agent.sql")
        assert "agent_events" in agent_sql
        assert "realization_evidence" in agent_sql
        assert "sync_state" in agent_sql

    def test_coverage_sql_loads(self):
        coverage_sql = _load_sql("schema_coverage.sql")
        assert "coverage_snapshots" in coverage_sql
        assert "snapshot_date" in coverage_sql
        assert "realized_ac" in coverage_sql

    def test_staleness_migration_present(self):
        sql = _load_sql()
        assert "doc_type" in sql
        assert "last_code_change_at" in sql
        assert "last_doc_change_at" in sql
        assert "stale_since" in sql


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock pool whose acquire() returns an async context manager yielding mock_conn."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


class TestEnsureSchema:
    async def test_executes_ddl(self):
        mock_conn = AsyncMock()
        mock_pool = _mock_pool_with_conn(mock_conn)

        def fake_load(filename="schema.sql"):
            if filename == "schema.sql":
                return "CREATE TABLE test;"
            if filename == "schema_installations.sql":
                return "CREATE TABLE installs;"
            if filename == "schema_agent.sql":
                return "CREATE TABLE agents;"
            if filename == "schema_users.sql":
                return "CREATE TABLE users;"
            if filename == "schema_coverage.sql":
                return "CREATE TABLE coverage;"
            return "CREATE INDEX bm25;"

        with patch("canon.db.schema._load_sql", side_effect=fake_load):
            await ensure_schema(mock_pool)

        # Core + installations + agent + users + coverage + BM25 = 6 calls
        assert mock_conn.execute.await_count == 6
        mock_conn.execute.assert_any_await("CREATE TABLE test;")

    async def test_bm25_failure_does_not_crash(self):
        """If BM25 DDL fails, ensure_schema still succeeds."""
        mock_conn = AsyncMock()
        call_count = 0

        async def execute_side_effect(sql):
            nonlocal call_count
            call_count += 1
            if (
                call_count == 6
            ):  # BM25 is the sixth call (after core + installations + agent + users + coverage)
                raise Exception("pg_search not available")

        mock_conn.execute = AsyncMock(side_effect=execute_side_effect)
        mock_pool = _mock_pool_with_conn(mock_conn)

        def fake_load(filename="schema.sql"):
            if filename == "schema.sql":
                return "CREATE TABLE test;"
            if filename == "schema_installations.sql":
                return "CREATE TABLE installs;"
            if filename == "schema_agent.sql":
                return "CREATE TABLE agents;"
            if filename == "schema_users.sql":
                return "CREATE TABLE users;"
            if filename == "schema_coverage.sql":
                return "CREATE TABLE coverage;"
            return "CREATE INDEX bm25;"

        with patch("canon.db.schema._load_sql", side_effect=fake_load):
            await ensure_schema(mock_pool)

        # Should not raise — BM25 failure is swallowed
        assert call_count == 6
