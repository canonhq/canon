"""Add user_preferences table for per-(user, org) notification and appearance prefs.

Stores notification settings (Slack DM toggles, email-digest cadence) and
appearance settings (theme, timezone, relative-time formatting) for each
user inside each org they belong to. Per-(user, org) scoping lets a user
mute one org without muting another. See docs/specs/profile-account-management.md.

Revision ID: 0019
Revises: 0018

Originally authored as 0018; renumbered to 0019 when PR #783 was
rebased onto main after PR #782's 0018_subscriptions_free_internal_plans
landed first. Re-parented onto 0018 to keep the migration chain linear.
"""

from __future__ import annotations

from alembic import op

revision: str = "0019"
down_revision: str = "0018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id              BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            org_login            TEXT   NOT NULL,
            slack_dm_enabled     BOOLEAN NOT NULL DEFAULT TRUE,
            slack_dm_pr_comments BOOLEAN NOT NULL DEFAULT TRUE,
            slack_dm_spec_drift  BOOLEAN NOT NULL DEFAULT TRUE,
            email_digest_cadence TEXT    NOT NULL DEFAULT 'weekly',
            email_pr_comments    BOOLEAN NOT NULL DEFAULT FALSE,
            theme                TEXT    NOT NULL DEFAULT 'system',
            timezone             TEXT    NOT NULL DEFAULT '',
            relative_time        BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, org_login),
            CONSTRAINT user_preferences_email_digest_cadence_chk
                CHECK (email_digest_cadence IN ('off', 'daily', 'weekly')),
            CONSTRAINT user_preferences_theme_chk
                CHECK (theme IN ('system', 'light', 'dark'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_user_preferences_user_id")
    op.execute("DROP TABLE IF EXISTS user_preferences")
