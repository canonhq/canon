"""Tests for installation registry data access."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from canon.db.registry import (
    InstallationRegistry,
    _row_to_index_job,
    _row_to_installation,
)


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock pool whose acquire() returns an async context manager."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


def _make_install_row(**overrides) -> dict:
    """Build a dict mimicking an asyncpg Record for gh_installations."""
    defaults = {
        "id": 1,
        "installation_id": 12345,
        "org_login": "test-org",
        "org_id": 111,
        "app_id": "app-1",
        "status": "active",
        "installed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "last_indexed_at": None,
        "repos_count": 5,
        "auth0_org_id": "",
    }
    defaults.update(overrides)
    return defaults


def _make_job_row(**overrides) -> dict:
    defaults = {
        "id": 10,
        "installation_id": 12345,
        "repo": "test-org/repo1",
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "specs_indexed": 0,
        "errors": 0,
        "error_message": "",
    }
    defaults.update(overrides)
    return defaults


class TestRowMappers:
    def test_row_to_installation(self):
        row = _make_install_row()
        inst = _row_to_installation(row)
        assert inst.installation_id == 12345
        assert inst.org_login == "test-org"
        assert inst.status == "active"

    def test_row_to_index_job(self):
        row = _make_job_row(status="running", specs_indexed=3)
        job = _row_to_index_job(row)
        assert job.id == 10
        assert job.status == "running"
        assert job.specs_indexed == 3


class TestUpsertInstallation:
    async def test_calls_insert_on_conflict(self):
        mock_conn = AsyncMock()
        row = _make_install_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)

        registry = InstallationRegistry(pool)
        result = await registry.upsert_installation(
            installation_id=12345, org_login="test-org", org_id=111, app_id="app-1"
        )

        assert result.installation_id == 12345
        assert result.org_login == "test-org"
        mock_conn.fetchrow.assert_awaited_once()
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO gh_installations" in sql
        assert "ON CONFLICT" in sql


class TestMarkStatus:
    async def test_mark_suspended(self):
        mock_conn = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)
        await registry.mark_suspended(12345)
        sql = mock_conn.execute.call_args[0][0]
        assert "suspended" in sql

    async def test_mark_removed(self):
        mock_conn = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)
        await registry.mark_removed(12345)
        sql = mock_conn.execute.call_args[0][0]
        assert "removed" in sql

    async def test_mark_unsuspended(self):
        mock_conn = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)
        await registry.mark_unsuspended(12345)
        sql = mock_conn.execute.call_args[0][0]
        assert "active" in sql


class TestQueryInstallations:
    async def test_get_active_installations(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[_make_install_row()])
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        results = await registry.get_active_installations()
        assert len(results) == 1
        assert results[0].org_login == "test-org"
        sql = mock_conn.fetch.call_args[0][0]
        assert "status = 'active'" in sql

    async def test_get_installation_by_org(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=_make_install_row())
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        result = await registry.get_installation_by_org("test-org")
        assert result is not None
        assert result.org_login == "test-org"

    async def test_get_installation_by_org_returns_none(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        result = await registry.get_installation_by_org("nonexistent")
        assert result is None

    async def test_get_installation_by_id(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=_make_install_row())
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        result = await registry.get_installation_by_id(12345)
        assert result is not None
        assert result.installation_id == 12345

    async def test_list_orgs(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[{"org_login": "org-a"}, {"org_login": "org-b"}])
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        orgs = await registry.list_orgs()
        assert orgs == ["org-a", "org-b"]


class TestUpdateLastIndexed:
    async def test_without_repos_count(self):
        mock_conn = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)
        await registry.update_last_indexed(12345)
        sql = mock_conn.execute.call_args[0][0]
        assert "last_indexed_at" in sql
        assert "repos_count" not in sql

    async def test_with_repos_count(self):
        mock_conn = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)
        await registry.update_last_indexed(12345, repos_count=10)
        sql = mock_conn.execute.call_args[0][0]
        assert "repos_count" in sql


class TestIndexJobs:
    async def test_create_index_job(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=_make_job_row())
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        job = await registry.create_index_job(installation_id=12345, repo="test-org/repo1")
        assert job.repo == "test-org/repo1"
        assert job.status == "pending"

    async def test_update_index_job_status(self):
        mock_conn = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        await registry.update_index_job(10, status="running")
        sql = mock_conn.execute.call_args[0][0]
        assert "status" in sql
        assert "started_at" in sql

    async def test_update_index_job_completed(self):
        mock_conn = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        await registry.update_index_job(10, status="completed", specs_indexed=5)
        sql = mock_conn.execute.call_args[0][0]
        assert "completed_at" in sql
        assert "specs_indexed" in sql

    async def test_update_index_job_noop(self):
        mock_conn = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        await registry.update_index_job(10)
        mock_conn.execute.assert_not_awaited()

    async def test_get_index_jobs_all(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[_make_job_row()])
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        jobs = await registry.get_index_jobs()
        assert len(jobs) == 1

    async def test_get_index_jobs_filtered(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[_make_job_row()])
        pool = _mock_pool_with_conn(mock_conn)
        registry = InstallationRegistry(pool)

        jobs = await registry.get_index_jobs(installation_id=12345)
        assert len(jobs) == 1
        sql = mock_conn.fetch.call_args[0][0]
        assert "installation_id" in sql
