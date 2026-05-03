"""Add content cache tables for GitHub spec caching.

Extends spec_documents and spec_sections with raw content storage,
and adds repo_configs + repo_sync_state tables for tracking sync
state. This eliminates the need to fetch specs from GitHub on every
dashboard/MCP/cron request.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from alembic import op

revision: str = "0012"
down_revision: str = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- Extend spec_documents with raw content + sync metadata ---
    op.execute("ALTER TABLE spec_documents ADD COLUMN IF NOT EXISTS raw_markdown TEXT")
    op.execute("ALTER TABLE spec_documents ADD COLUMN IF NOT EXISTS github_etag VARCHAR(128)")
    op.execute("ALTER TABLE spec_documents ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ")
    op.execute("ALTER TABLE spec_documents ADD COLUMN IF NOT EXISTS github_sha VARCHAR(40)")

    # --- Extend spec_sections with raw section content ---
    op.execute("ALTER TABLE spec_sections ADD COLUMN IF NOT EXISTS raw_content TEXT")

    # --- repo_configs: cached CANON.yaml per repo ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS repo_configs (
            id              SERIAL PRIMARY KEY,
            installation_id BIGINT NOT NULL,
            owner           VARCHAR(255) NOT NULL,
            repo            VARCHAR(255) NOT NULL,
            config_yaml     TEXT,
            parsed_config   JSONB,
            github_etag     VARCHAR(128),
            synced_at       TIMESTAMPTZ,
            UNIQUE (owner, repo)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_repo_configs_installation ON repo_configs (installation_id)"
    )

    # --- repo_sync_state: per-repo sync tracking ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS repo_sync_state (
            id              SERIAL PRIMARY KEY,
            installation_id BIGINT NOT NULL,
            owner           VARCHAR(255) NOT NULL,
            repo            VARCHAR(255) NOT NULL,
            default_branch  VARCHAR(255),
            last_full_sync_at   TIMESTAMPTZ,
            last_push_sync_at   TIMESTAMPTZ,
            spec_count      INTEGER DEFAULT 0,
            sync_status     VARCHAR(32) DEFAULT 'pending',
            error_detail    TEXT,
            UNIQUE (owner, repo)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_repo_sync_state_installation "
        "ON repo_sync_state (installation_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS repo_sync_state")
    op.execute("DROP TABLE IF EXISTS repo_configs")
    op.execute("ALTER TABLE spec_sections DROP COLUMN IF EXISTS raw_content")
    op.execute("ALTER TABLE spec_documents DROP COLUMN IF EXISTS github_sha")
    op.execute("ALTER TABLE spec_documents DROP COLUMN IF EXISTS synced_at")
    op.execute("ALTER TABLE spec_documents DROP COLUMN IF EXISTS github_etag")
    op.execute("ALTER TABLE spec_documents DROP COLUMN IF EXISTS raw_markdown")
