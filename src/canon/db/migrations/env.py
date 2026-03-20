"""Alembic environment configuration.

Uses an async SQLAlchemy engine backed by asyncpg (already a project dep)
so we don't need a separate sync PostgreSQL driver like psycopg2.

Called from a thread via asyncio.to_thread → safe to use asyncio.run().
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine


def _do_run_migrations(connection: object) -> None:
    """Configure and run migrations within a sync callback."""
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    """Create an async engine, run migrations, and dispose."""
    url = context.config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url not set — call run_upgrade() with a database_url")

    # Allow tests to specify a schema via config attributes for isolation.
    connect_args: dict = {}
    schema = context.config.attributes.get("schema") if context.config.attributes else None
    if schema:
        connect_args["server_settings"] = {"search_path": schema}

    connectable = create_async_engine(url, poolclass=pool.NullPool, connect_args=connect_args)

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


asyncio.run(_run_async_migrations())
