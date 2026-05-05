"""OpenSearch reconciliation cron job.

Diffs ``content_hash`` between Postgres ``spec_documents`` and the OpenSearch
``canon-specs`` index. Re-indexes specs whose hashes mismatch and removes
specs that exist in OpenSearch but no longer in Postgres.

Run as: python -m canon.cron.opensearch_reconcile

Skipped at runtime when ``OPENSEARCH_ENABLED`` is false.
"""

from __future__ import annotations

import asyncio
import logging

from ..alerts.cron_utils import tracked_cron
from ..db import close_pool, create_pool
from ..db.content_cache_store import ContentCacheStore
from ..db.schema import ensure_schema
from ..parser.models import ParseOptions
from ..parser.parse import parse_spec
from ..search.embed import EmbeddingClient
from ..search.indexer import index_spec
from ..search.opensearch_client import build_client_from_settings
from ..settings import Settings

logger = logging.getLogger(__name__)


@tracked_cron("opensearch_reconcile")
async def run_opensearch_reconciliation() -> dict:
    """Reconcile the OpenSearch index against Postgres.

    Returns a summary dict with counts of reindexed/deleted/errors.
    """
    settings = Settings()

    if not settings.opensearch_enabled:
        logger.info("OPENSEARCH_ENABLED=false — skipping reconciliation")
        return {"skipped": True}

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for OpenSearch reconciliation")

    pool = await create_pool(settings.database_url)
    await ensure_schema(pool, settings.database_url)

    opensearch = build_client_from_settings(settings)
    if not opensearch.is_enabled:
        logger.warning("OpenSearch client not enabled at runtime — skipping")
        await close_pool(pool)
        return {"skipped": True}

    embed_client = EmbeddingClient(
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        service_account_key=settings.gcp_service_account_key,
    )

    try:
        store = ContentCacheStore(pool)
        result = await _reconcile(store, opensearch, embed_client)
        logger.info("OpenSearch reconciliation complete: %s", result)
        return result
    finally:
        await opensearch.close()
        await close_pool(pool)


async def _reconcile(
    store: ContentCacheStore,
    opensearch,
    embed_client,
) -> dict:
    """Compute the diff and apply reindex/delete operations."""
    pg_specs = await store.list_all_spec_hashes()
    pg_by_id = {f"{s['repo']}:{s['path']}": s for s in pg_specs}

    os_hashes = await opensearch.list_spec_hashes()

    to_reindex: list[dict] = []
    for spec_id, pg_spec in pg_by_id.items():
        os_hash = os_hashes.get(spec_id)
        if os_hash != pg_spec["content_hash"]:
            to_reindex.append(pg_spec)

    to_delete = [spec_id for spec_id in os_hashes if spec_id not in pg_by_id]

    reindexed = 0
    errors = 0
    for spec in to_reindex:
        try:
            did_reindex = await _reindex_spec(store, opensearch, embed_client, spec)
        except Exception:
            errors += 1
            logger.warning(
                "Reconcile reindex failed for %s:%s",
                spec["repo"],
                spec["path"],
                exc_info=True,
            )
            continue
        if did_reindex:
            reindexed += 1
        else:
            # list_all_spec_hashes already filters raw_markdown IS NOT NULL,
            # so a None from get_spec_raw here means the row was deleted
            # between the two queries (benign race) or its raw was nulled
            # out (data inconsistency). Either way, the next run hits the
            # same hash mismatch — count as an error so existing alerts on
            # `errors > 0` surface persistent occurrences instead of letting
            # the cron loop forever on a phantom mismatch.
            errors += 1
            logger.warning(
                "Reconcile skipped %s:%s: raw_markdown unexpectedly empty",
                spec["repo"],
                spec["path"],
            )

    deleted = 0
    for spec_id in to_delete:
        try:
            await opensearch.delete_spec(spec_id)
            deleted += 1
        except Exception:
            errors += 1
            logger.warning("Reconcile delete failed for %s", spec_id, exc_info=True)

    return {
        "pg_specs": len(pg_by_id),
        "os_specs": len(os_hashes),
        "reindexed": reindexed,
        "deleted": deleted,
        "errors": errors,
    }


async def _reindex_spec(
    store: ContentCacheStore,
    opensearch,
    embed_client,
    pg_spec: dict,
) -> bool:
    """Pull a spec's raw markdown from Postgres and push to OpenSearch.

    OpenSearch is the only target — Postgres state is untouched. Returns
    True when an actual reindex happened, False when raw was missing.
    The caller distinguishes the two so the cron summary doesn't claim
    successful reindexing of specs that were never touched.
    """
    raw = await store.get_spec_raw(pg_spec["repo"], pg_spec["path"])
    if not raw:
        return False

    parsed = parse_spec(raw, ParseOptions(file_path=pg_spec["path"]))

    await index_spec(
        doc=parsed.document,
        repo=pg_spec["repo"],
        search_index=_NoopSearchIndex(),
        embed_client=embed_client,
        opensearch_client=opensearch,
    )
    return True


class _NoopSearchIndex:
    """Stand-in SearchIndex used during OpenSearch-only reconciliation.

    ``index_spec`` always upserts to a Postgres SearchIndex first; during
    reconciliation we only want to refresh OpenSearch, so we satisfy that
    contract with a no-op stub that returns a synthetic doc id.
    """

    async def upsert_spec(self, **_kwargs) -> int:
        return 0


def main() -> None:
    from .. import otel_logging

    settings = Settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if settings.posthog_logs_enabled:
        otel_logging.init(
            settings.posthog_key,
            min_level=settings.posthog_logs_min_level,
            posthog_host=settings.posthog_host,
        )

    try:
        asyncio.run(run_opensearch_reconciliation())
    finally:
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
