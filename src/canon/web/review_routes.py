"""API routes for PR review data."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..auth.deps import require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import Permission
from .models import (
    OrgReviewListResponse,
    OrgReviewSummary,
    PRReviewResponse,
    RepoReviewListResponse,
    ReviewDetail,
    ReviewSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _coerce_analysis(value: object) -> dict:
    # JSONB rows usually return as dicts (via the pool's jsonb codec), but
    # some legacy rows have analysis stored as a JSON-encoded string. Be
    # tolerant of both so a single bad row can't 500 the whole list.
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _review_to_summary(row: dict) -> dict:
    """Convert a pr_reviews DB row to a ReviewSummary dict."""
    analysis = _coerce_analysis(row.get("analysis"))
    return {
        "id": row["id"],
        "pr_number": row["pr_number"],
        "pr_url": row["pr_url"],
        "pr_title": row["pr_title"],
        "pr_author": row["pr_author"],
        "head_sha": row["head_sha"],
        "base_ref": row["base_ref"],
        "model": row["model"],
        "tokens_in": row["tokens_in"],
        "tokens_out": row["tokens_out"],
        "cost_estimate": float(row.get("cost_estimate") or 0),
        "review_kind": row["review_kind"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "spec_reference_count": len(analysis.get("spec_references", [])),
        "discrepancy_count": len(analysis.get("discrepancies", [])),
        "realization_count": len(analysis.get("realizations", [])),
        "realized_count": sum(
            1
            for r in analysis.get("realizations", [])
            if r.get("status") in ("realized", "partially_realized")
        ),
    }


def _review_to_detail(row: dict) -> dict:
    """Convert a pr_reviews DB row to a ReviewDetail dict."""
    summary = _review_to_summary(row)
    summary["analysis"] = _coerce_analysis(row.get("analysis"))
    return summary


def _get_store(request: Request):
    """Get PRReviewStore from app state."""
    return getattr(request.app.state, "pr_review_store", None)


def _check_owner_matches_org(owner: str, org: str) -> None:
    """Reject requests where the path owner doesn't match the org."""
    if owner != org:
        raise HTTPException(
            status_code=400,
            detail=f"Owner '{owner}' does not match organization '{org}'",
        )


@router.get("/app/{org}/api/reviews")
async def list_org_reviews(
    request: Request,
    org: str,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """List PR reviews across all repos in an org."""
    store = _get_store(request)
    if store is None:
        return JSONResponse({"reviews": [], "total": 0}, status_code=200)

    reviews = await store.list_reviews_for_org(org, limit=limit, offset=offset)
    total = await store.count_reviews_for_org(org)
    return OrgReviewListResponse(
        reviews=[
            OrgReviewSummary(repo=r.get("repo", ""), **_review_to_summary(r)) for r in reviews
        ],
        total=total,
    )


@router.get("/app/{org}/api/reviews/{owner}/{repo}")
async def list_repo_reviews(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """List PR reviews for a repo."""
    _check_owner_matches_org(owner, org)
    store = _get_store(request)
    if store is None:
        return JSONResponse(
            {"reviews": [], "total": 0},
            status_code=200,
        )

    full_repo = f"{owner}/{repo}"
    reviews = await store.list_reviews_for_repo(full_repo, limit=limit, offset=offset)
    total = await store.count_reviews_for_repo(full_repo)
    return RepoReviewListResponse(
        reviews=[ReviewSummary(**_review_to_summary(r)) for r in reviews],
        total=total,
    )


@router.get("/app/{org}/api/reviews/{owner}/{repo}/{pr_number}")
async def get_pr_review(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    pr_number: int,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """Get the latest review for a PR with history."""
    _check_owner_matches_org(owner, org)
    store = _get_store(request)
    if store is None:
        return JSONResponse({"review": None, "history": []}, status_code=200)

    full_repo = f"{owner}/{repo}"
    latest = await store.get_latest_review(full_repo, pr_number)
    if latest is None:
        return JSONResponse({"review": None, "history": []}, status_code=200)

    all_reviews = await store.list_reviews_for_pr(full_repo, pr_number)
    history = [ReviewSummary(**_review_to_summary(r)) for r in all_reviews]

    return PRReviewResponse(
        review=ReviewDetail(**_review_to_detail(latest)),
        history=history,
    )
