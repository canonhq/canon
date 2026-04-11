"""Stale documentation check cron job — detects and reports stale docs.

Run as: python -m canon.cron.stale_check

For K8s CronJob: set CMD override to ["python", "-m", "canon.cron.stale_check"]
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from .. import analytics, otel_logging
from ..alerts.cron_utils import tracked_cron
from ..db import create_pool
from ..db.schema import ensure_schema
from ..github.client import GitHubClient
from ..search.index import SearchIndex
from ..settings import Settings
from ..stale.detector import detect_stale_docs
from ..stale.issue_reporter import upsert_stale_issue

logger = logging.getLogger(__name__)


@tracked_cron("stale_doc_check")
async def run_stale_check() -> list[dict]:
    """Run stale check across all installed repos.

    Returns a list of result dicts with repo, stale_count, issue_number.
    """
    settings = Settings()

    if not settings.gh_app_id or not settings.gh_private_key or not settings.gh_installation_id:
        logger.error("Missing GitHub App credentials")
        sys.exit(1)

    if not settings.database_url:
        logger.error("DATABASE_URL is required for stale detection")
        sys.exit(1)

    pool = await create_pool(settings.database_url)
    await ensure_schema(pool, settings.database_url)
    search_index = SearchIndex(pool)

    client = GitHubClient(
        app_id=settings.gh_app_id,
        private_key=settings.gh_private_key,
        installation_id=settings.gh_installation_id,
    )

    results: list[dict] = []

    try:
        # Get installation token and list repos
        headers = await client._auth_headers()
        resp = await client._http.get(
            "/installation/repositories",
            headers=headers,
            params={"per_page": "100"},
        )
        resp.raise_for_status()
        repos = resp.json().get("repositories", [])

        for repo_data in repos:
            owner = repo_data["owner"]["login"]
            repo_name = repo_data["name"]
            full_repo = f"{owner}/{repo_name}"

            try:
                # Check repo config for stale_detection setting
                from ..config.parse import DEFAULT_CONFIG, parse_canon_yaml

                config = DEFAULT_CONFIG
                try:
                    try:
                        content, _sha = await client.get_file_content(
                            owner,
                            repo_name,
                            "CANON.yaml",
                        )
                    except Exception:
                        content, _sha = await client.get_file_content(
                            owner,
                            repo_name,
                            "SPECWRIGHT.yaml",
                        )
                    result = parse_canon_yaml(content)
                    if result.config:
                        config = result.config
                except Exception:
                    pass

                if config.agents.stale_detection is False:
                    logger.info("Stale detection disabled for %s", full_repo)
                    continue

                # Parse threshold from config (e.g. "30d" -> 30)
                threshold_days = 30
                if isinstance(config.agents.stale_detection, str):
                    with contextlib.suppress(ValueError):
                        threshold_days = int(config.agents.stale_detection.rstrip("d"))

                stale_docs = await detect_stale_docs(
                    search_index,
                    full_repo,
                    threshold_days=threshold_days,
                )

                for stale_doc in stale_docs:
                    days_since_update = None
                    if stale_doc.stale_since:
                        import datetime

                        days_since_update = (
                            datetime.datetime.now(tz=datetime.UTC) - stale_doc.stale_since
                        ).days
                    stale_org = stale_doc.repo.split("/")[0] if "/" in stale_doc.repo else ""
                    analytics.track(
                        "stale_spec_detected",
                        properties={
                            "repo": stale_doc.repo,
                            "spec_path": stale_doc.path,
                            "days_since_update": days_since_update,
                        },
                        groups={"organization": stale_org} if stale_org else None,
                    )

                issue_number = await upsert_stale_issue(
                    client,
                    owner,
                    repo_name,
                    stale_docs,
                )

                results.append(
                    {
                        "repo": full_repo,
                        "stale_count": len(stale_docs),
                        "issue_number": issue_number,
                    }
                )

                logger.info(
                    "Stale check for %s: %d stale doc(s), issue=#%s",
                    full_repo,
                    len(stale_docs),
                    issue_number,
                )
            except Exception:
                logger.exception("Error checking staleness for %s", full_repo)
    finally:
        await client.close()
        from ..db import close_pool

        await close_pool(pool)

    return results


def main() -> None:
    """CLI entry point for the stale check cron job."""
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
        results = asyncio.run(run_stale_check())

        total_stale = sum(r["stale_count"] for r in results)
        logger.info(
            "Stale check complete: %d repos processed, %d stale doc(s) total",
            len(results),
            total_stale,
        )
    finally:
        otel_logging.shutdown()


if __name__ == "__main__":
    main()
