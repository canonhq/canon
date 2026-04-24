"""Add sync_runs and sync_events tables for sync history persistence.

Tracks every forward/reverse sync operation and its individual ticket
events (created, updated, closed, reopened, skipped, error) so the
web UI can display sync dashboards, run detail, and per-spec status.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from alembic import op

revision: str = "0011"
down_revision: str = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sync_runs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_login       VARCHAR(255) NOT NULL,
            repo            VARCHAR(512) NOT NULL,
            spec_path       VARCHAR(1024),
            system          VARCHAR(50) NOT NULL,
            direction       VARCHAR(20) NOT NULL,
            trigger         VARCHAR(50) NOT NULL DEFAULT 'manual',
            status          VARCHAR(20) NOT NULL DEFAULT 'running',
            created_count   INTEGER NOT NULL DEFAULT 0,
            updated_count   INTEGER NOT NULL DEFAULT 0,
            closed_count    INTEGER NOT NULL DEFAULT 0,
            reopened_count  INTEGER NOT NULL DEFAULT 0,
            skipped_count   INTEGER NOT NULL DEFAULT 0,
            error_count     INTEGER NOT NULL DEFAULT 0,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at        TIMESTAMPTZ,
            triggered_by    VARCHAR(255),
            metadata        JSONB DEFAULT '{}'::jsonb
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS sync_events (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id          UUID NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
            event_type      VARCHAR(30) NOT NULL,
            section_title   VARCHAR(500),
            section_number  VARCHAR(50),
            ticket_id       VARCHAR(255),
            ticket_url      VARCHAR(1024),
            detail          JSONB DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Indexes for sync_runs
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_runs_org_started "
        "ON sync_runs (org_login, started_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_runs_org_repo_started "
        "ON sync_runs (org_login, repo, started_at DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_sync_runs_status ON sync_runs (status)")

    # Indexes for sync_events
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_events_run_type ON sync_events (run_id, event_type)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_sync_events_ticket ON sync_events (ticket_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sync_events")
    op.execute("DROP TABLE IF EXISTS sync_runs")
