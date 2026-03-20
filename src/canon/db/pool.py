"""asyncpg connection pool lifecycle."""

from __future__ import annotations

import asyncpg


async def create_pool(dsn: str, *, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    """Create and return an asyncpg connection pool."""
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)


async def close_pool(pool: asyncpg.Pool) -> None:
    """Gracefully close the connection pool."""
    await pool.close()
