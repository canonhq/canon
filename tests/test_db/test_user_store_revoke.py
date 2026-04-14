"""Tests for bulk API key revocation in UserStore."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from canon.db.user_store import UserStore


def _mock_pool(conn: AsyncMock) -> MagicMock:
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool


class TestRevokeAllApiKeys:
    async def test_revokes_active_keys_returns_count(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 3")
        store = UserStore(_mock_pool(conn))

        count = await store.revoke_all_api_keys(user_id=42)

        assert count == 3
        sql = conn.execute.call_args[0][0]
        assert "UPDATE api_keys" in sql
        assert "revoked_at" in sql
        assert conn.execute.call_args[0][1] == 42

    async def test_returns_zero_when_no_active_keys(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 0")
        store = UserStore(_mock_pool(conn))

        count = await store.revoke_all_api_keys(user_id=99)

        assert count == 0


class TestListApiKeysForAdmin:
    async def test_returns_cross_org_keys(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "label": "ci",
                    "user_id": 42,
                    "org_login": "acme",
                    "scopes": ["read"],
                    "created_at": None,
                    "expires_at": None,
                    "revoked_at": None,
                    "last_used_at": None,
                },
                {
                    "id": 2,
                    "label": "personal",
                    "user_id": 42,
                    "org_login": "personal",
                    "scopes": ["read", "write"],
                    "created_at": None,
                    "expires_at": None,
                    "revoked_at": None,
                    "last_used_at": None,
                },
            ]
        )
        store = UserStore(_mock_pool(conn))

        keys = await store.list_api_keys_for_admin(user_id=42)

        assert len(keys) == 2
        sql = conn.fetch.call_args[0][0]
        # No org_login filter (admin sees all orgs)
        where_clause = sql.split("WHERE")[1].split("ORDER BY")[0]
        assert "org_login" not in where_clause
        # key_hash never returned (only the hash exists in the DB anyway)
        assert "key_hash" not in sql

    async def test_empty(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        store = UserStore(_mock_pool(conn))

        assert await store.list_api_keys_for_admin(user_id=42) == []


class TestRevokeApiKeyForAdmin:
    async def test_revokes_when_found(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        store = UserStore(_mock_pool(conn))

        result = await store.revoke_api_key_for_admin(key_id=7, user_id=42)

        assert result is True
        sql = conn.execute.call_args[0][0]
        # No org_login arg (admin doesn't need tenant scoping)
        where_clause = sql.split("WHERE")[1]
        assert "org_login" not in where_clause
        assert conn.execute.call_args[0][1] == 7
        assert conn.execute.call_args[0][2] == 42

    async def test_returns_false_when_not_found(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 0")
        store = UserStore(_mock_pool(conn))

        result = await store.revoke_api_key_for_admin(key_id=999, user_id=42)

        assert result is False
