"""Schema initialization via Alembic migrations."""

from __future__ import annotations

import asyncio
import importlib.resources
import logging

import asyncpg

logger = logging.getLogger(__name__)


def _load_sql(filename: str) -> str:
    """Load a SQL file from the package resources."""
    return importlib.resources.files(__package__).joinpath(filename).read_text("utf-8")


async def ensure_schema(pool: asyncpg.Pool, database_url: str) -> None:
    """Run Alembic migrations, then best-effort BM25 index.

    Alembic's synchronous ``command.upgrade()`` is offloaded to a thread
    via ``asyncio.to_thread`` to avoid blocking the event loop.
    """
    from .migrate import run_upgrade

    await asyncio.to_thread(run_upgrade, database_url)

    # Best-effort: ParadeDB BM25 index (stays outside Alembic)
    try:
        bm25_ddl = _load_sql("schema_bm25.sql")
        async with pool.acquire() as conn:
            await conn.execute(bm25_ddl)
    except Exception:
        logger.info(
            "ParadeDB BM25 index not available — skipping (vector + BM25-less search still works)"
        )
