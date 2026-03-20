"""Tests for SessionStore data access layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from canon.db.session_store import SessionStore


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock pool whose acquire() returns an async context manager."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


class TestCreateSession:
    async def test_inserts_session(self):
        mock_conn = AsyncMock()
        row = {
            "id": "sess-1",
            "user_id": 1,
            "org_login": "my-org",
            "device_label": "cli",
            "refresh_hash": "abc123",
            "created_at": datetime.now(UTC),
            "last_used_at": datetime.now(UTC),
            "expires_at": datetime.now(UTC),
            "revoked_at": None,
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        result = await store.create_session(
            session_id="sess-1",
            user_id=1,
            org_login="my-org",
            device_label="cli",
            refresh_hash="abc123",
            expires_at=datetime.now(UTC),
        )
        assert result["id"] == "sess-1"
        assert result["org_login"] == "my-org"
        assert result["device_label"] == "cli"
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO sessions" in sql


class TestGetSessionByRefreshHash:
    async def test_found(self):
        mock_conn = AsyncMock()
        row = {
            "id": "sess-1",
            "user_id": 1,
            "org_login": "my-org",
            "device_label": "cli",
            "refresh_hash": "abc123",
            "created_at": datetime.now(UTC),
            "last_used_at": datetime.now(UTC),
            "expires_at": datetime.now(UTC),
            "revoked_at": None,
            "user_sub": "auth0|123",
            "user_email": "test@example.com",
            "user_name": "Test",
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        result = await store.get_session_by_refresh_hash("abc123")
        assert result is not None
        assert result["user_sub"] == "auth0|123"
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "JOIN users" in sql
        assert "revoked_at IS NULL" in sql
        assert "expires_at > now()" in sql

    async def test_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        result = await store.get_session_by_refresh_hash("nonexistent")
        assert result is None


class TestRotateRefresh:
    async def test_success(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        result = await store.rotate_refresh(session_id="sess-1", old_hash="old", new_hash="new")
        assert result is True
        sql = mock_conn.execute.call_args[0][0]
        assert "refresh_hash" in sql
        assert "last_used_at" in sql

    async def test_stale_hash_fails(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        result = await store.rotate_refresh(session_id="sess-1", old_hash="wrong", new_hash="new")
        assert result is False


class TestRevokeSession:
    async def test_revoke_success(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        result = await store.revoke_session(session_id="sess-1", user_id=1)
        assert result is True

    async def test_revoke_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        result = await store.revoke_session(session_id="nonexistent", user_id=1)
        assert result is False


class TestRevokeAllSessions:
    async def test_revokes_all(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 3")
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        count = await store.revoke_all_sessions(user_id=1)
        assert count == 3
        sql = mock_conn.execute.call_args[0][0]
        assert "revoked_at" in sql
        assert "id !=" not in sql

    async def test_revokes_all_except_one(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 2")
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        count = await store.revoke_all_sessions(user_id=1, except_session_id="keep-me")
        assert count == 2
        sql = mock_conn.execute.call_args[0][0]
        assert "id !=" in sql

    async def test_none_to_revoke(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        count = await store.revoke_all_sessions(user_id=1)
        assert count == 0


class TestListSessions:
    async def test_returns_list(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": "sess-1",
                    "device_label": "cli",
                    "created_at": datetime.now(UTC),
                    "last_used_at": datetime.now(UTC),
                    "expires_at": datetime.now(UTC),
                },
                {
                    "id": "sess-2",
                    "device_label": "browser",
                    "created_at": datetime.now(UTC),
                    "last_used_at": datetime.now(UTC),
                    "expires_at": datetime.now(UTC),
                },
            ]
        )
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        sessions = await store.list_sessions(user_id=1, org_login="my-org")
        assert len(sessions) == 2
        assert sessions[0]["id"] == "sess-1"
        assert sessions[1]["device_label"] == "browser"
        sql = mock_conn.fetch.call_args[0][0]
        assert "expires_at > now()" in sql

    async def test_empty_list(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        sessions = await store.list_sessions(user_id=1, org_login="my-org")
        assert sessions == []


class TestDeleteExpiredSessions:
    async def test_deletes_expired(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 5")
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        count = await store.delete_expired_sessions()
        assert count == 5
        sql = mock_conn.execute.call_args[0][0]
        assert "DELETE FROM sessions" in sql
        assert "expires_at" in sql

    async def test_none_to_delete(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")
        pool = _mock_pool_with_conn(mock_conn)
        store = SessionStore(pool)

        count = await store.delete_expired_sessions()
        assert count == 0
