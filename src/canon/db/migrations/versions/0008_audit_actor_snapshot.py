"""Add actor_sub_snapshot to audit_events and relax actor_id FK.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-11

GDPR delete (admin-ui-user-org-management §2.5) needs to remove the user
row entirely while preserving the audit trail of what they did. Two
schema changes make that possible:

1. ``actor_sub_snapshot`` captures the deleted user's oidc_sub at the
   time of audit emission so the actor can be identified after the
   user row is gone.
2. The ``actor_id`` foreign key is relaxed from RESTRICT (the implicit
   default) to SET NULL so an admin can delete a user without first
   having to scrub every audit event they authored.

Existing audit rows are backfilled with the current users.oidc_sub
value via a one-shot UPDATE so the snapshot column matches reality
for everything emitted before this migration ran.
"""

from __future__ import annotations

from alembic import op

revision: str = "0008"
down_revision: str = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS actor_sub_snapshot TEXT")
    # Backfill the snapshot from the live users table for any audit row
    # whose actor_id still resolves. New rows fill this in at write time.
    op.execute("""
        UPDATE audit_events ae
        SET actor_sub_snapshot = u.oidc_sub
        FROM users u
        WHERE ae.actor_id = u.id AND ae.actor_sub_snapshot IS NULL
    """)

    # Relax the FK to SET NULL so user delete can proceed without scrubbing
    op.execute("ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_actor_id_fkey")
    op.execute("""
        ALTER TABLE audit_events
        ADD CONSTRAINT audit_events_actor_id_fkey
        FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_actor_id_fkey")
    op.execute("""
        ALTER TABLE audit_events
        ADD CONSTRAINT audit_events_actor_id_fkey
        FOREIGN KEY (actor_id) REFERENCES users(id)
    """)
    op.execute("ALTER TABLE audit_events DROP COLUMN IF EXISTS actor_sub_snapshot")
