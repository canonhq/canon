"""Server-side ticket proxy endpoints.

These endpoints let CLI users (who've run ``canon login``) create and
manage GitHub Issues through the Canon server's GitHub App installation
token — no local GITHUB_TOKEN required.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import AnyHttpUrl, BaseModel, Field

from ..auth.deps import require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import Permission
from ..sync.adapters.github_issues import GitHubAdapter
from ..sync.models import (
    CreateTicketInput,
    GitHubConfig,
    UpdateTicketInput,
)
from .routes import _get_client_for_org

logger = logging.getLogger(__name__)

ticket_router = APIRouter(prefix="/app/{org}/api/tickets")


# ── Request models ────────────────────────────────────────


class ProxiedCreateRequest(BaseModel):
    owner: str
    repo: str
    input: CreateTicketInput


class ProxiedStatusRequest(BaseModel):
    owner: str
    repo: str
    ticket_id: str


class ProxiedBatchStatusRequest(BaseModel):
    owner: str
    repo: str
    ticket_ids: list[str] = Field(max_length=100)


class ProxiedUpdateRequest(BaseModel):
    owner: str
    repo: str
    input: UpdateTicketInput


class ProxiedLinkPRRequest(BaseModel):
    owner: str
    repo: str
    ticket_id: str
    pr_url: AnyHttpUrl
    pr_title: str


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


async def _get_github_adapter(
    request: Request, org: str, owner: str, repo: str, user: CurrentUser
) -> GitHubAdapter:
    """Build a GitHubAdapter after validating org access and owner match."""
    _check_org_access(user, org)
    _check_owner_matches_org(owner, org)
    client = await _get_client_for_org(request, org)
    token = await client.get_installation_token()
    return GitHubAdapter(GitHubConfig(token=token, default_owner=owner, default_repo=repo))


# ── Endpoints ─────────────────────────────────────────────


@ticket_router.post("/create", response_class=JSONResponse)
async def create_ticket(
    request: Request,
    org: str,
    body: ProxiedCreateRequest,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
):
    adapter = await _get_github_adapter(request, org, body.owner, body.repo, _user)
    result = await adapter.create_ticket(body.input)
    return JSONResponse(content=result.model_dump())


@ticket_router.post("/status", response_class=JSONResponse)
async def get_ticket_status(
    request: Request,
    org: str,
    body: ProxiedStatusRequest,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    adapter = await _get_github_adapter(request, org, body.owner, body.repo, _user)
    result = await adapter.get_ticket_status(body.ticket_id)
    return JSONResponse(content=result.model_dump())


@ticket_router.post("/batch-status", response_class=JSONResponse)
async def batch_ticket_status(
    request: Request,
    org: str,
    body: ProxiedBatchStatusRequest,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    adapter = await _get_github_adapter(request, org, body.owner, body.repo, _user)
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
    adapter = await _get_github_adapter(request, org, body.owner, body.repo, _user)
    await adapter.update_ticket(body.input)
    return JSONResponse(content={"ok": True})


@ticket_router.post("/link-pr", response_class=JSONResponse)
async def link_pr(
    request: Request,
    org: str,
    body: ProxiedLinkPRRequest,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
):
    adapter = await _get_github_adapter(request, org, body.owner, body.repo, _user)
    await adapter.link_pr(body.ticket_id, str(body.pr_url), body.pr_title)
    return JSONResponse(content={"ok": True})
