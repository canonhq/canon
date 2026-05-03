"""Handle push events — detect spec file changes and run forward sync."""

from __future__ import annotations

import logging

from canon import analytics

from ...parser.models import ParseOptions, SpecDocument
from ...parser.parse import parse_spec
from ...settings import Settings
from ...sync.adapters.base import TicketAdapter
from ...sync.adapters.factory import create_adapter, from_config, from_org
from ...sync.engine import forward_sync, forward_sync_multi
from ...sync.mapping import (
    TicketMappingConfig,
    TicketSystemConfig,
    deep_merge_configs,
    synthesize_mapping_config,
)
from ...sync.org_config import load_org_mapping_config
from ...sync.router import resolve_all_targets, resolve_target
from ..spec_utils import filter_spec_files, load_repo_config, matches_doc_patterns

logger = logging.getLogger(__name__)

BOT_SUFFIX = "[bot]"


def _get_notification_dispatcher():
    """Get NotificationDispatcher from app.state, or None."""
    try:
        from canon.main import app

        return getattr(app.state, "notification_dispatcher", None)
    except Exception:
        return None


def _get_integration_store():
    """Get IntegrationStore from app.state, or None."""
    try:
        from canon.main import app

        return getattr(app.state, "integration_store", None)
    except ImportError:
        return None
    except Exception:
        logger.warning("Failed to access integration_store from app.state", exc_info=True)
        return None


async def _notify_spec_status_change(
    spec_title: str, old_status: str, new_status: str, author: str, github_url: str
) -> None:
    """Best-effort: send Slack notification on spec status change."""
    dispatcher = _get_notification_dispatcher()
    if dispatcher is None:
        return
    try:
        await dispatcher.send_spec_status_change(
            spec_title=spec_title,
            old_status=old_status,
            new_status=new_status,
            author=author,
            github_url=github_url,
        )
    except Exception:
        logger.debug("Failed to send spec status change notification", exc_info=True)


async def _notify_coverage_regression(
    spec_title: str, coverage_pct: int, threshold: int, github_url: str
) -> None:
    """Best-effort: send Slack notification on coverage regression."""
    dispatcher = _get_notification_dispatcher()
    if dispatcher is None:
        return
    try:
        await dispatcher.send_coverage_regression(
            spec_title=spec_title,
            coverage_pct=coverage_pct,
            threshold=threshold,
            github_url=github_url,
        )
    except Exception:
        logger.debug("Failed to send coverage regression notification", exc_info=True)


def _invalidate_web_cache(owner: str, repo: str) -> None:
    """Invalidate cached web data for a repo after a push."""
    try:
        from canon.main import app

        cache = getattr(app.state, "cache", None)
        if cache is not None:
            cache.invalidate(f"repo:{owner}/{repo}")
            cache.invalidate(f"config:{owner}/{repo}")
            cache.invalidate_prefix(f"spec:{owner}/{repo}/")
            cache.invalidate_prefix(f"doc:{owner}/{repo}/")
            cache.invalidate_prefix("org_overview:")
            cache.invalidate_prefix("search:")
            cache.invalidate_prefix("facets:")
            logger.info("Invalidated web cache for %s/%s", owner, repo)
    except Exception:
        logger.debug("Web cache not available", exc_info=True)

    try:
        from canon.slack import invalidate_spec_cache

        invalidate_spec_cache(owner, repo)
    except ImportError:
        pass  # Slack module not available
    except Exception:
        logger.warning(
            "Failed to invalidate Slack spec cache for %s/%s", owner, repo, exc_info=True
        )


