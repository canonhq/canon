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
