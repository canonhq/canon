"""Align subscriptions table with baseline schema.

Production databases created before the seat-based pricing refactor have
``repo_count`` and ``free_repos`` columns instead of ``seat_count``, and
are missing ``trial_start`` and ``trial_end``.  The baseline migration
(0001) was updated but production never received an ALTER TABLE.

This migration:
1. Adds ``seat_count`` (with CHECK constraint) if missing.
2. Adds ``trial_start`` and ``trial_end`` if missing.
3. Drops legacy ``repo_count`` and ``free_repos`` columns (only if the
   table is empty — fails loudly otherwise).

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from alembic import op

revision: str = "0010"
down_revision: str = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Add seat_count if missing (scoped to current schema to avoid
    # false matches from other schemas visible to the DB user).
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'subscriptions'
                  AND column_name = 'seat_count'
            ) THEN
                ALTER TABLE subscriptions
                    ADD COLUMN seat_count INTEGER NOT NULL DEFAULT 3;
                ALTER TABLE subscriptions
                    ADD CONSTRAINT chk_seat_count_min CHECK (seat_count >= 3);
            END IF;
        END
        $$;
    """)

    # Add trial columns if missing
    op.execute("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS trial_start TIMESTAMPTZ")
    op.execute("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS trial_end TIMESTAMPTZ")

    # Guard: refuse to drop legacy columns if the table has data, since
    # the values would be permanently lost.
    op.execute("""
        DO $$
        BEGIN
            IF (SELECT count(*) FROM subscriptions) > 0 THEN
                RAISE EXCEPTION
                    'subscriptions table is not empty — manual migration required (% rows)',
                    (SELECT count(*) FROM subscriptions);
            END IF;
        END
        $$;
    """)

    # Drop legacy columns from repo-based pricing
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS repo_count")
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS free_repos")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS repo_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS free_repos INTEGER NOT NULL DEFAULT 3"
    )
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS trial_start")
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS trial_end")
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS chk_seat_count_min;
            ALTER TABLE subscriptions DROP COLUMN IF EXISTS seat_count;
        END
        $$;
    """)