async def _index_specs(
    owner: str,
    repo: str,
    parsed_specs: dict,
    removed_spec_files: set[str],
    commit_sha: str,
) -> None:
    """Best-effort indexing of changed/removed specs into the search index."""
    try:
        from canon.main import app
        from canon.search.indexer import index_spec, opensearch_doc_id

        search_index = getattr(app.state, "search_index", None)
        if search_index is None:
            return

        embed_client = getattr(app.state, "embed_client", None)
        opensearch_client = getattr(app.state, "opensearch_client", None)
        full_repo = f"{owner}/{repo}"

        for file_path in removed_spec_files:
            try:
                await search_index.delete_spec(full_repo, file_path)
                logger.info("Deleted spec from index: %s:%s", full_repo, file_path)
            except Exception:
                logger.warning(
                    "Failed to delete spec from index: %s:%s", full_repo, file_path, exc_info=True
                )
            if opensearch_client is not None:
                try:
                    await opensearch_client.delete_spec(opensearch_doc_id(full_repo, file_path))
                except Exception:
                    logger.warning(
                        "Failed to delete spec from OpenSearch: %s:%s",
                        full_repo,
                        file_path,
                        exc_info=True,
                    )

        for file_path, doc in parsed_specs.items():
            try:
                await index_spec(
                    doc=doc,
                    repo=full_repo,
                    search_index=search_index,
                    embed_client=embed_client,
                    commit_sha=commit_sha,
                    opensearch_client=opensearch_client,
                )
            except Exception:
                logger.warning("Failed to index spec: %s:%s", full_repo, file_path, exc_info=True)
    except Exception:
        # Outer catch is a last-resort guard for unexpected failures (e.g.
        # canon.main not importable in some test contexts). Log so the
        # operator can see why search updates aren't landing — the prior
        # `pass` swallowed AttributeError, ImportError, etc., silently.
        logger.warning("Search index update failed for %s/%s", owner, repo, exc_info=True)


async def _cache_specs(
    owner: str,
    repo: str,
    parsed_specs: dict,
    spec_contents: dict[str, tuple[str, str]],
    removed_spec_files: set[str],
    installation_id: int = 0,
) -> None:
    """Best-effort caching of spec content into Postgres content cache."""
    try:
        from canon.main import app
        from canon.sync.content_sync import ContentSyncEngine

        content_cache_store = getattr(app.state, "content_cache_store", None)
        if content_cache_store is None:
            return

        github_client = getattr(app.state, "github_client", None)
        engine = ContentSyncEngine(content_cache_store, github_client)
        full_repo = f"{owner}/{repo}"

        for file_path in removed_spec_files:
            try:
                await content_cache_store.delete_spec(full_repo, file_path)
                logger.info("Deleted spec from content cache: %s:%s", full_repo, file_path)
            except Exception:
                logger.warning(
                    "Failed to delete spec from content cache: %s:%s",
                    full_repo,
                    file_path,
                    exc_info=True,
                )

        for file_path, _doc in parsed_specs.items():
            raw_content, file_sha = spec_contents.get(file_path, ("", ""))
            if not raw_content:
                continue
            try:
                await engine.sync_spec(owner, repo, file_path, raw_content, commit_sha=file_sha)
                logger.debug("Cached spec content: %s:%s", full_repo, file_path)
            except Exception:
                logger.warning("Failed to cache spec: %s:%s", full_repo, file_path, exc_info=True)

        # Update push sync timestamp
        if installation_id:
            try:
                from datetime import UTC, datetime

                await content_cache_store.upsert_sync_state(
                    owner, repo, installation_id, last_push_sync_at=datetime.now(UTC)
                )
            except Exception:
                logger.debug("Failed to update push sync timestamp for %s/%s", owner, repo)

    except Exception:
        logger.debug("Content cache not available for %s/%s", owner, repo, exc_info=True)


def _get_doc_patterns(owner: str, repo: str) -> list[str] | None:
    """Load doc_paths from CANON.yaml config cache, or None for defaults."""
    try:
        from canon.main import app

        cache = getattr(app.state, "cache", None)
        if cache is None:
            return None
        cached = cache.get(f"config:{owner}/{repo}")
        if cached is not None:
            return cached.specs.doc_paths
    except Exception:
        pass
    return None


