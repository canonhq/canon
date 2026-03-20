"""Integration tests for Alembic migrations against a real PostgreSQL instance.

These tests verify that migrations apply cleanly, produce the expected schema,
and preserve data across column renames.  They require a running PostgreSQL
server and are marked ``@pytest.mark.integration`` so they are skipped by
default (the project's ``addopts = "-m 'not integration'"`` handles this).

Set ``TEST_DATABASE_URL`` to override the default connection string.

Usage::

    uv run pytest -m integration tests/test_db/test_migrations.py -v
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from collections.abc import AsyncGenerator

import pytest

# ---------------------------------------------------------------------------
# Dependency / connectivity checks
# ---------------------------------------------------------------------------

try:
    import asyncpg
    from alembic import command
    from alembic.config import Config

    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://canon:test@localhost:5432/canon_test",
)


def _can_connect() -> bool:
    """Return *True* if the test database is reachable."""
    if not HAS_DEPS:
        return False
    try:
        loop = asyncio.new_event_loop()
        try:

            async def _check() -> None:
                conn = await asyncpg.connect(TEST_DB_URL, timeout=5)
                await conn.close()

            loop.run_until_complete(_check())
        finally:
            loop.close()
        return True
    except Exception:
        return False


# Evaluated once at module import; caches the result for all tests.
_DB_AVAILABLE = _can_connect()

skip_no_db = pytest.mark.skipif(
    not _DB_AVAILABLE,
    reason="Test database not available (set TEST_DATABASE_URL)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alembic_cfg(schema: str) -> Config:
    """Build an Alembic ``Config`` that targets *schema* within the test DB.

    We use SQLAlchemy's async engine (``postgresql+asyncpg://``) as required
    by the project's ``env.py``.  The schema is passed via ``cfg.attributes``
    so the env.py can set ``search_path`` via asyncpg's ``server_settings``
    (asyncpg does not support the libpq ``options`` URL parameter).
    """
    import importlib.resources

    ini_path = str(importlib.resources.files("canon.db").joinpath("alembic.ini"))
    cfg = Config(ini_path)

    migrations_dir = str(importlib.resources.files("canon.db").joinpath("migrations"))
    cfg.set_main_option("script_location", migrations_dir)

    sqla_url = TEST_DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    cfg.set_main_option("sqlalchemy.url", sqla_url)

    # Pass schema via attributes — env.py reads this to set search_path.
    cfg.attributes["schema"] = schema

    return cfg


async def _create_schema(schema: str) -> asyncpg.Connection:
    """Create an isolated PostgreSQL schema and return a connection to it."""
    conn = await asyncpg.connect(TEST_DB_URL, timeout=5)
    await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    await conn.execute(f'SET search_path TO "{schema}"')
    return conn


async def _drop_schema(schema: str) -> None:
    """Drop a schema and everything inside it."""
    conn = await asyncpg.connect(TEST_DB_URL, timeout=5)
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        await conn.close()


async def _table_names(conn: asyncpg.Connection, schema: str) -> set[str]:
    """Return all table names in the given schema."""
    rows = await conn.fetch(
        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = $1",
        schema,
    )
    return {row["tablename"] for row in rows}


async def _column_names(conn: asyncpg.Connection, schema: str, table: str) -> set[str]:
    """Return column names for *table* in *schema*."""
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = $1 AND table_name = $2",
        schema,
        table,
    )
    return {row["column_name"] for row in rows}


async def _column_default(
    conn: asyncpg.Connection, schema: str, table: str, column: str
) -> str | None:
    """Return the column default expression, or *None*."""
    row = await conn.fetchrow(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = $1 AND table_name = $2 AND column_name = $3",
        schema,
        table,
        column,
    )
    return row["column_default"] if row else None


def _run_upgrade(cfg: Config, revision: str = "head") -> None:
    """Run ``alembic upgrade`` synchronously (env.py uses asyncio.run internally)."""
    command.upgrade(cfg, revision)


async def _run_upgrade_async(cfg: Config, revision: str = "head") -> None:
    """Run ``alembic upgrade`` in a thread to avoid nested asyncio.run()."""
    await asyncio.to_thread(command.upgrade, cfg, revision)


def _run_downgrade(cfg: Config, revision: str) -> None:
    """Run ``alembic downgrade`` synchronously."""
    command.downgrade(cfg, revision)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def schema_name() -> str:
    """Generate a unique schema name for test isolation."""
    return f"test_mig_{uuid.uuid4().hex[:12]}"


@pytest.fixture()
async def pg_schema(schema_name: str) -> AsyncGenerator[str, None]:
    """Create a fresh Postgres schema, yield its name, and tear it down."""
    conn = await _create_schema(schema_name)
    # Ensure the vector extension is available (needed by 0001_baseline).
    # The extension is installed at the database level, not per-schema.
    with contextlib.suppress(Exception):
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await conn.close()
    yield schema_name
    await _drop_schema(schema_name)


@pytest.fixture()
def cfg(pg_schema: str) -> Config:
    """Alembic config wired to the test schema."""
    return _alembic_cfg(pg_schema)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
@skip_no_db
class TestMigrations:
    """Validate that Alembic migrations apply cleanly against PostgreSQL."""

    # -- 1. Upgrade to head without errors -----------------------------------

    def test_upgrade_to_head(self, cfg: Config) -> None:
        """Applying all migrations from an empty database to head succeeds."""
        _run_upgrade(cfg, "head")

    # -- 2. Baseline creates expected tables ---------------------------------

    @pytest.mark.asyncio
    async def test_baseline_creates_tables(self, cfg: Config, pg_schema: str) -> None:
        """After 0001, ``users`` and ``gh_installations`` tables exist."""
        await _run_upgrade_async(cfg, "0001")

        conn = await asyncpg.connect(TEST_DB_URL, timeout=5)
        try:
            tables = await _table_names(conn, pg_schema)
        finally:
            await conn.close()

        assert "users" in tables
        assert "gh_installations" in tables
        # Spot-check a few more tables from the baseline.
        assert "spec_documents" in tables
        assert "sessions" in tables
        assert "subscriptions" in tables

    # -- 3. OIDC rename columns ----------------------------------------------

    @pytest.mark.asyncio
    async def test_oidc_rename_columns(self, cfg: Config, pg_schema: str) -> None:
        """After 0002, ``oidc_sub`` exists in users, ``auth0_sub`` does not.

        The baseline (0001) already creates ``oidc_sub`` directly, so the
        0002 migration's idempotent ``IF EXISTS`` guard means the rename is
        a no-op on fresh databases.  We verify the final state is correct.
        """
        await _run_upgrade_async(cfg, "0002")

        conn = await asyncpg.connect(TEST_DB_URL, timeout=5)
        try:
            user_cols = await _column_names(conn, pg_schema, "users")
            inst_cols = await _column_names(conn, pg_schema, "gh_installations")
        finally:
            await conn.close()

        assert "oidc_sub" in user_cols
        assert "auth0_sub" not in user_cols

        assert "oidc_org_id" in inst_cols
        assert "auth0_org_id" not in inst_cols

    # -- 4. Role column added ------------------------------------------------

    @pytest.mark.asyncio
    async def test_role_column_added(self, cfg: Config, pg_schema: str) -> None:
        """After 0002, ``users.role`` exists with default ``'editor'``."""
        await _run_upgrade_async(cfg, "0002")

        conn = await asyncpg.connect(TEST_DB_URL, timeout=5)
        try:
            cols = await _column_names(conn, pg_schema, "users")
            default = await _column_default(conn, pg_schema, "users", "role")
        finally:
            await conn.close()

        assert "role" in cols
        # The default is stored as a string literal, e.g. ``'editor'::text``.
        assert default is not None
        assert "editor" in default

    # -- 5. Data survives rename ---------------------------------------------

    @pytest.mark.asyncio
    async def test_data_survives_rename(self, cfg: Config, pg_schema: str) -> None:
        """Insert a user at 0001, upgrade to 0002, verify data in ``oidc_sub``.

        Because the consolidated 0001 already creates ``oidc_sub``, we first
        upgrade to 0001, then *manually* rename the column back to
        ``auth0_sub`` to simulate a legacy database, insert test data, and
        finally upgrade to 0002 which performs the rename.
        """
        # 1. Apply baseline.
        await _run_upgrade_async(cfg, "0001")

        conn = await asyncpg.connect(TEST_DB_URL, timeout=5)
        try:
            await conn.execute(f'SET search_path TO "{pg_schema}"')

            # 2. Simulate legacy schema: rename oidc_sub -> auth0_sub.
            await conn.execute("ALTER TABLE users RENAME COLUMN oidc_sub TO auth0_sub")

            # 3. Insert a user with the old column name.
            test_sub = f"auth0|test-{uuid.uuid4().hex[:8]}"
            await conn.execute(
                "INSERT INTO users (auth0_sub, email) VALUES ($1, $2)",
                test_sub,
                "test@example.com",
            )

            # Verify it's there under the old name.
            row = await conn.fetchrow(
                "SELECT auth0_sub FROM users WHERE email = 'test@example.com'"
            )
            assert row is not None
            assert row["auth0_sub"] == test_sub
        finally:
            await conn.close()

        # 4. Apply 0002 which renames auth0_sub -> oidc_sub.
        await _run_upgrade_async(cfg, "0002")

        # 5. Verify data is now accessible under oidc_sub.
        conn = await asyncpg.connect(TEST_DB_URL, timeout=5)
        try:
            await conn.execute(f'SET search_path TO "{pg_schema}"')
            row = await conn.fetchrow("SELECT oidc_sub FROM users WHERE email = 'test@example.com'")
            assert row is not None
            assert row["oidc_sub"] == test_sub
        finally:
            await conn.close()

    # -- 6. Migrations are idempotent ----------------------------------------

    def test_migrations_idempotent(self, cfg: Config) -> None:
        """Upgrading to head twice in a row does not error."""
        _run_upgrade(cfg, "head")
        _run_upgrade(cfg, "head")
