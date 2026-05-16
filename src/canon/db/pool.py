"""asyncpg connection pool lifecycle."""

from __future__ import annotations

import asyncio
import logging

import asyncpg

logger = logging.getLogger(__name__)

_CONNECT_MAX_RETRIES = 3
_CONNECT_BASE_DELAY = 2.0  # seconds


async def create_pool(dsn: str, *, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    """Create and return an asyncpg connection pool with retry.

    Retries up to ``_CONNECT_MAX_RETRIES`` times with exponential backoff
    to handle transient issues like Postgres pods not being ready yet
    during a K8s rollout.
    """
    last_exc: Exception | None = None
    for attempt in range(_CONNECT_MAX_RETRIES + 1):
        try:
            return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
        except Exception as exc:
            last_exc = exc
            if attempt == _CONNECT_MAX_RETRIES:
                break
            delay = _CONNECT_BASE_DELAY * (2**attempt)
            logger.warning(
                "Database connection attempt %d/%d failed, retrying in %.1fs: %s",
                attempt + 1,
                _CONNECT_MAX_RETRIES + 1,
                delay,
                exc,
            )
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]


async def close_pool(pool: asyncpg.Pool) -> None:
    """Gracefully close the connection pool."""
    await pool.close()