async def _index_doc_files(
    client,
    owner: str,
    repo: str,
    changed_files: set[str],
    removed_files: set[str],
    doc_patterns: list[str],
    commit_sha: str,
) -> None:
    """Best-effort indexing of changed doc files (not just spec files)."""
    try:
        from canon.main import app
        from canon.search.indexer import index_spec, opensearch_doc_id

        search_index = getattr(app.state, "search_index", None)
        if search_index is None:
            return

        embed_client = getattr(app.state, "embed_client", None)
        opensearch_client = getattr(app.state, "opensearch_client", None)
        full_repo = f"{owner}/{repo}"

        # Delete removed doc files from index
        for file_path in removed_files:
            if matches_doc_patterns(file_path, doc_patterns):
                try:
                    await search_index.delete_spec(full_repo, file_path)
                    logger.info("Deleted doc from index: %s:%s", full_repo, file_path)
                except Exception:
                    logger.warning(
                        "Failed to delete doc: %s:%s", full_repo, file_path, exc_info=True
                    )
                if opensearch_client is not None:
                    try:
                        await opensearch_client.delete_spec(opensearch_doc_id(full_repo, file_path))
                    except Exception:
                        logger.warning(
                            "Failed to delete doc from OpenSearch: %s:%s",
                            full_repo,
                            file_path,
                            exc_info=True,
                        )

        # Index changed doc files that aren't already spec files
        for file_path in changed_files:
            if not matches_doc_patterns(file_path, doc_patterns):
                continue
            # Skip if already handled as a spec file
            if filter_spec_files([file_path]):
                continue
            try:
                content, _sha = await client.get_file_content(owner, repo, file_path)
                result = parse_spec(content, ParseOptions(file_path=file_path))
                await index_spec(
                    doc=result.document,
                    repo=full_repo,
                    search_index=search_index,
                    embed_client=embed_client,
                    commit_sha=commit_sha,
                    opensearch_client=opensearch_client,
                )
            except Exception:
                logger.warning("Failed to index doc: %s:%s", full_repo, file_path, exc_info=True)
    except Exception:
        # Outer catch is a last-resort guard for unexpected failures (e.g.
        # canon.main not importable in some test contexts). Logged so
        # operators see why doc indexing isn't landing.
        logger.warning("Doc index update failed for %s/%s", owner, repo, exc_info=True)


async def _track_code_changes(owner: str, repo: str, changed_paths: list[str]) -> None:
    """Best-effort: update last_code_change_at for docs related to changed code."""
    try:
        from canon.main import app

        search_index = getattr(app.state, "search_index", None)
        if search_index is None:
            return

        full_repo = f"{owner}/{repo}"
        newly_stale = await search_index.mark_code_change(full_repo, changed_paths)
        if newly_stale:
            logger.info(
                "Marked %d doc(s) as stale in %s",
                len(newly_stale),
                full_repo,
            )
    except Exception:
        logger.debug("Code change tracking failed for %s/%s", owner, repo, exc_info=True)


async def _try_org_adapter(
    sys_config: TicketSystemConfig | None,
    org: str,
) -> TicketAdapter | None:
    """Try to create an adapter from DB-stored org integration credentials."""
    if not sys_config or not sys_config.system:
        return None
    integration_store = _get_integration_store()
    if integration_store is None:
        return None
    try:
        settings = Settings()
        return await from_org(
            org,
            sys_config.system,
            integration_store,
            jira_client_id=settings.jira_oauth_client_id,
            jira_client_secret=settings.jira_oauth_client_secret,
        )
    except Exception:
        logger.warning(
            "from_org credential lookup failed for org=%s system=%s — "
            "DB-stored OAuth credentials will not be used for this sync",
            org,
            sys_config.system,
            exc_info=True,
        )
        return None


