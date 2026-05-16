"""Tests for database pool lifecycle."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from canon.db.pool import _init_connection, close_pool, create_pool


class TestCreatePool:
    async def test_calls_asyncpg_create_pool(self):
        mock_pool = AsyncMock()
        with patch(
            "canon.db.pool.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool
        ) as mock_create:
            pool = await create_pool("postgres://localhost/test")
            mock_create.assert_awaited_once_with(
                "postgres://localhost/test",
                min_size=2,
                max_size=10,
                init=_init_connection,
            )
            assert pool is mock_pool

    async def test_custom_pool_sizes(self):
        mock_pool = AsyncMock()
        with patch(
            "canon.db.pool.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool
        ) as mock_create:
            await create_pool("postgres://localhost/test", min_size=1, max_size=5)
            mock_create.assert_awaited_once_with(
                "postgres://localhost/test",
                min_size=1,
                max_size=5,
                init=_init_connection,
            )


class TestInitConnection:
    async def test_registers_jsonb_and_json_codecs(self):
        conn = AsyncMock()
        await _init_connection(conn)
        # Both jsonb and json types must be registered so callers can read
        # row values directly as dicts/lists instead of raw JSON strings.
        kinds = {call.args[0] for call in conn.set_type_codec.await_args_list}
        assert kinds == {"jsonb", "json"}
        for call in conn.set_type_codec.await_args_list:
            assert call.kwargs["encoder"] is json.dumps
            assert call.kwargs["decoder"] is json.loads
            assert call.kwargs["schema"] == "pg_catalog"

    async def test_propagates_codec_registration_failure(self):
        # A partially-broken codec would silently fall back to raw strings,
        # reintroducing the AttributeError this PR fixes. Reject the connection.
        conn = AsyncMock()
        conn.set_type_codec.side_effect = RuntimeError("boom")
        try:
            await _init_connection(conn)
        except RuntimeError as exc:
            assert str(exc) == "boom"
        else:
            raise AssertionError("expected RuntimeError to propagate")


class TestClosePool:
    async def test_calls_pool_close(self):
        mock_pool = AsyncMock()
        await close_pool(mock_pool)
        mock_pool.close.assert_awaited_once()
