"""Add error_issue_map table for SRE auto-triage dedup.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-20
"""

from __future__ import annotations

from alembic import op

revision: str = "0003"
down_revision: str = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS error_issue_map (
            id              BIGSERIAL PRIMARY KEY,
            fingerprint     TEXT NOT NULL,
            repo            TEXT NOT NULL,
            issue_number    INT NOT NULL,
            issue_url       TEXT NOT NULL DEFAULT '',
            severity        TEXT NOT NULL DEFAULT 'medium',
            first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            occurrence_count INT NOT NULL DEFAULT 1,
            resolved_at     TIMESTAMPTZ,
            UNIQUE (fingerprint, repo)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_error_issue_map_fingerprint "
        "ON error_issue_map (fingerprint)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_error_issue_map_repo ON error_issue_map (repo)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_error_issue_map_issue "
        "ON error_issue_map (repo, issue_number)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS error_issue_map")
