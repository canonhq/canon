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


async def _get_installations(settings: Settings) -> list[tuple[str, str]]:
    """Return (installation_id, org_login) pairs from the DB, falling back to env var.

    When the database has active installations, iterate all of them so the
    sync cron covers every org. When the DB is unavailable or has no rows,
    fall back to the single GH_INSTALLATION_ID env var for backwards
    compatibility.
    """
    if settings.database_url:
        try:
            import asyncpg

            from ..db.registry import InstallationRegistry

            pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=1)
            try:
                registry = InstallationRegistry(pool)
                installations = await registry.get_active_installations()
                if installations:
                    return [(str(inst.installation_id), inst.org_login) for inst in installations]
                logger.warning(
                    "DB has no active installations — falling back to GH_INSTALLATION_ID"
                )
            finally:
                await pool.close()
        except Exception:
            logger.warning(
                "Failed to load installations from DB — falling back to GH_INSTALLATION_ID",
                exc_info=True,
            )

    # Fallback: single installation from env var
    if settings.gh_installation_id:
        return [(settings.gh_installation_id, "unknown")]

    return []


@tracked_cron("reverse_sync_status")
async def run_reverse_sync() -> list[dict]:
    """Run reverse sync across all installed repos.

    Returns a list of result dicts with repo, file, changed, errors.
    """
    settings = Settings()

    if not settings.gh_app_id or not settings.gh_private_key:
        logger.error("Missing GitHub App credentials (GH_APP_ID, GH_PRIVATE_KEY)")
        sys.exit(1)

    installations = await _get_installations(settings)
    if not installations:
        logger.error(
            "No installations found — set GH_INSTALLATION_ID or ensure "
            "gh_installations table has active rows"
        )
        sys.exit(1)

    results: list[dict] = []

    # Best-effort: pool used by both IntegrationStore (OAuth creds) and
    # ContentCacheStore (read spec markdown from Postgres instead of GitHub).
    integration_store = None
    content_cache_store = None
    ref_store = None
    pool = None
    if settings.database_url:
        try:
            import asyncpg

            from ..db.content_cache_store import ContentCacheStore
            from ..db.integration_store import IntegrationStore
            from ..db.ticket_ref_status_store import TicketRefStatusStore

            pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
            content_cache_store = ContentCacheStore(pool)
            ref_store = TicketRefStatusStore(pool)
            if settings.byok_encryption_key:
                integration_store = IntegrationStore(pool, settings.byok_encryption_key)
        except ImportError:
            logger.info("asyncpg not installed — skipping DB-backed stores for cron")
        except Exception:
            # Pool failure means the content-cache optimization silently
            # disengages and we fan out to GitHub for every spec. That is
            # exactly the rate-limit burnout this cron is supposed to avoid,
            # so surface it as an error + analytics event for alerting.
            logger.error(
                "Failed to initialize DB-backed stores for cron job — "
                "spec content will be fetched from GitHub and DB OAuth creds skipped",
                exc_info=True,
            )
            analytics.track(
                "reverse_sync_db_pool_failed",
                properties={"installations": len(installations)},
            )

    auth_failures = 0
    try:
        for install_id, org_login in installations:
            client = GitHubClient(
                app_id=settings.gh_app_id,
                private_key=settings.gh_private_key,
                installation_id=install_id,
            )
            try:
                try:
                    github_token = await client.get_installation_token()
                    repos = await client.list_installation_repos()
                except Exception:
                    auth_failures += 1
                    logger.exception(
                        "Failed to authenticate or list repos for installation %s (%s) — skipping",
                        install_id,
                        org_login,
                    )
                    analytics.track(
                        "reverse_sync_repo_list_failed",
                        properties={
                            "installation_id": install_id,
                            "org_login": org_login,
                        },
                    )
                    continue

                if not repos:
                    logger.info(
                        "No repos for installation %s (%s) — skipping",
                        install_id,
                        org_login,
                    )
                    continue

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

                    try:
                        repo_config = await load_repo_config(client, owner, repo_name)
                    except Exception:
                        logger.warning(
                            "Failed to load config for %s/%s — skipping repo",
                            owner,
                            repo_name,
                            exc_info=True,
                        )
                        continue
                    doc_paths = repo_config.specs.doc_paths

                    # List spec files using Git Trees API (1 call per repo)
                    # instead of per-directory Contents API calls
                    try:
                        tree_data = await client._get(
                            f"/repos/{owner}/{repo_name}/git/trees/{default_branch}",
                            recursive="true",
                        )
                        if tree_data.get("truncated"):
                            logger.warning(
                                "Git Trees API truncated for %s/%s — falling back to Contents API",
                                owner,
                                repo_name,
                            )
                            raise ValueError("truncated tree")
                        tree_entries = tree_data.get("tree", [])
                        spec_files = [
                            (item["path"], item.get("sha", ""))
                            for item in tree_entries
                            if item["type"] == "blob"
                            and item["path"].endswith(".md")
                            and not item["path"].rsplit("/", 1)[-1].startswith("_")
                            and matches_doc_patterns(item["path"], doc_paths)
                        ]
                    except Exception:
                        # Fallback to per-directory listing if Trees API fails
                        logger.debug(
                            "Git Trees API failed for %s/%s — falling back to Contents API",
                            owner,
                            repo_name,
                            exc_info=True,
                        )
                        directories = extract_directories(doc_paths)
                        entries: list[dict] = []
                        for directory, _is_recursive in directories:
                            try:
                                entries.extend(
                                    await client.list_directory(owner, repo_name, directory)
                                )
                            except Exception:
                                logger.warning(
                                    "Failed to list directory %s in %s/%s — skipping",
                                    directory,
                                    owner,
                                    repo_name,
                                    exc_info=True,
                                )
                        spec_files = [
                            (e.get("path", f"{e.get('name', '')}"), e.get("sha", ""))
                            for e in entries
                            if e.get("type") == "file"
                            and e.get("name", "").endswith(".md")
                            and not e.get("name", "").startswith("_")
                            and matches_doc_patterns(e.get("path", e.get("name", "")), doc_paths)
                        ]
                    if not spec_files:
                        continue
                    mapping, _deprecated = synthesize_mapping_config(
                        ticket_system=repo_config.ticket_system,
                        project_key=repo_config.project_key,
                        ticket_mapping=repo_config.ticket_mapping,
                    )

                    # Merge org-level defaults if available
                    org_mapping = await load_org_mapping_config(client, owner)
                    if org_mapping:
                        mapping = deep_merge_configs(org_mapping, mapping)

                    full_repo = f"{owner}/{repo_name}"
                    for file_path, tree_sha in spec_files:
                        try:
                            content: str | None = None
                            file_sha = tree_sha
                            if content_cache_store is not None and tree_sha:
                                try:
                                    cached = await content_cache_store.get_spec(
                                        full_repo, file_path
                                    )
                                except Exception:
                                    logger.warning(
                                        "Content cache read failed for %s/%s — falling back to GitHub",
                                        full_repo,
                                        file_path,
                                        exc_info=True,
                                    )
                                    cached = None
                                if (
                                    cached
                                    and cached.get("github_sha") == tree_sha
                                    and cached.get("raw_markdown")
                                ):
                                    content = cached["raw_markdown"]
                            if content is None:
                                content, file_sha = await client.get_file_content(
                                    owner, repo_name, file_path
                                )
                            result = parse_spec(content, ParseOptions(file_path=file_path))
                            project_key = result.document.frontmatter.ticket_project

                            adapter = None
                            resolved_sys_config = None
                            reason = "no_explicit_mapping"
                            if not mapping.is_empty():
                                target_name = resolve_target(
                                    None,
                                    result.document,
                                    mapping.routing,
                                    mapping.ticket_systems,
                                )
                                if target_name:
                                    resolved_sys_config = mapping.ticket_systems[target_name]
                                    adapter = from_config(
                                        target_name,
                                        resolved_sys_config,
                                        mapping.auth_profiles or None,
                                        github_token=github_token,
                                        repo_context=full_repo,
                                    )
                                    if not adapter:
                                        reason = "from_config_failed"
                                    if (
                                        not adapter
                                        and integration_store
                                        and resolved_sys_config.system
                                    ):
                                        try:
                                            adapter = await from_org(
                                                owner,
                                                resolved_sys_config.system,
                                                integration_store,
                                                jira_client_id=settings.jira_oauth_client_id,
                                                jira_client_secret=settings.jira_oauth_client_secret,
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
                                    reason = "no_routing_target_matched"
                                    single = mapping.single_system()
                                    if single:
                                        resolved_sys_config = single
                                        sys_name = next(iter(mapping.ticket_systems.keys()))
                                        adapter = from_config(
                                            sys_name,
                                            single,
                                            mapping.auth_profiles or None,
                                            github_token=github_token,
                                            repo_context=full_repo,
                                        )
                                        if not adapter:
                                            reason = "from_config_failed"
                                        if not adapter and integration_store and single.system:
                                            try:
                                                adapter = await from_org(
                                                    owner,
                                                    single.system,
                                                    integration_store,
                                                    jira_client_id=settings.jira_oauth_client_id,
                                                    jira_client_secret=settings.jira_oauth_client_secret,
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
                                    reason = "no_project_key_and_no_routing"
                                else:
                                    adapter = create_adapter(
                                        ticket_project=project_key,
                                        github_token=github_token,
                                        repo_context=full_repo,
                                    )
                                    reason = "create_adapter_returned_none"

                            if not adapter:
                                logger.warning(
                                    "No ticket adapter resolved for %s/%s/%s "
                                    "(project_key=%r, reason=%s) — skipping reverse sync",
                                    owner,
                                    repo_name,
                                    file_path,
                                    project_key,
                                    reason,
                                )
                                analytics.track(
                                    "sync_adapter_resolution_failed",
                                    properties={
                                        "repo": f"{owner}/{repo_name}",
                                        "file_path": file_path,
                                        "project_key": project_key,
                                        "reason": reason,
                                        "context": "reverse_sync",
                                    },
                                    groups={"organization": owner},
                                )
                                continue

                            updated_md, sync_result = await reverse_sync(
                                result.document,
                                adapter,
                                system_config=resolved_sys_config,
                                repo=full_repo,
                                org=owner,
                                installation_id=int(install_id),
                                ref_store=ref_store,
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
    finally:
        if pool is not None:
            await pool.close()

    if auth_failures and not results:
        raise RuntimeError(
            f"All {auth_failures}/{len(installations)} installations failed — "
            "check GitHub App credentials and installation permissions"
        )

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

    import importlib.metadata
    import socket

    try:
        app_version = importlib.metadata.version("canonhq")
    except importlib.metadata.PackageNotFoundError:
        app_version = "dev"

    analytics.init(
        settings.posthog_key,
        settings.posthog_host,
        super_properties={
            "service": "canon-cron",
            "environment": settings.environment,
            "version": app_version,
            "hostname": socket.gethostname(),
        },
    )

    total_errors = 0
    try:
        results = asyncio.run(run_reverse_sync())

        total_changed = sum(r["changed"] for r in results)
        total_errors = sum(r["errors"] for r in results)

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
        analytics.shutdown()
        otel_logging.shutdown()

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
