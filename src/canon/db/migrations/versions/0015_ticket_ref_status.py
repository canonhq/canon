"""Track persistently-broken ticket references so the canon-sync cron
stops re-checking dead refs every 15 min and the dashboard can surface
them for cleanup.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from alembic import op

revision: str = "0015"
down_revision: str = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_ref_status (
            id              BIGSERIAL PRIMARY KEY,
            installation_id BIGINT NOT NULL,
            system          TEXT   NOT NULL,
            ticket_ref      TEXT   NOT NULL,
            status          TEXT NOT NULL DEFAULT 'ok',
            consecutive_failures   INT  NOT NULL DEFAULT 0,
            last_error_kind        TEXT,
            last_error_message     TEXT,
            first_failure_at TIMESTAMPTZ,
            last_check_at    TIMESTAMPTZ,
            last_recheck_at  TIMESTAMPTZ,
            dismissed_at     TIMESTAMPTZ,
            dismissed_by     TEXT,
            UNIQUE (installation_id, system, ticket_ref)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ticket_ref_status_broken_idx
            ON ticket_ref_status (installation_id, status)
            WHERE status IN ('broken', 'dismissed')
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ticket_ref_status_recheck_idx
            ON ticket_ref_status (status, last_recheck_at)
            WHERE status = 'broken'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ticket_ref_status")
