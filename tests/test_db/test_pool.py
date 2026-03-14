"""Tests for database pool lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from canon.db.pool import close_pool, create_pool


class TestCreatePool:
    async def test_calls_asyncpg_create_pool(self):
        mock_pool = AsyncMock()
        with patch(
            "canon.db.pool.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool
        ) as mock_create:
            pool = await create_pool("postgres://localhost/test")
            mock_create.assert_awaited_once_with(
                "postgres://localhost/test", min_size=2, max_size=10
            )
            assert pool is mock_pool

    async def test_custom_pool_sizes(self):
        mock_pool = AsyncMock()
        with patch(
            "canon.db.pool.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool
        ) as mock_create:
            await create_pool("postgres://localhost/test", min_size=1, max_size=5)
            mock_create.assert_awaited_once_with(
                "postgres://localhost/test", min_size=1, max_size=5
            )


class TestClosePool:
    async def test_calls_pool_close(self):
        mock_pool = AsyncMock()
        await close_pool(mock_pool)
        mock_pool.close.assert_awaited_once()
