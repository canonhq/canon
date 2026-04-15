"""Add session_evidence table for the plugin → GitHub App evidence pipeline.

Stores dev-session evidence captured by the Canon plugin (Stop hook → MCP
record_session_evidence tool). The PR analyzer queries this table at
PR-open time as hint input for the LLM prompt.

See: docs/specs/plugin-evidence-pipeline.md §6.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from alembic import op

revision: str = "0009"
down_revision: str = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS session_evidence (
            id              BIGSERIAL PRIMARY KEY,
            repo            TEXT NOT NULL,
            branch          TEXT NOT NULL,
            session_id      TEXT NOT NULL,
            schema_version  INT  NOT NULL DEFAULT 1,
            payload         JSONB NOT NULL,
            recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (repo, session_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_evidence_branch ON session_evidence (repo, branch)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_evidence_recorded_at "
        "ON session_evidence (recorded_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_session_evidence_recorded_at")
    op.execute("DROP INDEX IF EXISTS idx_session_evidence_branch")
    op.execute("DROP TABLE IF EXISTS session_evidence")
