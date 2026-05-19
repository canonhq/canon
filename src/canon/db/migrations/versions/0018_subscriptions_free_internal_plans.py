"""Allow 'free' and 'internal' values in subscriptions.plan.

The baseline migration restricted plan to ('starter', 'pro', 'enterprise').
After the Free-tier refactor every managed-cloud org has a real plan,
auto-enrolled to 'free' on first billing access, and Canon's own
dev/test orgs use the 'internal' tier (Pro Stripe sub + comp coupon,
DB plan flagged as 'internal' for uncapped feature gates).

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from alembic import op

revision: str = "0018"
down_revision: str = "0017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.constraint_column_usage
                WHERE table_name = 'subscriptions'
                  AND constraint_name = 'subscriptions_plan_check'
            ) THEN
                ALTER TABLE subscriptions DROP CONSTRAINT subscriptions_plan_check;
            END IF;
        END
        $$;
    """)
    op.execute("""
        ALTER TABLE subscriptions
        ADD CONSTRAINT subscriptions_plan_check
        CHECK (plan IN ('free', 'starter', 'pro', 'enterprise', 'internal'))
    """)


def downgrade() -> None:
    # Revert to baseline constraint. Any 'free' or 'internal' rows must
    # be migrated to a baseline plan first, otherwise this raises.
    op.execute("""
        ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS subscriptions_plan_check
    """)
    op.execute("""
        ALTER TABLE subscriptions
        ADD CONSTRAINT subscriptions_plan_check
        CHECK (plan IN ('starter', 'pro', 'enterprise'))
    """)
