"""Add audit_events table for admin action logging.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-31
"""

from __future__ import annotations

from alembic import op

revision: str = "0005"
down_revision: str = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            actor_id        BIGINT REFERENCES users(id),
            org             TEXT,
            event_type      TEXT NOT NULL,
            resource_type   TEXT NOT NULL,
            resource_id     TEXT NOT NULL,
            detail          JSONB,
            ip_address      INET
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_org_time ON audit_events (org, created_at DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events (actor_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_events (resource_type, resource_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_events (event_type)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_events")
