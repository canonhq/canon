"""Full re-index CLI — indexes all specs across all installed repos.

Run as: python -m canon.search.reindex

For K8s CronJob: set CMD override to ["python", "-m", "canon.search.reindex"]
"""

from __future__ import annotations

import asyncio
import logging
import sys

from ..db import close_pool, create_pool, ensure_schema
from ..github.client import GitHubClient
from ..github.spec_utils import load_repo_config, load_repo_specs
from ..search.embed import EmbeddingClient
from ..search.index import SearchIndex
from ..search.indexer import index_spec
from ..settings import Settings

logger = logging.getLogger(__name__)


async def run_reindex() -> list[dict]:
    """Re-index all specs across all installed repos.

    Returns a list of result dicts with repo, specs_indexed, errors.
    """
    settings = Settings()

    if not settings.gh_app_id or not settings.gh_private_key or not settings.gh_installation_id:
        logger.error(
            "Missing GitHub App credentials (GH_APP_ID, GH_PRIVATE_KEY, GH_INSTALLATION_ID)"
        )
        sys.exit(1)

    if not settings.database_url:
        logger.error("Missing DATABASE_URL — required for re-indexing")
        sys.exit(1)

    client = GitHubClient(
        app_id=settings.gh_app_id,
        private_key=settings.gh_private_key,
        installation_id=settings.gh_installation_id,
    )

    pool = await create_pool(settings.database_url)
    await ensure_schema(pool, settings.database_url)
    search_index = SearchIndex(pool)

    embed_client = EmbeddingClient(
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        service_account_key=settings.gcp_service_account_key,
    )
    if embed_client.is_available:
        logger.info("Embedding client initialised")
    else:
        logger.info("Embedding client unavailable — indexing without embeddings (BM25 only)")

    results: list[dict] = []

    try:
        # List repos via paginated client method (ETag-cached)
        repos = await client.list_installation_repos()

        for repo_idx, repo_data in enumerate(repos, 1):
            owner = repo_data["owner"]["login"]
            repo_name = repo_data["name"]
            full_repo = f"{owner}/{repo_name}"

            logger.info("Indexing repo %d/%d: %s", repo_idx, len(repos), full_repo)

            repo_config = await load_repo_config(client, owner, repo_name)
            specs = await load_repo_specs(
                client, owner, repo_name, patterns=repo_config.specs.doc_paths
            )
            if not specs:
                logger.info("  No specs found in %s", full_repo)
                continue

            indexed = 0
            errors = 0

            for spec_idx, spec_data in enumerate(specs, 1):
                file_path = spec_data["file_path"]
                doc = spec_data["document"]

                logger.info("  Spec %d/%d: %s", spec_idx, len(specs), file_path)

                try:
                    await index_spec(
                        doc=doc,
                        repo=full_repo,
                        search_index=search_index,
                        embed_client=embed_client,
                    )
                    indexed += 1
                except Exception:
                    logger.exception("  Error indexing %s in %s", file_path, full_repo)
                    errors += 1

            results.append(
                {
                    "repo": full_repo,
                    "specs_indexed": indexed,
                    "errors": errors,
                }
            )
    finally:
        await client.close()
        await close_pool(pool)

    return results


def main() -> None:
    """CLI entry point for the full re-index."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    results = asyncio.run(run_reindex())

    total_indexed = sum(r["specs_indexed"] for r in results)
    total_errors = sum(r["errors"] for r in results)

    logger.info(
        "Re-index complete: %d repos processed, %d specs indexed, %d errors",
        len(results),
        total_indexed,
        total_errors,
    )

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
