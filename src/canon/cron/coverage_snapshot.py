"""Coverage snapshot cron job — captures daily per-spec coverage metrics.

Run as: python -m canon.cron.coverage_snapshot

For K8s CronJob: set CMD override to ["python", "-m", "canon.cron.coverage_snapshot"]
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date

from .. import otel_logging
from ..alerts.cron_utils import tracked_cron
from ..db import create_pool
from ..db.agent_store import AgentStore
from ..db.schema import ensure_schema
from ..github.client import GitHubClient
from ..github.spec_utils import load_repo_config, load_repo_specs
from ..settings import Settings
from ..web.services import _summarize_spec

logger = logging.getLogger(__name__)


@tracked_cron("coverage_snapshot")
async def run_coverage_snapshot() -> list[dict]:
    """Capture coverage snapshots for all specs across installed repos.

    Returns a list of result dicts with repo, spec_count, total_ac.
    """
    settings = Settings()

    if not settings.gh_app_id or not settings.gh_private_key or not settings.gh_installation_id:
        logger.error("Missing GitHub App credentials")
        sys.exit(1)

    if not settings.database_url:
        logger.error("DATABASE_URL is required for coverage snapshots")
        sys.exit(1)

    pool = await create_pool(settings.database_url)
    await ensure_schema(pool, settings.database_url)
    agent_store = AgentStore(pool)

    client = GitHubClient(
        app_id=settings.gh_app_id,
        private_key=settings.gh_private_key,
        installation_id=settings.gh_installation_id,
    )

    results: list[dict] = []
    today = date.today()

    try:
        # List repos via paginated client method (ETag-cached)
        repos = await client.list_installation_repos()

        for repo_data in repos:
            owner = repo_data["owner"]["login"]
            repo_name = repo_data["name"]
            full_repo = f"{owner}/{repo_name}"

            try:
                repo_config = await load_repo_config(client, owner, repo_name)
                specs = await load_repo_specs(
                    client, owner, repo_name, patterns=repo_config.specs.doc_paths
                )

                for spec_data in specs:
                    doc = spec_data["document"]
                    summary = _summarize_spec(doc)

                    # Get realization count from DB
                    realized_ac = 0
                    try:
                        realization = await agent_store.get_realization_summary(
                            full_repo, doc.file_path
                        )
                        realized_ac = realization.get("realized", 0)
                    except Exception:
                        logger.debug("No realization data for %s/%s", full_repo, doc.file_path)

                    await agent_store.upsert_coverage_snapshot(
                        today,
                        owner,
                        full_repo,
                        doc.file_path,
                        team=summary.team,
                        total_sections=summary.total_sections,
                        done_sections=summary.done_sections,
                        total_ac=summary.total_ac,
                        done_ac=summary.done_ac,
                        realized_ac=realized_ac,
                    )

                results.append(
                    {
                        "repo": full_repo,
                        "spec_count": len(specs),
                        "total_ac": sum(_summarize_spec(s["document"]).total_ac for s in specs),
                    }
                )

                logger.info(
                    "Coverage snapshot for %s: %d spec(s)",
                    full_repo,
                    len(specs),
                )
            except Exception:
                logger.exception("Error snapshotting coverage for %s", full_repo)
    finally:
        await client.close()
        from ..db import close_pool

        await close_pool(pool)

    return results


def main() -> None:
    """CLI entry point for the coverage snapshot cron job."""
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
        results = asyncio.run(run_coverage_snapshot())

        total_specs = sum(r["spec_count"] for r in results)
        logger.info(
            "Coverage snapshot complete: %d repos processed, %d spec(s) total",
            len(results),
            total_specs,
        )
    finally:
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
