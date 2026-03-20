"""Tests for UserStore data access layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from canon.db.user_store import UserStore


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock pool whose acquire() returns an async context manager."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


class TestUpsertUser:
    async def test_inserts_user(self):
        mock_conn = AsyncMock()
        row = {
            "id": 1,
            "oidc_sub": "auth0|123",
            "email": "test@example.com",
            "name": "Test",
            "picture": "",
            "created_at": datetime.now(UTC),
            "last_login_at": datetime.now(UTC),
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.upsert_user(
            oidc_sub="auth0|123",
            email="test@example.com",
            name="Test",
        )
        assert result["oidc_sub"] == "auth0|123"
        assert result["email"] == "test@example.com"
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO users" in sql
        assert "ON CONFLICT" in sql

    async def test_returns_is_new_flag(self):
        mock_conn = AsyncMock()
        row = {
            "id": 1,
            "oidc_sub": "auth0|new",
            "email": "new@example.com",
            "name": "New",
            "picture": "",
            "created_at": datetime.now(UTC),
            "last_login_at": datetime.now(UTC),
            "is_new": True,
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.upsert_user(oidc_sub="auth0|new", email="new@example.com")
        assert result["is_new"] is True
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "is_new" in sql

    async def test_returns_is_new_false_on_update(self):
        mock_conn = AsyncMock()
        row = {
            "id": 1,
            "oidc_sub": "auth0|existing",
            "email": "existing@example.com",
            "name": "Existing",
            "picture": "",
            "created_at": datetime.now(UTC),
            "last_login_at": datetime.now(UTC),
            "is_new": False,
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.upsert_user(oidc_sub="auth0|existing", email="existing@example.com")
        assert result["is_new"] is False


class TestGetUserBySub:
    async def test_found(self):
        mock_conn = AsyncMock()
        row = {"id": 1, "oidc_sub": "auth0|123", "email": "test@example.com"}
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.get_user_by_sub("auth0|123")
        assert result is not None
        assert result["oidc_sub"] == "auth0|123"

    async def test_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.get_user_by_sub("nonexistent")
        assert result is None


class TestCreateApiKey:
    async def test_creates_key(self):
        mock_conn = AsyncMock()
        row = {
            "id": 1,
            "key_hash": "abc",
            "label": "test key",
            "user_id": 1,
            "org_login": "my-org",
            "scopes": ["specs:read"],
            "created_at": datetime.now(UTC),
            "expires_at": None,
            "revoked_at": None,
            "last_used_at": None,
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        raw_key, record = await store.create_api_key(
            user_id=1,
            org_login="my-org",
            scopes=["specs:read"],
            label="test key",
        )
        assert raw_key.startswith("sw_")
        assert record["label"] == "test key"
        assert record["scopes"] == ["specs:read"]


class TestGetApiKeyByHash:
    async def test_found(self):
        mock_conn = AsyncMock()
        row = {
            "id": 1,
            "key_hash": "abc",
            "user_sub": "auth0|123",
            "user_email": "test@example.com",
            "user_name": "Test",
            "org_login": "my-org",
            "scopes": ["specs:read"],
            "revoked_at": None,
            "expires_at": None,
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.execute = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.get_api_key_by_hash("abc")
        assert result is not None
        assert result["user_sub"] == "auth0|123"

    async def test_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.get_api_key_by_hash("nonexistent")
        assert result is None


class TestListApiKeys:
    async def test_returns_list(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "label": "key1",
                    "org_login": "my-org",
                    "scopes": ["specs:read"],
                    "created_at": datetime.now(UTC),
                    "expires_at": None,
                    "revoked_at": None,
                    "last_used_at": None,
                },
            ]
        )
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        keys = await store.list_api_keys(user_id=1, org_login="my-org")
        assert len(keys) == 1
        assert keys[0]["label"] == "key1"


class TestRevokeApiKey:
    async def test_revoke_success(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.revoke_api_key(key_id=1, user_id=1, org_login="test-org")
        assert result is True

    async def test_revoke_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.revoke_api_key(key_id=999, user_id=1, org_login="test-org")
        assert result is False


class TestCountUsers:
    async def test_returns_zero_when_empty(self):
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        count = await store.count_users()
        assert count == 0
        sql = mock_conn.fetchval.call_args[0][0]
        assert "SELECT COUNT(*) FROM users" in sql

    async def test_returns_correct_count_after_inserts(self):
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=3)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        count = await store.count_users()
        assert count == 3


class TestSetUserRole:
    async def test_updates_role(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        await store.set_user_role(user_id=1, role="admin")
        mock_conn.execute.assert_awaited_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "UPDATE users SET role" in sql
        # Verify correct positional args: role=$1, id=$2
        args = mock_conn.execute.call_args[0]
        assert args[1] == "admin"
        assert args[2] == 1

    async def test_updates_to_viewer_role(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        await store.set_user_role(user_id=42, role="viewer")
        args = mock_conn.execute.call_args[0]
        assert args[1] == "viewer"
        assert args[2] == 42


class TestPromoteFirstUserToAdmin:
    async def test_returns_true_when_promoted(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.promote_first_user_to_admin(1)
        assert result is True
        sql = mock_conn.execute.call_args[0][0]
        assert "NOT EXISTS" in sql

    async def test_returns_false_when_admin_exists(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        result = await store.promote_first_user_to_admin(2)
        assert result is False


class TestDeleteExpiredKeys:
    async def test_deletes_expired(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 3")
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        count = await store.delete_expired_keys()
        assert count == 3
        sql = mock_conn.execute.call_args[0][0]
        assert "DELETE FROM api_keys" in sql
        assert "expires_at" in sql

    async def test_none_to_delete(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")
        pool = _mock_pool_with_conn(mock_conn)
        store = UserStore(pool)

        count = await store.delete_expired_keys()
        assert count == 0
