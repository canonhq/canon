"""Add pr_reviews table for persisting full PR analysis results.

Stores the complete PRAnalysisResult for every review so analysis data
is durable, queryable, and independent of the GitHub PR comment. Each
row captures one analysis per commit SHA, enabling review history and
the smart re-analysis skip logic.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

from alembic import op

revision: str = "0017"
down_revision: str = "0016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS pr_reviews (
            id              SERIAL PRIMARY KEY,
            org             TEXT NOT NULL,
            repo            TEXT NOT NULL,
            pr_number       INTEGER NOT NULL,
            pr_url          TEXT NOT NULL,
            pr_title        TEXT NOT NULL,
            pr_author       TEXT NOT NULL,
            head_sha        TEXT NOT NULL,
            base_ref        TEXT NOT NULL,
            analysis        JSONB NOT NULL DEFAULT '{}'::jsonb,
            model           TEXT NOT NULL DEFAULT '',
            tokens_in       INTEGER NOT NULL DEFAULT 0,
            tokens_out      INTEGER NOT NULL DEFAULT 0,
            cost_estimate   NUMERIC(10,6) DEFAULT 0,
            review_kind     TEXT NOT NULL DEFAULT 'full',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (repo, pr_number, head_sha)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pr_reviews_repo_pr_date "
        "ON pr_reviews (repo, pr_number, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pr_reviews_org_date ON pr_reviews (org, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pr_reviews")
