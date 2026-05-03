"""Truncate spec_documents.content_hash to 16 chars.

Earlier writers (legacy SearchIndex.upsert_spec) wrote full 64-char SHA-256
hashes; ContentSyncEngine.sync_spec wrote 16. The Phase 2b OpenSearch dual-
write standardised on 16, but pre-existing rows still carry 64-char values.
The reconcile cron compares Postgres against OpenSearch hashes for equality;
without this migration, every spec with a legacy 64-char row stays mismatched
forever and the cron re-embeds it on every hourly run.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from alembic import op

revision: str = "0013"
down_revision: str = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE spec_documents "
        "SET content_hash = LEFT(content_hash, 16) "
        "WHERE LENGTH(content_hash) > 16"
    )


def downgrade() -> None:
    # No-op: truncation is one-way. Rolling back would not restore the
    # original 64-char hashes because we don't store them.
    pass
