"""Sync management API endpoints.

Provides endpoints for viewing sync history, triggering manual syncs,
reading/writing ticket mapping configuration, and fetching status map presets.
"""

from __future__ import annotations

import logging
import time
import uuid as _uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..auth.deps import require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import Permission
from ..db.sync_history_store import SyncHistoryStore

logger = logging.getLogger(__name__)

sync_router = APIRouter()

# Simple in-memory rate limiter for manual sync triggers: repo → last_trigger_ts.
# Per-process only — not distributed across replicas.
_trigger_rate_limit: dict[str, float] = {}
_TRIGGER_COOLDOWN_SECONDS = 60
_TRIGGER_RATE_LIMIT_MAX_ENTRIES = 1000


# ── Request / Response models ────────────────────────────────


class SyncTriggerRequest(BaseModel):
    repo: str = Field(..., description="owner/repo")
    spec_path: str | None = Field(None, description="Specific spec file to sync")
    direction: Literal["forward", "reverse", "both"] = "forward"


class SyncRetryRequest(BaseModel):
    run_id: str
    event_ids: list[str] = Field(default_factory=list, description="Specific event IDs to retry")


class SyncRunsQuery(BaseModel):
    repo: str | None = None
    system: str | None = None
    direction: str | None = None
    status: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    cursor: datetime | None = None
    limit: int = Field(50, ge=1, le=100)


class SyncConfigUpdate(BaseModel):
    """Ticket mapping config update payload.

    All fields default to None so that omitted fields are skipped
    during partial updates (avoids silently overwriting with empty values).
    """

    ticket_systems: dict[str, Any] | None = None
    routing: list[dict[str, Any]] | None = None
    auth_profiles: dict[str, Any] | None = None


class SyncConfigValidateRequest(BaseModel):
    """Config to validate without saving."""

    config: dict[str, Any]


# ── Helpers ──────────────────────────────────────────────────


def _get_sync_store(request: Request) -> SyncHistoryStore:
    """Get or create SyncHistoryStore from app state."""
    store = getattr(request.app.state, "sync_history_store", None)
    if not store:
        pool = getattr(request.app.state, "db_pool", None)
        if not pool:
            raise HTTPException(status_code=503, detail="Database not available")
        store = SyncHistoryStore(pool)
        request.app.state.sync_history_store = store
    return store


def _check_org_access(user: CurrentUser, org: str) -> None:
    """Verify the authenticated user belongs to the requested org."""
    if user.is_anonymous:
        return
    if not user.org_login or user.org_login != org:
        raise HTTPException(status_code=403, detail="Access denied for this organization")


def _validate_uuid(value: str, field_name: str = "id") -> None:
    """Validate that a string is a valid UUID, raising 400 if not."""
    try:
        _uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format") from None


def _check_owner_matches_org(owner: str, org: str) -> None:
    """Reject requests where the path owner doesn't match the org."""
    if owner != org:
        raise HTTPException(
            status_code=400,
            detail=f"Owner '{owner}' does not match organization '{org}'",
        )


# ── Repos Endpoint ─────────────────────────────────────────


