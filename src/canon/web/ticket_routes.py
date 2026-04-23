"""Server-side ticket proxy endpoints.

These endpoints let CLI users (who've run ``canon login``) create and
manage tickets through the Canon server — no local ticket-system
credentials required.

Supported systems:
- **GitHub** (default): Uses the GitHub App installation token.
- **Jira / Linear**: Uses org-level OAuth credentials from the DB
  (connected via the Settings UI).
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import AnyHttpUrl, BaseModel, Field

from ..auth.deps import require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import Permission
from ..sync.adapters.base import TicketAdapter
from ..sync.adapters.factory import from_org
from ..sync.adapters.github_issues import GitHubAdapter
from ..sync.models import (
    CreateTicketInput,
    GitHubConfig,
    UpdateTicketInput,
)
from .routes import _get_client_for_org

logger = logging.getLogger(__name__)

ticket_router = APIRouter(prefix="/app/{org}/api/tickets")

TicketSystem = Literal["github", "jira", "linear"]


# ── Request models ────────────────────────────────────────


class ProxiedCreateRequest(BaseModel):
    owner: str | None = None
    repo: str | None = None
    ticket_system: TicketSystem | None = None
    project_key: str | None = None
    input: CreateTicketInput


class ProxiedStatusRequest(BaseModel):
    owner: str | None = None
    repo: str | None = None
    ticket_system: TicketSystem | None = None
    ticket_id: str


class ProxiedBatchStatusRequest(BaseModel):
    owner: str | None = None
    repo: str | None = None
    ticket_system: TicketSystem | None = None
    ticket_ids: list[str] = Field(max_length=100)


class ProxiedUpdateRequest(BaseModel):
    owner: str | None = None
    repo: str | None = None
    ticket_system: TicketSystem | None = None
    input: UpdateTicketInput


class ProxiedLinkPRRequest(BaseModel):
    owner: str | None = None
    repo: str | None = None
    ticket_system: TicketSystem | None = None
    ticket_id: str
    pr_url: AnyHttpUrl
    pr_title: str


class ProxiedSearchRequest(BaseModel):
    owner: str | None = None
    repo: str | None = None
    ticket_system: TicketSystem | None = None
    project_key: str = Field(max_length=100, pattern=r'^[^"\\]+$')
    title_pattern: str = Field(max_length=200, pattern=r'^[^"\\]+$')


# ── Helpers ───────────────────────────────────────────────


def _check_org_access(user: CurrentUser, org: str) -> None:
    """Verify the authenticated user belongs to the requested org.

    Fails closed: authenticated users without an org_login are rejected.
    Anonymous users (dev mode) are allowed through since auth is disabled.
    """
    if user.is_anonymous:
        return
    if not user.org_login or user.org_login != org:
        raise HTTPException(status_code=403, detail="Access denied for this organization")


def _check_owner_matches_org(owner: str, org: str) -> None:
    """Reject requests where the body owner doesn't match the path org."""
    if owner != org:
        raise HTTPException(
            status_code=400,
            detail=f"Owner '{owner}' does not match organization '{org}'",
        )


async def _get_adapter(
    request: Request,
    org: str,
    user: CurrentUser,
    *,
    ticket_system: TicketSystem | None,
    owner: str | None = None,
    repo: str | None = None,
) -> TicketAdapter:
    """Build the appropriate TicketAdapter based on the requested system.

    - github (default): Uses the GitHub App installation token.
    - jira / linear: Uses org-level OAuth credentials from the DB.
    """
    _check_org_access(user, org)

    system = ticket_system or "github"

    if system == "github":
        if not owner or not repo:
            raise HTTPException(
                status_code=400,
                detail="owner and repo are required for GitHub ticket operations",
            )
        _check_owner_matches_org(owner, org)
        client = await _get_client_for_org(request, org)
        token = await client.get_installation_token()
        return GitHubAdapter(GitHubConfig(token=token, default_owner=owner, default_repo=repo))

    # Jira / Linear — resolve from DB-stored OAuth credentials
    integration_store = getattr(request.app.state, "integration_store", None)
    if integration_store is None:
        raise HTTPException(
            status_code=503,
            detail="Integration credential store is not available",
        )

    settings = request.app.state.settings
    adapter = await from_org(
        org,
        system,
        integration_store,
        jira_client_id=settings.jira_oauth_client_id,
        jira_client_secret=settings.jira_oauth_client_secret,
    )
    if adapter is None:
        raise HTTPException(
            status_code=422,
            detail=f"{system.capitalize()} integration is not connected for organization '{org}'. "
            f"Connect it at /app/{org}/settings/integrations.",
        )
    return adapter


# ── Endpoints ─────────────────────────────────────────────


@ticket_router.post("/create", response_class=JSONResponse)
async def create_ticket(
    request: Request,
    org: str,
    body: ProxiedCreateRequest,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
):
    adapter = await _get_adapter(
        request,
        org,
        _user,
        ticket_system=body.ticket_system,
        owner=body.owner,
        repo=body.repo,
    )
    result = await adapter.create_ticket(body.input)
    return JSONResponse(content=result.model_dump())


@ticket_router.post("/status", response_class=JSONResponse)
async def get_ticket_status(
    request: Request,
    org: str,
    body: ProxiedStatusRequest,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    adapter = await _get_adapter(
        request,
        org,
        _user,
        ticket_system=body.ticket_system,
        owner=body.owner,
        repo=body.repo,
    )
    result = await adapter.get_ticket_status(body.ticket_id)
    return JSONResponse(content=result.model_dump())


@ticket_router.post("/batch-status", response_class=JSONResponse)
async def batch_ticket_status(
    request: Request,
    org: str,
    body: ProxiedBatchStatusRequest,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    adapter = await _get_adapter(
        request,
        org,
        _user,
        ticket_system=body.ticket_system,
        owner=body.owner,
        repo=body.repo,
    )
    results: list[dict] = []
    errors: list[dict] = []
    for tid in body.ticket_ids:
        try:
            result = await adapter.get_ticket_status(tid)
            results.append(result.model_dump())
        except Exception as exc:
            logger.warning("batch-status failed for ticket %s: %s", tid, exc)
            errors.append({"ticket_id": tid, "error": "Failed to fetch ticket status"})
    return JSONResponse(content={"results": results, "errors": errors})


@ticket_router.post("/update", response_class=JSONResponse)
async def update_ticket(
    request: Request,
    org: str,
    body: ProxiedUpdateRequest,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
):
    adapter = await _get_adapter(
        request,
        org,
        _user,
        ticket_system=body.ticket_system,
        owner=body.owner,
        repo=body.repo,
    )
    await adapter.update_ticket(body.input)
    return JSONResponse(content={"ok": True})


@ticket_router.post("/link-pr", response_class=JSONResponse)
async def link_pr(
    request: Request,
    org: str,
    body: ProxiedLinkPRRequest,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
):
    adapter = await _get_adapter(
        request,
        org,
        _user,
        ticket_system=body.ticket_system,
        owner=body.owner,
        repo=body.repo,
    )
    await adapter.link_pr(body.ticket_id, str(body.pr_url), body.pr_title)
    return JSONResponse(content={"ok": True})


@ticket_router.post("/search", response_class=JSONResponse)
async def search_tickets(
    request: Request,
    org: str,
    body: ProxiedSearchRequest,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    adapter = await _get_adapter(
        request,
        org,
        _user,
        ticket_system=body.ticket_system,
        owner=body.owner,
        repo=body.repo,
    )
    results = await adapter.search_tickets(body.project_key, body.title_pattern)
    return JSONResponse(content=[r.model_dump() for r in results])
