"""Rename Auth0-specific columns to generic OIDC terminology.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-18
"""

from __future__ import annotations

from alembic import op

revision: str = "0002"
down_revision: str = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Idempotent renames: fresh installs already have oidc_* columns from the
    # updated 0001 baseline, so guard with existence checks.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name='users' AND column_name='auth0_sub')
             AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name='users' AND column_name='oidc_sub')
          THEN ALTER TABLE users RENAME COLUMN auth0_sub TO oidc_sub;
          END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name='gh_installations' AND column_name='auth0_org_id')
             AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name='gh_installations' AND column_name='oidc_org_id')
          THEN ALTER TABLE gh_installations RENAME COLUMN auth0_org_id TO oidc_org_id;
          END IF;
        END $$
    """)
    # If both old and new columns exist (partial prior migration), drop the old one.
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS auth0_sub")
    op.execute("ALTER TABLE gh_installations DROP COLUMN IF EXISTS auth0_org_id")
    op.execute("DROP INDEX IF EXISTS idx_gh_installations_auth0_org_id")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gh_installations_oidc_org_id "
        "ON gh_installations (oidc_org_id) WHERE oidc_org_id != ''"
    )
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'editor'")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS role")
    op.execute("DROP INDEX IF EXISTS idx_gh_installations_oidc_org_id")
    # Idempotent renames: guard with IF EXISTS for consistency with upgrade()
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name='gh_installations' AND column_name='oidc_org_id')
          THEN ALTER TABLE gh_installations RENAME COLUMN oidc_org_id TO auth0_org_id;
          END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name='users' AND column_name='oidc_sub')
          THEN ALTER TABLE users RENAME COLUMN oidc_sub TO auth0_sub;
          END IF;
        END $$
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gh_installations_auth0_org_id "
        "ON gh_installations (auth0_org_id)"
    )
