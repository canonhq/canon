"""Add organizations_meta table for admin-editable org metadata.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-11

Adds a Canon-side metadata table for organizations. The authoritative
org name still lives in Auth0 (display_name via the Management API); this
table holds support-facing fields that don't belong in the identity provider:
primary contact, support notes, and bookkeeping for who last touched the row.

Keyed by org_login rather than installation_id so metadata survives a
GitHub App reinstall (which gets a new installation_id but reuses the same
org_login).
"""

from __future__ import annotations

from alembic import op

revision: str = "0007"
down_revision: str = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS organizations_meta (
            org_login               TEXT PRIMARY KEY,
            primary_contact_email   TEXT,
            primary_contact_name    TEXT,
            support_notes           TEXT,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by_sub          TEXT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS organizations_meta")
