"""Programmatic Alembic migration runner.

All database access uses asyncpg (already a project dependency) so no
additional sync PostgreSQL driver is required.  Since this module is called
from ``asyncio.to_thread`` there is no running event loop in the thread,
making ``asyncio.run()`` safe to call.
"""

from __future__ import annotations

import asyncio
import importlib.resources
import logging
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import asyncpg
from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

BASELINE_REV = "0001"


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _to_asyncpg_url(url: str) -> str:
    """Normalise a database URL for raw asyncpg (``postgresql://`` scheme)."""
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


_SSLMODE_TO_SSL: dict[str, str | None] = {
    "disable": None,
    # asyncpg has no partial-SSL mode; upgrade to require rather than silently
    # falling back to plaintext, which would be a security downgrade.
    "allow": "require",
    "prefer": "require",
    "require": "require",
    "verify-ca": "verify-full",
    "verify-full": "verify-full",
}


def _convert_sslmode_params(url: str) -> str:
    """Replace ``sslmode`` query param with asyncpg-compatible ``ssl``.

    SQLAlchemy's asyncpg dialect passes query-string parameters directly to
    ``asyncpg.connect()`` which does **not** accept ``sslmode``.  This
    function converts ``sslmode`` to the equivalent ``ssl`` parameter that
    asyncpg understands.
    """
    parts = urlsplit(url)
    params = parse_qs(parts.query, keep_blank_values=True)

    sslmode_values = params.pop("sslmode", None)
    if sslmode_values is None:
        return url  # nothing to convert

    sslmode = sslmode_values[0]

    if sslmode not in _SSLMODE_TO_SSL:
        logger.warning("Unrecognised sslmode %r — passing through unchanged", sslmode)
        return url

    ssl_value = _SSLMODE_TO_SSL[sslmode]

    # Only set ssl if there isn't already an explicit ssl param
    if ssl_value is not None and "ssl" not in params:
        params["ssl"] = [ssl_value]
    elif ssl_value is None:
        # disable → remove ssl entirely
        params.pop("ssl", None)

    new_query = urlencode(params, doseq=True)
    return urlunsplit(parts._replace(query=new_query))


def _to_sqla_async_url(url: str) -> str:
    """Normalise a database URL for SQLAlchemy's asyncpg dialect."""
    url = _to_asyncpg_url(url)
    url = _convert_sslmode_params(url)
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


# ---------------------------------------------------------------------------
# Alembic config
# ---------------------------------------------------------------------------


def _alembic_cfg(database_url: str) -> Config:
    """Build an Alembic Config pointing at our bundled migrations."""
    ini_path = str(importlib.resources.files(__package__).joinpath("alembic.ini"))
    cfg = Config(ini_path)

    # Override script_location to absolute path (works inside wheels)
    migrations_dir = str(importlib.resources.files(__package__).joinpath("migrations"))
    cfg.set_main_option("script_location", migrations_dir)
    cfg.set_main_option("sqlalchemy.url", _to_sqla_async_url(database_url))

    return cfg


# ---------------------------------------------------------------------------
# Auto-stamp for existing databases
# ---------------------------------------------------------------------------


async def _get_public_tables(url: str) -> set[str]:
    """Return the set of public table names in the database."""
    conn = await asyncpg.connect(_to_asyncpg_url(url))
    try:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
        )
        return {row["tablename"] for row in rows}
    finally:
        await conn.close()


async def _apply_legacy_migrations(url: str) -> None:
    """Run the idempotent DO $$ migration blocks from the old SQL files.

    Ensures existing databases have all columns before we stamp them at the
    baseline revision (which assumes the full schema is present).
    """
    legacy_blocks = [
        # schema.sql: resize embeddings 1536 -> 1024
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'spec_documents' AND column_name = 'embedding'
            ) THEN
                DROP INDEX IF EXISTS idx_spec_documents_embedding;
                ALTER TABLE spec_documents ALTER COLUMN embedding TYPE vector(1024);
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'spec_sections' AND column_name = 'embedding'
            ) THEN
                DROP INDEX IF EXISTS idx_spec_sections_embedding;
                ALTER TABLE spec_sections ALTER COLUMN embedding TYPE vector(1024);
            END IF;
        END
        $$
        """,
        # schema.sql: add commit_sha
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'spec_documents' AND column_name = 'commit_sha'
            ) THEN
                ALTER TABLE spec_documents ADD COLUMN commit_sha TEXT NOT NULL DEFAULT '';
            END IF;
        END
        $$
        """,
        # schema.sql: add doc_type, staleness columns
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'spec_documents' AND column_name = 'doc_type'
            ) THEN
                ALTER TABLE spec_documents ADD COLUMN doc_type TEXT NOT NULL DEFAULT 'spec';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'spec_documents' AND column_name = 'last_code_change_at'
            ) THEN
                ALTER TABLE spec_documents ADD COLUMN last_code_change_at TIMESTAMPTZ;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'spec_documents' AND column_name = 'last_doc_change_at'
            ) THEN
                ALTER TABLE spec_documents ADD COLUMN last_doc_change_at TIMESTAMPTZ;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'spec_documents' AND column_name = 'stale_since'
            ) THEN
                ALTER TABLE spec_documents ADD COLUMN stale_since TIMESTAMPTZ;
            END IF;
        END
        $$
        """,
        # schema_installations.sql: add auth0_org_id (legacy name — 0002 migration renames it)
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'gh_installations' AND column_name = 'auth0_org_id'
            ) THEN
                ALTER TABLE gh_installations ADD COLUMN auth0_org_id TEXT NOT NULL DEFAULT '';
            END IF;
        END
        $$
        """,
        # schema_billing.sql: make stripe_customer_id nullable
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'subscriptions' AND column_name = 'stripe_customer_id'
                    AND is_nullable = 'NO'
            ) THEN
                ALTER TABLE subscriptions ALTER COLUMN stripe_customer_id DROP NOT NULL;
            END IF;
        END
        $$
        """,
        # Re-create HNSW indices after potential resize
        """
        CREATE INDEX IF NOT EXISTS idx_spec_documents_embedding
            ON spec_documents USING hnsw (embedding vector_cosine_ops)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_spec_sections_embedding
            ON spec_sections USING hnsw (embedding vector_cosine_ops)
        """,
    ]

    conn = await asyncpg.connect(_to_asyncpg_url(url))
    try:
        for block in legacy_blocks:
            await conn.execute(block)
    finally:
        await conn.close()


def _auto_stamp_if_needed(database_url: str) -> bool:
    """If real tables exist but alembic_version doesn't, stamp at baseline.

    Returns True if a stamp was applied.
    """
    tables = asyncio.run(_get_public_tables(database_url))

    has_real_tables = bool(tables & {"spec_documents", "users", "gh_installations"})
    has_alembic = "alembic_version" in tables

    if has_real_tables and not has_alembic:
        logger.info(
            "Existing database detected without alembic_version — stamping at %s",
            BASELINE_REV,
        )
        asyncio.run(_apply_legacy_migrations(database_url))
        cfg = _alembic_cfg(database_url)
        command.stamp(cfg, BASELINE_REV)
        return True

    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_upgrade(database_url: str, revision: str = "head") -> None:
    """Run Alembic migrations up to *revision*.

    Call from ``asyncio.to_thread(run_upgrade, url)`` when inside an async
    context, or directly from a sync CLI entry point.
    """
    _auto_stamp_if_needed(database_url)
    cfg = _alembic_cfg(database_url)
    command.upgrade(cfg, revision)
    logger.info("Database migrated to %s", revision)
