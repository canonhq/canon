"""Add slack_dm_prompts table for one-time-prompt tracking.

Tracks whether the bot has already nudged a Slack user to link their GitHub
identity (via /canon link). Without this, every unlinked DM would re-prompt
the user, which becomes spammy. One row per (workspace_id, user_id, prompt_type).

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_dm_prompts",
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("prompt_type", sa.String(length=64), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("workspace_id", "user_id", "prompt_type"),
    )


def downgrade() -> None:
    op.drop_table("slack_dm_prompts")