async def _resolve_adapter(
    mapping: TicketMappingConfig,
    doc,
    project_key: str,
    file_path: str,
    *,
    github_token: str = "",
    org: str = "",
) -> tuple[TicketAdapter | None, str, TicketSystemConfig | None]:
    """Resolve a ticket adapter for a spec doc using routing or legacy fallback.

    Credential resolution order:
    1. CANON.yaml auth_profiles / env vars (via ``from_config``)
    2. GitHub App installation token (``github_token``, for GitHub adapters)
    3. DB org_integrations (via ``from_org``, for OAuth-connected orgs)

    Returns (adapter, project_key, system_config) or (None, "", None) when
    no adapter can be resolved.
    """
    adapter = None
    sys_config: TicketSystemConfig | None = None

    if not mapping.is_empty():
        # Try multi-system routing first, then single-system fallback
        target_name = resolve_target(None, doc, mapping.routing, mapping.ticket_systems)
        if target_name:
            sys_config = mapping.ticket_systems[target_name]
            # Empty dict → None so from_config uses default env var detection
            adapter = from_config(
                target_name, sys_config, mapping.auth_profiles or None, github_token=github_token
            )
            # Fallback: try DB-stored org credentials (Jira/Linear OAuth)
            if not adapter:
                adapter = await _try_org_adapter(sys_config, org)
            project_key = project_key or sys_config.project or ""
        else:
            single = mapping.single_system()
            if single:
                sys_config = single
                sys_name = next(iter(mapping.ticket_systems.keys()))
                adapter = from_config(
                    sys_name, single, mapping.auth_profiles or None, github_token=github_token
                )
                if not adapter:
                    adapter = await _try_org_adapter(single, org)
                project_key = project_key or single.project or ""

    if not adapter:
        if not project_key:
            logger.info("No ticket_project in frontmatter for %s, skipping sync", file_path)
            return None, "", None
        adapter = create_adapter(ticket_project=project_key, github_token=github_token)

    if not adapter:
        logger.warning(
            "No ticket adapter configured for %s (project_key=%r)",
            file_path,
            project_key,
        )
        analytics.track(
            "sync_adapter_resolution_failed",
            properties={
                "file_path": file_path,
                "project_key": project_key,
            },
        )
        return None, "", None

    if not project_key:
        logger.info("No project key resolved for %s, skipping sync", file_path)
        return None, "", None

    return adapter, project_key, sys_config


async def _resolve_adapter_multi(
    mapping: TicketMappingConfig,
    doc: SpecDocument,
    project_key: str,
    file_path: str,
    *,
    github_token: str = "",
    org: str = "",
) -> tuple[
    TicketAdapter | None,
    str,
    TicketSystemConfig | None,
    dict[str, tuple[TicketAdapter, TicketSystemConfig]],
]:
    """Resolve primary + shadow adapters using routing rules.

    Args:
        github_token: GitHub App installation token. When provided, GitHub
            adapters use this instead of the GITHUB_TOKEN env var.
        org: GitHub org login, used for DB credential fallback via ``from_org``.

    Returns (adapter, project_key, system_config, shadow_adapters).
    shadow_adapters is a dict of {name: (adapter, config)} for shadow targets.
    """
    shadow_adapters: dict[str, tuple[TicketAdapter, TicketSystemConfig]] = {}
    original_project_key = project_key

    if not mapping.is_empty():
        primary_name, shadow_names = resolve_all_targets(
            None, doc, mapping.routing, mapping.ticket_systems
        )
        if primary_name:
            sys_config = mapping.ticket_systems[primary_name]
            adapter = from_config(
                primary_name, sys_config, mapping.auth_profiles or None, github_token=github_token
            )
            if not adapter:
                adapter = await _try_org_adapter(sys_config, org)
            resolved_key = project_key or sys_config.project or ""

            # Instantiate shadow adapters
            for sname in shadow_names:
                scfg = mapping.ticket_systems[sname]
                sadapter = from_config(
                    sname, scfg, mapping.auth_profiles or None, github_token=github_token
                )
                if not sadapter:
                    sadapter = await _try_org_adapter(scfg, org)
                if sadapter:
                    shadow_adapters[sname] = (sadapter, scfg)
                else:
                    logger.warning(
                        "Shadow adapter %r could not be instantiated for %s — skipping",
                        sname,
                        file_path,
                    )

            if adapter and resolved_key:
                return adapter, resolved_key, sys_config, shadow_adapters
            else:
                logger.warning(
                    "Multi-target routing matched %r but adapter/project resolution failed "
                    "for %s — falling back to single-adapter",
                    primary_name,
                    file_path,
                )

    # Fall back to single-adapter resolution (no shadows).
    # Use the original project_key to avoid bleeding state from the failed multi-target path.
    adapter, project_key, sys_config = await _resolve_adapter(
        mapping, doc, original_project_key, file_path, github_token=github_token, org=org
    )
    return adapter, project_key, sys_config, {}


