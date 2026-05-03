"""Add ai_exposure and tags columns to spec_documents and backfill from raw_markdown.

Phase 2 introduces find_related_specs which must filter neighbour results
whose own frontmatter sets ``ai_exposure: none`` (otherwise their title
and path leak through the kNN result). The OpenSearch path stores these
on canon-specs, but the Postgres pgvector path — which is the default
backend when ``OPENSEARCH_ENABLED`` is unset — had no equivalent. Adding
the columns lets ``PostgresSearchBackend.get_related`` surface the same
metadata so the MCP layer can resolve per-spec exposure consistently.

The default empty values for `ai_exposure` and `tags` are ambiguous —
they could mean "frontmatter has no override" (correct) or "row predates
this migration" (the leak case). The reconcile cron uses `_NoopSearchIndex`
so won't re-write Postgres metadata even on hash mismatch, and inactive
specs may never see another push. Backfill here parses each spec's
``raw_markdown`` once and writes the extracted values, closing the
window.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import logging

import frontmatter
from alembic import op
from sqlalchemy import text

revision: str = "0014"
down_revision: str = "0013"
branch_labels: str | None = None
depends_on: str | None = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE spec_documents "
        "ADD COLUMN IF NOT EXISTS ai_exposure VARCHAR(16) NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE spec_documents ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}'"
    )

    # Backfill from raw_markdown. Parse each spec once and write the
    # extracted frontmatter values so existing rows don't sit at the
    # default '' / [] (which the find_related_specs filter would treat as
    # "no override" and let through).
    bind = op.get_bind()
    rows = bind.execute(
        text(
            "SELECT id, path, raw_markdown FROM spec_documents "
            "WHERE raw_markdown IS NOT NULL "
            "  AND (ai_exposure = '' AND tags = '{}')"
        )
    ).fetchall()

    backfilled = 0
    failed = 0
    for row in rows:
        try:
            post = frontmatter.loads(row.raw_markdown)
            ai_exposure = post.metadata.get("ai_exposure", "")
            tags_raw = post.metadata.get("tags", [])
            tags_list = tags_raw if isinstance(tags_raw, list) else []
            ai_exp = ai_exposure if isinstance(ai_exposure, str) else ""
            tags = tags_list
        except Exception:
            failed += 1
            logger.warning("0014 backfill: failed to parse row id=%s path=%s", row.id, row.path)
            continue
        bind.execute(
            text("UPDATE spec_documents SET ai_exposure = :ai, tags = :tags WHERE id = :id"),
            {"ai": ai_exp, "tags": tags, "id": row.id},
        )
        backfilled += 1

    if backfilled or failed:
        logger.info(
            "0014 backfill: ai_exposure/tags updated on %d rows (%d parse failures)",
            backfilled,
            failed,
        )


def downgrade() -> None:
    op.execute("ALTER TABLE spec_documents DROP COLUMN IF EXISTS tags")
    op.execute("ALTER TABLE spec_documents DROP COLUMN IF EXISTS ai_exposure")
