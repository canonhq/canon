"""Add status column to users table.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_status")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS status")