async def on_push(client, payload: dict) -> None:
    """Handle a GitHub push event.

    Args:
        client: GitHubClient instance.
        payload: The webhook payload.
    """
    commits = payload.get("commits", [])

    # Loop prevention: skip if latest commit is from the bot or has canon/specwright prefix
    if commits:
        latest = commits[-1]
        author_name = (latest.get("author") or {}).get("name", "")
        commit_message = latest.get("message", "")
        if (
            author_name.endswith(BOT_SUFFIX)
            or commit_message.startswith("chore(canon):")
            or commit_message.startswith("chore(specwright):")
        ):
            logger.info("Skipping bot-authored push")
            return

    # Collect changed and removed files separately
    changed_files: set[str] = set()
    removed_files: set[str] = set()
    added_files: set[str] = set()
    for commit in commits:
        for f in commit.get("added", []):
            changed_files.add(f)
            added_files.add(f)
        for f in commit.get("modified", []):
            changed_files.add(f)
        for f in commit.get("removed", []):
            removed_files.add(f)

    # Files that were removed shouldn't be in changed
    changed_files -= removed_files

    all_touched = changed_files | removed_files
    spec_files = filter_spec_files(list(all_touched))

    ref_raw = payload.get("ref", "")
    ref = ref_raw.replace("refs/heads/", "")
    owner = payload["repository"]["owner"]["login"]
    repo = payload["repository"]["name"]

    # Invalidate web cache on any push (spec or doc changes)
    _invalidate_web_cache(owner, repo)

    if not spec_files:
        return

    logger.info("Spec files changed in push: %s ref=%s", spec_files, ref)

    # Track removed spec files and parsed docs for indexing
    removed_spec_files = filter_spec_files(list(removed_files))
    parsed_specs: dict = {}
    spec_contents: dict[str, tuple[str, str]] = {}  # {path: (raw_markdown, file_sha)}
    commit_sha = payload.get("after", "")

    # Load repo config for require_review setting
    config = await load_repo_config(client, owner, repo, ref=ref)
    require_review = config.specs.require_review
    analytics.track(
        "config_loaded",
        properties={
            "repo": f"{owner}/{repo}",
            "auto_tickets": config.specs.auto_tickets,
            "require_review": config.specs.require_review,
        },
        groups={"organization": owner},
    )

    # Resolve ticket mapping config (new-style or legacy)
    mapping, _is_deprecated = synthesize_mapping_config(
        ticket_system=config.ticket_system,
        project_key=config.project_key,
        ticket_mapping=config.ticket_mapping,
    )

    # Merge org-level defaults if available
    org_mapping = await load_org_mapping_config(client, owner)
    if org_mapping:
        mapping = deep_merge_configs(org_mapping, mapping)

    # Obtain the GitHub App installation token so that GitHub-targeted ticket
    # adapters can reuse it instead of requiring a separate GITHUB_TOKEN env var.
    # This is critical for multi-tenant deployments where each repo installation
    # has its own scoped token.
    github_token = await client.get_installation_token()

    # Track distinct adapter system names seen across the per-spec sync loop.
    # Populated as each spec gets a resolved adapter; rolled up into the
    # push-level ``forward_sync_completed`` event after the loop. Using a set
    # so pushes that touch 5 specs all routed through Jira show
    # adapters_used=["jira"] rather than ["jira","jira","jira","jira","jira"].
    _adapters_used: set[str] = set()

    for file_path in spec_files:
        if file_path in removed_files:
            continue  # Skip removed files for sync (handled by indexing)

        try:
            content, file_sha = await client.get_file_content(owner, repo, file_path, ref=ref)
            result = parse_spec(content, ParseOptions(file_path=file_path))
            parsed_specs[file_path] = result.document
            spec_contents[file_path] = (content, file_sha)

            if file_path in added_files:
                from canon.parser.models import flatten_sections as _flat

                fm = result.document.frontmatter
                all_flat = _flat(result.document.sections)
                total_ac = sum(len(s.acceptance_criteria) for s in all_flat)
                analytics.track(
                    "spec_detected",
                    properties={
                        "repo": f"{owner}/{repo}",
                        "spec_path": file_path,
                        "title": fm.title,
                        "author": fm.owner,
                        "team": fm.team,
                        "section_count": len(result.document.sections),
                        "ac_count": total_ac,
                    },
                    groups={"organization": owner},
                )

            try:
                before_sha = payload.get("before", "")
                current_status = result.document.frontmatter.status
                if before_sha and file_path not in added_files:
                    prev_content, _ = await client.get_file_content(
                        owner, repo, file_path, ref=before_sha
                    )
                    prev_result = parse_spec(prev_content, ParseOptions(file_path=file_path))
                    prev_status = prev_result.document.frontmatter.status
                    if prev_status and prev_status != current_status:
                        analytics.track(
                            "spec_status_changed",
                            properties={
                                "repo": f"{owner}/{repo}",
                                "spec_path": file_path,
                                "from_status": prev_status,
                                "to_status": current_status,
                            },
                            groups={"organization": owner},
                        )
                        spec_url = f"https://github.com/{owner}/{repo}/blob/{ref}/{file_path}"
                        spec_title = result.document.frontmatter.title or file_path
                        push_author = (commits[-1].get("author") or {}).get("name", "unknown")
                        await _notify_spec_status_change(
                            spec_title, prev_status, current_status, push_author, spec_url
                        )

                    # Check for coverage regression
                    from canon.parser.models import flatten_sections as _flat_prev

                    prev_flat = _flat_prev(prev_result.document.sections)
                    curr_flat = _flat_prev(result.document.sections)
                    prev_acs = sum(
                        1 for s in prev_flat for ac in s.acceptance_criteria if ac.checked
                    )
                    curr_acs = sum(
                        1 for s in curr_flat for ac in s.acceptance_criteria if ac.checked
                    )
                    total_acs = sum(len(s.acceptance_criteria) for s in curr_flat)
                    if curr_acs < prev_acs and total_acs > 0:
                        coverage_pct = round(curr_acs / total_acs * 100)
                        spec_url = f"https://github.com/{owner}/{repo}/blob/{ref}/{file_path}"
                        spec_title = result.document.frontmatter.title or file_path
                        await _notify_coverage_regression(spec_title, coverage_pct, 80, spec_url)
            except Exception:
                logger.debug(
                    "Failed to track spec_status_changed for %s/%s/%s",
                    owner,
                    repo,
                    file_path,
                    exc_info=True,
                )

            project_key = result.document.frontmatter.ticket_project

            adapter, project_key, sys_config, shadow_adapters = await _resolve_adapter_multi(
                mapping,
                result.document,
                project_key,
                file_path,
                github_token=github_token,
                org=owner,
            )
            if not adapter or not project_key:
                continue

            spec_url = f"https://github.com/{owner}/{repo}/blob/{ref}/{file_path}"

            if shadow_adapters:
                markdown, sync_result = await forward_sync_multi(
                    result.document,
                    primary_adapter=adapter,
                    primary_config=sys_config,
                    primary_project=project_key,
                    shadow_adapters=shadow_adapters,
                    require_review=require_review,
                    spec_url=spec_url,
                    repo=f"{owner}/{repo}",
                    org=owner,
                )
            else:
                markdown, sync_result = await forward_sync(
                    result.document,
                    adapter,
                    project_key,
                    require_review=require_review,
                    system_config=sys_config,
                    spec_url=spec_url,
                    repo=f"{owner}/{repo}",
                    org=owner,
                )

            logger.info(
                "Forward sync complete for %s: created=%d errors=%d",
                file_path,
                len(sync_result.created),
                len(sync_result.errors),
            )

            # Per-spec sync event — carries the adapter name so the Canon ·
            # Ticket Sync dashboard can break sync health down by
            # jira/linear/github. The parent ``forward_sync_completed`` event
            # fires once per push (see below) and can't distinguish adapter
            # counts for pushes that touch specs with different ticket
            # systems. This event is the per-spec granularity.
            adapter_name = getattr(adapter, "system_name", "unknown")
            analytics.track(
                "spec_sync_completed",
                properties={
                    "repo": f"{owner}/{repo}",
                    "file_path": file_path,
                    "adapter": adapter_name,
                    "project_key": project_key,
                    "is_multi_sync": bool(shadow_adapters),
                    "shadow_adapter_count": len(shadow_adapters) if shadow_adapters else 0,
                    "created_count": len(sync_result.created),
                    "updated_count": len(sync_result.updated),
                    "status_changed_count": len(sync_result.status_changed),
                    "error_count": len(sync_result.errors),
                    "success": not sync_result.errors,
                },
                groups={"organization": owner},
            )
            _adapters_used.add(adapter_name)

            # Notify on sync errors (best-effort)
            if sync_result.errors:
                dispatcher = _get_notification_dispatcher()
                if dispatcher is not None:
                    import contextlib

                    system_name = getattr(adapter, "system_name", "unknown")
                    error_msg = "; ".join(e.error for e in sync_result.errors[:3])
                    with contextlib.suppress(Exception):
                        await dispatcher.send_ticket_sync_failure(
                            system=system_name, error=error_msg
                        )

            # Commit updated markdown if tickets were created
            if sync_result.created:
                await client.create_or_update_file(
                    owner,
                    repo,
                    file_path,
                    markdown,
                    f"chore(canon): add ticket links to {file_path}",
                    file_sha,
                    branch=ref,
                )
        except Exception:
            logger.exception("Error during forward sync for %s", file_path)

    # Best-effort: index changed/removed specs
    await _index_specs(
        owner,
        repo,
        parsed_specs,
        set(removed_spec_files),
        commit_sha,
    )

    # Best-effort: cache spec content in Postgres
    await _cache_specs(
        owner,
        repo,
        parsed_specs,
        spec_contents,
        set(removed_spec_files),
        installation_id=int(getattr(client, "installation_id", 0) or 0),
    )

    # Best-effort: index doc files matching configurable doc_paths
    doc_patterns = _get_doc_patterns(owner, repo)
    if doc_patterns:
        await _index_doc_files(
            client,
            owner,
            repo,
            changed_files,
            removed_files,
            doc_patterns,
            commit_sha,
        )

    # Lightweight staleness tracking: mark code changes for non-spec files
    non_spec_changed = changed_files - set(spec_files)
    if non_spec_changed:
        await _track_code_changes(owner, repo, list(non_spec_changed))

    if parsed_specs:
        analytics.track(
            "forward_sync_completed",
            properties={
                "repo": f"{owner}/{repo}",
                "spec_files_synced": len(parsed_specs),
                # ``adapters_used`` is a sorted list of distinct system_name
                # values seen during the per-spec loop above. Sorted so
                # breakdowns in PostHog are deterministic (no flapping when
                # iteration order changes). Empty list means no adapter was
                # successfully resolved for any spec — the push had specs
                # but none of them routed to a ticket system (typical for
                # repos using canon without ticket sync configured).
                "adapters_used": sorted(_adapters_used),
                "adapter_count": len(_adapters_used),
            },
            groups={"organization": owner},
        )
