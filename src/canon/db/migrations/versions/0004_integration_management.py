"""Add user_connections and org_integrations tables for integration management.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-31
"""

from __future__ import annotations

from alembic import op

revision: str = "0004"
down_revision: str = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- user_connections: user-level VCS OAuth tokens (e.g. GitHub) ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_connections (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider            TEXT NOT NULL,
            provider_user_id    TEXT NOT NULL,
            provider_login      TEXT NOT NULL,
            encrypted_token     BYTEA NOT NULL,
            refresh_token       BYTEA,
            scopes              TEXT[] DEFAULT '{}',
            token_expires_at    TIMESTAMPTZ,
            connected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, provider)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_connections_user_id ON user_connections (user_id)"
    )

    # --- org_integrations: org-level ticketing/notification OAuth credentials ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS org_integrations (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_login           TEXT NOT NULL,
            provider            TEXT NOT NULL,
            display_name        TEXT NOT NULL,
            encrypted_config    BYTEA NOT NULL,
            status              TEXT NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'needs_reauth', 'error', 'disabled')),
            provider_metadata   JSONB NOT NULL DEFAULT '{}',
            connected_by        BIGINT REFERENCES users(id),
            connected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (org_login, provider)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_org_integrations_org_login ON org_integrations (org_login)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_org_integrations_org_provider "
        "ON org_integrations (org_login, provider)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS org_integrations")
    op.execute("DROP TABLE IF EXISTS user_connections")