@sync_router.get("/app/{org}/api/sync/repos")
async def sync_repos(
    org: str,
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    """List repos accessible to the org's GitHub App installation.

    Unlike the editor repos endpoint (which requires user GitHub OAuth),
    this uses the GitHub App installation token so it always works for
    authenticated org members.
    """
    _check_org_access(user, org)

    try:
        client = await _get_github_client(request, org)
        raw_repos = await client.list_installation_repos()
    except Exception:
        logger.warning("Failed to list installation repos for %s", org, exc_info=True)
        return JSONResponse([])

    # Return a slim payload: full_name, name, owner, private, default_branch
    repos = [
        {
            "full_name": r.get("full_name", ""),
            "name": r.get("name", ""),
            "owner": r.get("owner", {}).get("login", ""),
            "private": r.get("private", False),
            "default_branch": r.get("default_branch", "main"),
        }
        for r in raw_repos
        if r.get("full_name")
    ]
    repos.sort(key=lambda r: r["full_name"].lower())
    return JSONResponse(repos)


# ── Sync Dashboard Endpoints ────────────────────────────────


@sync_router.get("/app/{org}/api/sync/stats")
async def sync_stats(
    org: str,
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    """Get aggregate sync stats for the org dashboard."""
    _check_org_access(user, org)
    store = _get_sync_store(request)
    stats = await store.get_stats(org)
    # Convert any non-serializable types
    return JSONResponse({k: int(v) if isinstance(v, int) else v for k, v in stats.items()})


@sync_router.get("/app/{org}/api/sync/runs")
async def sync_runs_list(
    org: str,
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
    repo: str | None = None,
    system: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    since: str | None = None,
    until: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> JSONResponse:
    """List sync runs with optional filters and cursor pagination."""
    _check_org_access(user, org)
    store = _get_sync_store(request)

    cursor_dt = None
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
        except ValueError as err:
            raise HTTPException(status_code=400, detail="Invalid cursor format") from err

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as err:
            raise HTTPException(status_code=400, detail="Invalid since format") from err

    until_dt = None
    if until:
        try:
            until_dt = datetime.fromisoformat(until)
        except ValueError as err:
            raise HTTPException(status_code=400, detail="Invalid until format") from err

    effective_limit = max(1, min(limit, 100))
    runs = await store.list_runs(
        org,
        repo=repo,
        system=system,
        direction=direction,
        status=status,
        since=since_dt,
        until=until_dt,
        cursor=cursor_dt,
        limit=effective_limit,
    )

    # Serialize datetime fields
    serialized = []
    for run in runs:
        serialized.append(_serialize_row(run))

    next_cursor = None
    if runs and len(runs) == effective_limit:
        last = runs[-1]
        if last.get("started_at"):
            next_cursor = last["started_at"].isoformat()

    return JSONResponse({"runs": serialized, "next_cursor": next_cursor})


@sync_router.get("/app/{org}/api/sync/runs/{run_id}")
async def sync_run_detail(
    org: str,
    run_id: str,
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    """Get a single sync run with all its events."""
    _check_org_access(user, org)
    _validate_uuid(run_id, "run_id")
    store = _get_sync_store(request)

    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found")
    if run["org_login"] != org:
        raise HTTPException(status_code=403, detail="Access denied")

    events = await store.get_run_events(run_id)

    # Group events by type
    grouped: dict[str, list[dict]] = {}
    for event in events:
        et = event.get("event_type", "unknown")
        grouped.setdefault(et, []).append(_serialize_row(event))

    return JSONResponse(
        {
            "run": _serialize_row(run),
            "events": grouped,
            "event_counts": {k: len(v) for k, v in grouped.items()},
        }
    )


@sync_router.get("/app/{org}/api/sync/specs/{owner}/{repo}/{path:path}")
async def spec_sync_status(
    org: str,
    owner: str,
    repo: str,
    path: str,
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    """Get sync status for a specific spec file."""
    _check_org_access(user, org)
    _check_owner_matches_org(owner, org)
    store = _get_sync_store(request)
    status = await store.get_spec_sync_status(org, owner, repo, path)

    result: dict[str, Any] = {"recent_errors": status["recent_errors"]}
    if status["last_run"]:
        result["last_run"] = _serialize_row(status["last_run"])
    else:
        result["last_run"] = None

    return JSONResponse(result)


# ── Sync Trigger Endpoints ──────────────────────────────────


@sync_router.post("/app/{org}/api/sync/trigger")
async def trigger_sync(
    org: str,
    body: SyncTriggerRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
) -> JSONResponse:
    """Manually trigger a sync operation. Runs in background."""
    _check_org_access(user, org)

    # Rate limit: 1 trigger per repo per minute (per-process, not distributed)
    rate_key = f"{org}/{body.repo}"
    now = time.time()
    last = _trigger_rate_limit.get(rate_key, 0)
    if now - last < _TRIGGER_COOLDOWN_SECONDS:
        raise HTTPException(
            status_code=429,
            detail=f"Sync for {body.repo} was triggered recently. Please wait.",
        )
    _trigger_rate_limit[rate_key] = now

    # Evict stale entries to prevent unbounded growth
    if len(_trigger_rate_limit) > _TRIGGER_RATE_LIMIT_MAX_ENTRIES:
        stale = [k for k, v in _trigger_rate_limit.items() if now - v > _TRIGGER_COOLDOWN_SECONDS]
        for k in stale:
            del _trigger_rate_limit[k]

    store = _get_sync_store(request)

    # Create a placeholder run so we can return the run_id immediately
    run_id = await store.create_run(
        org_login=org,
        repo=body.repo,
        spec_path=body.spec_path,
        system="pending",
        direction=body.direction,
        trigger="manual",
        triggered_by=user.sub or user.email or "unknown",
    )

    # TODO: Background task that actually runs the sync.
    # For now, we mark the run as needing execution.
    # This will be wired up when the full background sync executor is built.
    background_tasks.add_task(
        _execute_manual_sync,
        request=request,
        org=org,
        repo=body.repo,
        spec_path=body.spec_path,
        direction=body.direction,
        run_id=run_id,
    )

    return JSONResponse({"run_id": run_id, "status": "started"}, status_code=202)


async def _execute_manual_sync(
    *,
    request: Request,
    org: str,
    repo: str,
    spec_path: str | None,
    direction: str,
    run_id: str,
) -> None:
    """Execute a manually triggered sync in the background.

    Resolves adapters from CANON.yaml (+ org defaults + DB credentials),
    loads spec files, and runs forward_sync / reverse_sync per spec.
    """
    from ..github.spec_utils import (
        extract_directories,
        load_repo_config,
        matches_doc_patterns,
    )
    from ..parser import ParseOptions, parse_spec
    from ..sync.adapters.factory import create_adapter, from_config, from_org
    from ..sync.engine import forward_sync, reverse_sync
    from ..sync.mapping import deep_merge_configs, synthesize_mapping_config
    from ..sync.org_config import load_org_mapping_config
    from ..sync.router import resolve_target

    store: SyncHistoryStore | None = None
    try:
        store = _get_sync_store(request)
        owner, repo_name = repo.split("/", 1) if "/" in repo else (org, repo)

        logger.info(
            "Manual sync starting for %s/%s (direction=%s, run_id=%s)",
            owner,
            repo_name,
            direction,
            run_id,
        )

        # 1. Get GitHub client and installation token
        client = await _get_github_client(request, org)
        github_token = await client.get_installation_token()

        # 2. Load repo config and synthesize mapping
        repo_config = await load_repo_config(client, owner, repo_name)
        mapping, _deprecated = synthesize_mapping_config(
            ticket_system=repo_config.ticket_system,
            project_key=repo_config.project_key,
            ticket_mapping=repo_config.ticket_mapping,
        )

        # Merge org-level defaults
        org_mapping = await load_org_mapping_config(client, owner)
        if org_mapping:
            mapping = deep_merge_configs(org_mapping, mapping)

        if mapping.is_empty():
            await store.add_event(
                run_id,
                event_type="error",
                section_title="Configuration",
                detail={
                    "error": (
                        "No ticket mapping configured. Add a ticket_systems section "
                        "to your CANON.yaml or configure mapping in Settings > Sync."
                    ),
                },
            )
            await store.complete_run(run_id, status="failed", error_count=1)
            return

        # 3. Discover spec files
        doc_paths = repo_config.specs.doc_paths
        if spec_path:
            spec_files = [spec_path]
        else:
            directories = extract_directories(doc_paths)
            entries: list[dict] = []
            for directory, _is_recursive in directories:
                entries.extend(await client.list_directory(owner, repo_name, directory))
            spec_files = [
                e.get("path", e.get("name", ""))
                for e in entries
                if e.get("type") == "file"
                and e.get("name", "").endswith(".md")
                and not e.get("name", "").startswith("_")
                and matches_doc_patterns(e.get("path", e.get("name", "")), doc_paths)
            ]

        if not spec_files:
            await store.add_event(
                run_id,
                event_type="error",
                section_title="Discovery",
                detail={"error": "No spec files found in this repository."},
            )
            await store.complete_run(run_id, status="failed", error_count=1)
            return

        # 4. Resolve settings for DB credential fallback
        settings = getattr(request.app.state, "settings", None)
        integration_store = getattr(request.app.state, "integration_store", None)

        # 5. Process each spec file
        total_created = 0
        total_updated = 0
        total_closed = 0
        total_reopened = 0
        total_skipped = 0
        total_errors = 0

        for file_path in spec_files:
            try:
                content, file_sha = await client.get_file_content(owner, repo_name, file_path)
                result = parse_spec(content, ParseOptions(file_path=file_path))
                project_key = result.document.frontmatter.ticket_project

                # Resolve adapter via routing → single-system → env fallback
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
                                    owner,
                                    resolved_sys_config.system,
                                    integration_store,
                                    jira_client_id=getattr(settings, "jira_oauth_client_id", ""),
                                    jira_client_secret=getattr(
                                        settings, "jira_oauth_client_secret", ""
                                    ),
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
                                        owner,
                                        single.system,
                                        integration_store,
                                        jira_client_id=getattr(
                                            settings, "jira_oauth_client_id", ""
                                        ),
                                        jira_client_secret=getattr(
                                            settings, "jira_oauth_client_secret", ""
                                        ),
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
                        await store.add_event(
                            run_id,
                            event_type="skipped",
                            section_title=file_path,
                            detail={"message": "No adapter resolved and no project_key set"},
                        )
                        total_skipped += 1
                        continue
                    adapter = create_adapter(ticket_project=project_key, github_token=github_token)

                if not adapter:
                    await store.add_event(
                        run_id,
                        event_type="skipped",
                        section_title=file_path,
                        detail={
                            "message": (
                                f"No ticket adapter could be resolved for project_key={project_key!r}. "
                                "Check that integration credentials are configured."
                            ),
                        },
                    )
                    total_skipped += 1
                    continue

                spec_url = f"https://github.com/{owner}/{repo_name}/blob/main/{file_path}"
                full_repo = f"{owner}/{repo_name}"

                # Run sync — omit sync_store so the engine doesn't create
                # its own run record (we manage the run ourselves).
                if direction in ("forward", "both"):
                    updated_md, sync_result = await forward_sync(
                        result.document,
                        adapter,
                        project_key,
                        system_config=resolved_sys_config,
                        spec_url=spec_url,
                        repo=full_repo,
                        org=owner,
                    )

                    total_created += len(sync_result.created)
                    total_updated += len(sync_result.updated)
                    total_closed += len(sync_result.closed)
                    total_reopened += len(sync_result.reopened)
                    total_skipped += len(sync_result.skipped)
                    total_errors += len(sync_result.errors)

                    # Record events for this spec
                    for item in sync_result.created:
                        await store.add_event(
                            run_id,
                            event_type="created",
                            section_title=item.section_id,
                            ticket_id=item.ticket_id,
                            ticket_url=getattr(item, "ticket_url", None),
                        )
                    for item in sync_result.errors:
                        await store.add_event(
                            run_id,
                            event_type="error",
                            section_title=item.section_id,
                            detail={"error": item.error},
                        )

                    # Commit updated markdown if tickets were created
                    if sync_result.created and updated_md != content:
                        try:
                            await client.create_or_update_file(
                                owner,
                                repo_name,
                                file_path,
                                updated_md,
                                f"chore(canon): add ticket links to {file_path}",
                                file_sha,
                            )
                            # Re-fetch SHA after commit so reverse sync
                            # doesn't conflict with the new HEAD.
                            _, file_sha = await client.get_file_content(owner, repo_name, file_path)
                            content = updated_md
                        except Exception:
                            logger.warning(
                                "Failed to commit updated markdown for %s",
                                file_path,
                                exc_info=True,
                            )

                if direction in ("reverse", "both"):
                    updated_md, sync_result = await reverse_sync(
                        result.document,
                        adapter,
                        system_config=resolved_sys_config,
                        repo=full_repo,
                        org=owner,
                    )

                    total_updated += len(sync_result.status_changed)
                    total_errors += len(sync_result.errors)

                    for item in sync_result.status_changed:
                        await store.add_event(
                            run_id,
                            event_type="status_changed",
                            section_title=item.section_id,
                            ticket_id=item.ticket_id,
                            detail={
                                "message": f"{item.old_state} → {item.new_state}",
                            },
                        )
                    for item in sync_result.errors:
                        await store.add_event(
                            run_id,
                            event_type="error",
                            section_title=item.section_id,
                            detail={"error": item.error},
                        )

                    # Commit updated markdown if statuses changed
                    if sync_result.status_changed and updated_md != content:
                        try:
                            await client.create_or_update_file(
                                owner,
                                repo_name,
                                file_path,
                                updated_md,
                                f"chore(canon): sync ticket statuses in {file_path}",
                                file_sha,
                            )
                        except Exception:
                            logger.warning(
                                "Failed to commit updated markdown for %s",
                                file_path,
                                exc_info=True,
                            )

            except Exception:
                logger.exception("Error syncing spec %s", file_path)
                total_errors += 1
                await store.add_event(
                    run_id,
                    event_type="error",
                    section_title=file_path,
                    detail={"error": f"Unexpected error processing {file_path}"},
                )

        # 6. Complete the run
        status = (
            "success"
            if total_errors == 0
            else ("partial_success" if total_created > 0 else "failed")
        )

        # Update system name on the run
        await store.complete_run(
            run_id,
            status=status,
            created_count=total_created,
            updated_count=total_updated,
            closed_count=total_closed,
            reopened_count=total_reopened,
            skipped_count=total_skipped,
            error_count=total_errors,
        )

        logger.info(
            "Manual sync complete for %s/%s: status=%s created=%d updated=%d errors=%d",
            owner,
            repo_name,
            status,
            total_created,
            total_updated,
            total_errors,
        )

    except Exception:
        logger.exception("Manual sync failed for run %s", run_id)
        if store:
            try:
                await store.add_event(
                    run_id,
                    event_type="error",
                    section_title="Sync engine",
                    detail={"error": "Unexpected error during sync execution. Check server logs."},
                )
                await store.complete_run(run_id, status="failed", error_count=1)
            except Exception:
                logger.warning("Failed to mark run %s as failed", run_id, exc_info=True)


@sync_router.post("/app/{org}/api/sync/retry")
async def retry_sync(
    org: str,
    body: SyncRetryRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
) -> JSONResponse:
    """Retry failed sync events from a previous run."""
    _check_org_access(user, org)
    _validate_uuid(body.run_id, "run_id")
    store = _get_sync_store(request)

    run = await store.get_run(body.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found")
    if run["org_login"] != org:
        raise HTTPException(status_code=403, detail="Access denied")

    # TODO: Implement actual retry logic — re-run failed sections
    # For now, return acknowledgment
    return JSONResponse({"status": "retry_queued", "original_run_id": body.run_id})


# ── Config Endpoints ─────────────────────────────────────────


@sync_router.get("/app/{org}/api/sync/config/{owner}/{repo}")
async def get_sync_config(
    org: str,
    owner: str,
    repo: str,
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    """Read the parsed ticket mapping config for a repo."""
    _check_org_access(user, org)
    _check_owner_matches_org(owner, org)

    from ..github.spec_utils import load_repo_config
    from ..sync.mapping import deep_merge_configs, synthesize_mapping_config
    from ..sync.org_config import load_org_mapping_config

    client = await _get_github_client(request, org)
    try:
        repo_config = await load_repo_config(client, owner, repo)
    except Exception:
        logger.warning("Failed to load repo config for %s/%s", owner, repo, exc_info=True)
        raise HTTPException(status_code=404, detail="Could not load repo config") from None

    mapping, _deprecated = synthesize_mapping_config(
        ticket_system=repo_config.ticket_system,
        project_key=repo_config.project_key,
        ticket_mapping=repo_config.ticket_mapping,
    )

    # Merge org defaults
    org_mapping = await load_org_mapping_config(client, owner)
    effective = deep_merge_configs(org_mapping, mapping) if org_mapping else mapping

    return JSONResponse(
        {
            "repo_config": mapping.model_dump(mode="json"),
            "effective_config": effective.model_dump(mode="json"),
            "has_org_defaults": org_mapping is not None,
        }
    )


@sync_router.put("/app/{org}/api/sync/config/{owner}/{repo}")
async def update_sync_config(
    org: str,
    owner: str,
    repo: str,
    body: SyncConfigUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
) -> JSONResponse:
    """Update ticket mapping config in CANON.yaml via GitHub commit."""
    _check_org_access(user, org)
    _check_owner_matches_org(owner, org)

    import yaml

    client = await _get_github_client(request, org)

    # Load current CANON.yaml
    try:
        content, file_sha = await client.get_file_content(owner, repo, "CANON.yaml")
    except Exception:
        content, file_sha = "", None

    try:
        current = yaml.safe_load(content) if content else {}
    except yaml.YAMLError:
        current = {}

    if not isinstance(current, dict):
        current = {}

    # Update ticket mapping section
    if body.ticket_systems is not None:
        current["ticket_systems"] = body.ticket_systems
    if body.routing is not None:
        current["routing"] = body.routing
    if body.auth_profiles is not None:
        current["auth_profiles"] = body.auth_profiles

    # Validate merged config before committing
    from ..sync.mapping import TicketMappingConfig

    ticket_config = {
        k: current[k] for k in ("ticket_systems", "routing", "auth_profiles") if k in current
    }
    if ticket_config:
        try:
            TicketMappingConfig(**ticket_config)
        except (ValueError, TypeError) as err:
            raise HTTPException(
                status_code=422, detail=f"Invalid ticket mapping config: {err}"
            ) from None

    updated_yaml = yaml.dump(current, default_flow_style=False, sort_keys=False)

    # Commit to repo
    try:
        await client.create_or_update_file(
            owner,
            repo,
            "CANON.yaml",
            updated_yaml,
            "chore: update ticket mapping config",
            file_sha,
        )
    except Exception:
        logger.exception("Failed to commit config for %s/%s", owner, repo)
        raise HTTPException(status_code=500, detail="Failed to commit config update") from None

    return JSONResponse({"status": "updated"})


@sync_router.post("/app/{org}/api/sync/config/{owner}/{repo}/validate")
async def validate_sync_config(
    org: str,
    owner: str,
    repo: str,
    body: SyncConfigValidateRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    """Validate a ticket mapping config without saving."""
    _check_org_access(user, org)
    _check_owner_matches_org(owner, org)

    from ..sync.mapping import TicketMappingConfig

    errors: list[str] = []
    warnings: list[str] = []

    try:
        config = TicketMappingConfig(**body.config)
        # Run cross-reference validation
        if hasattr(config, "validate_references"):
            config.validate_references()
    except (ValueError, TypeError) as err:
        errors.append(str(err))

    # Check for common issues
    if not body.config.get("ticket_systems"):
        warnings.append("No ticket systems defined")

    routing = body.config.get("routing", [])
    has_default = any(r.get("match", {}).get("default") for r in routing)
    if routing and not has_default:
        warnings.append("No default routing rule — specs without matching rules won't sync")

    return JSONResponse(
        {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }
    )


@sync_router.get("/app/{org}/api/sync/config/{owner}/{repo}/presets")
async def get_config_presets(
    org: str,
    owner: str,
    repo: str,
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
    system: str | None = None,
) -> JSONResponse:
    """Get available status map presets."""
    _check_org_access(user, org)

    from ..sync.presets import get_presets

    presets = get_presets(system)
    return JSONResponse({"presets": presets})


# ── Internal helpers ─────────────────────────────────────────


async def _get_github_client(request: Request, org: str) -> Any:
    """Get a GitHub client from app state."""
    from .routes import _get_client_for_org

    return await _get_client_for_org(request, org)


def _serialize_row(row: dict) -> dict:
    """Serialize a DB row dict for JSON response, converting datetimes and UUIDs."""
    import json as _json

    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif hasattr(v, "hex"):  # UUID
            result[k] = str(v)
        elif k == "detail" and isinstance(v, str):
            # asyncpg may return JSONB as a string — parse it
            try:
                result[k] = _json.loads(v)
            except (ValueError, TypeError):
                result[k] = v
        else:
            result[k] = v
    return result
