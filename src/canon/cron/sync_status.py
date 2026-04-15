"""Reverse sync cron job — polls ticket statuses and updates spec status comments.

Run as: python -m canon.cron.sync_status

For K8s CronJob: set CMD override to ["python", "-m", "canon.cron.sync_status"]
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .. import analytics, otel_logging
from ..alerts.cron_utils import tracked_cron
from ..github.client import GitHubClient
from ..parser.models import ParseOptions
from ..parser.parse import parse_spec
from ..settings import Settings
from ..sync.adapters.factory import create_adapter, from_config, from_org
from ..sync.engine import reverse_sync
from ..sync.mapping import deep_merge_configs, synthesize_mapping_config
from ..sync.org_config import load_org_mapping_config
from ..sync.router import resolve_target

logger = logging.getLogger(__name__)


@tracked_cron("reverse_sync_status")
async def run_reverse_sync() -> list[dict]:
    """Run reverse sync across all installed repos.

    Returns a list of result dicts with repo, file, changed, errors.
    """
    settings = Settings()

    if not settings.gh_app_id or not settings.gh_private_key or not settings.gh_installation_id:
        logger.error(
            "Missing GitHub App credentials (GH_APP_ID, GH_PRIVATE_KEY, GH_INSTALLATION_ID)"
        )
        sys.exit(1)

    client = GitHubClient(
        app_id=settings.gh_app_id,
        private_key=settings.gh_private_key,
        installation_id=settings.gh_installation_id,
    )

    results: list[dict] = []

    # Best-effort: create IntegrationStore for DB-stored OAuth credentials
    integration_store = None
    pool = None
    if settings.database_url and settings.byok_encryption_key:
        try:
            import asyncpg

            from ..db.integration_store import IntegrationStore

            pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
            integration_store = IntegrationStore(pool, settings.byok_encryption_key)
        except ImportError:
            logger.info("asyncpg not installed — skipping DB credential resolution for cron")
        except Exception:
            logger.warning(
                "Failed to initialize IntegrationStore for cron job — "
                "DB-stored OAuth credentials will not be used this run",
                exc_info=True,
            )

    try:
        # Get installation token for GitHub adapter reuse and list repos
        github_token = await client.get_installation_token()
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
            default_branch = repo_data.get("default_branch", "main")

            # Load repo config for ticket mapping and doc_paths
            from ..github.spec_utils import (
                extract_directories,
                load_repo_config,
                matches_doc_patterns,
            )

            repo_config = await load_repo_config(client, owner, repo_name)
            doc_paths = repo_config.specs.doc_paths

            # List spec files using configurable patterns
            directories = extract_directories(doc_paths)
            entries: list[dict] = []
            for directory, _is_recursive in directories:
                entries.extend(await client.list_directory(owner, repo_name, directory))
            if not entries:
                continue

            spec_files = [
                e.get("path", f"{e.get('name', '')}")
                for e in entries
                if e.get("type") == "file"
                and e.get("name", "").endswith(".md")
                and not e.get("name", "").startswith("_")
                and matches_doc_patterns(e.get("path", e.get("name", "")), doc_paths)
            ]
            mapping, _deprecated = synthesize_mapping_config(
                ticket_system=repo_config.ticket_system,
                project_key=repo_config.project_key,
                ticket_mapping=repo_config.ticket_mapping,
            )

            # Merge org-level defaults if available
            org_mapping = await load_org_mapping_config(client, owner)
            if org_mapping:
                mapping = deep_merge_configs(org_mapping, mapping)

            for file_path in spec_files:
                try:
                    content, file_sha = await client.get_file_content(owner, repo_name, file_path)
                    result = parse_spec(content, ParseOptions(file_path=file_path))
                    project_key = result.document.frontmatter.ticket_project

                    # Resolve adapter via routing or single-system fallback.
                    # Credential resolution order:
                    # 1. CANON.yaml auth_profiles / env vars (from_config)
                    # 2. GitHub App installation token (github_token)
                    # 3. DB org_integrations (from_org, for OAuth-connected orgs)
                    adapter = None
                    resolved_sys_config = None
                    if not mapping.is_empty():
                        target_name = resolve_target(
                            None, result.document, mapping.routing, mapping.ticket_systems
                        )
                        if target_name:
                            resolved_sys_config = mapping.ticket_systems[target_name]
                            adapter = from_config(
                                target_name,
                                resolved_sys_config,
                                mapping.auth_profiles or None,
                                github_token=github_token,
                            )
                            if not adapter and integration_store and resolved_sys_config.system:
                                try:
                                    adapter = await from_org(
                                        owner, resolved_sys_config.system, integration_store
                                    )
                                except Exception:
                                    logger.warning(
                                        "DB credential lookup failed for %s/%s system=%s",
                                        owner,
                                        repo_name,
                                        resolved_sys_config.system,
                                        exc_info=True,
                                    )
                            project_key = project_key or resolved_sys_config.project or ""
                        else:
                            single = mapping.single_system()
                            if single:
                                resolved_sys_config = single
                                sys_name = next(iter(mapping.ticket_systems.keys()))
                                adapter = from_config(
                                    sys_name,
                                    single,
                                    mapping.auth_profiles or None,
                                    github_token=github_token,
                                )
                                if not adapter and integration_store and single.system:
                                    try:
                                        adapter = await from_org(
                                            owner, single.system, integration_store
                                        )
                                    except Exception:
                                        logger.warning(
                                            "DB credential lookup failed for %s/%s system=%s",
                                            owner,
                                            repo_name,
                                            single.system,
                                            exc_info=True,
                                        )
                                project_key = project_key or single.project or ""

                    if not adapter:
                        if not project_key:
                            continue
                        adapter = create_adapter(
                            ticket_project=project_key, github_token=github_token
                        )

                    if not adapter:
                        logger.warning(
                            "No ticket adapter resolved for %s/%s/%s (project_key=%r) "
                            "— skipping reverse sync",
                            owner,
                            repo_name,
                            file_path,
                            project_key,
                        )
                        analytics.track(
                            "sync_adapter_resolution_failed",
                            properties={
                                "repo": f"{owner}/{repo_name}",
                                "file_path": file_path,
                                "project_key": project_key,
                                "context": "reverse_sync",
                            },
                            groups={"organization": owner},
                        )
                        continue

                    updated_md, sync_result = await reverse_sync(
                        result.document, adapter, system_config=resolved_sys_config
                    )

                    if sync_result.status_changed and updated_md != content:
                        await client.create_or_update_file(
                            owner,
                            repo_name,
                            file_path,
                            updated_md,
                            f"chore(canon): sync ticket statuses in {file_path}",
                            file_sha,
                            branch=default_branch,
                        )

                    results.append(
                        {
                            "repo": f"{owner}/{repo_name}",
                            "file": file_path,
                            "changed": len(sync_result.status_changed),
                            "errors": len(sync_result.errors),
                        }
                    )

                    # Per-file reverse sync event — matches the shape of
                    # ``spec_sync_completed`` (per-file, with adapter tag) so
                    # Canon · Ticket Sync can correlate forward and reverse
                    # health per repo/file/adapter. The existing
                    # ``reverse_sync_cron_summary`` event (emitted once per
                    # cron run at the bottom of main()) stays in place for
                    # run-level monitoring.
                    analytics.track(
                        "reverse_sync_completed",
                        properties={
                            "repo": f"{owner}/{repo_name}",
                            "file_path": file_path,
                            "adapter": getattr(adapter, "system_name", "unknown"),
                            "status_changed_count": len(sync_result.status_changed),
                            "error_count": len(sync_result.errors),
                            "success": not sync_result.errors,
                        },
                        groups={"organization": owner},
                    )
                except Exception:
                    logger.exception("Error syncing %s/%s/%s", owner, repo_name, file_path)
    finally:
        await client.close()
        if pool is not None:
            await pool.close()

    return results


def main() -> None:
    """CLI entry point for the reverse sync cron job."""
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

    total_errors = 0
    try:
        results = asyncio.run(run_reverse_sync())

        total_changed = sum(r["changed"] for r in results)
        total_errors = sum(r["errors"] for r in results)

        from canon import analytics

        analytics.track(
            "reverse_sync_cron_summary",
            properties={
                "files_processed": len(results),
                "total_changed": total_changed,
                "total_errors": total_errors,
            },
        )

        logger.info(
            "Reverse sync complete: %d files processed, %d statuses changed, %d errors",
            len(results),
            total_changed,
            total_errors,
        )
    finally:
        otel_logging.shutdown()

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
