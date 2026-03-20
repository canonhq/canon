"""API key management routes — create, list, revoke."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .deps import require_permission
from .models import CurrentUser
from .permissions import ALL_PERMISSION_VALUES, Permission

logger = logging.getLogger(__name__)

api_key_router = APIRouter(prefix="/app/{org}/settings/api-keys")


class CreateApiKeyRequest(BaseModel):
    label: str = ""
    scopes: list[str] = Field(default_factory=list)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


@api_key_router.get("/", response_class=JSONResponse)
async def list_api_keys(
    request: Request,
    org: str,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_ADMIN)),
):
    """List API keys for the current user in this org."""
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None:
        raise HTTPException(status_code=503, detail="API key management not available")

    db_user = await user_store.get_user_by_sub(user.sub)
    if db_user is None:
        return JSONResponse(content={"keys": []})

    keys = await user_store.list_api_keys(user_id=db_user["id"], org_login=org)
    # Serialize datetimes
    for k in keys:
        for field in ("created_at", "expires_at", "revoked_at", "last_used_at"):
            if k.get(field) is not None:
                k[field] = k[field].isoformat()
    return JSONResponse(content={"keys": keys})


@api_key_router.post("/", response_class=JSONResponse)
async def create_api_key(
    request: Request,
    org: str,
    body: CreateApiKeyRequest,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_ADMIN)),
):
    """Create a new API key scoped to this org."""
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None:
        raise HTTPException(status_code=503, detail="API key management not available")

    # Validate scopes and ensure user has each permission
    for scope in body.scopes:
        if scope not in ALL_PERMISSION_VALUES:
            raise HTTPException(status_code=400, detail=f"Invalid scope: {scope}")
        if not user.has_permission(Permission(scope)):
            raise HTTPException(
                status_code=403,
                detail=f"Cannot grant scope you don't have: {scope}",
            )

    # Default scopes to specs:read if none provided
    scopes = body.scopes or [Permission.SPECS_READ.value]

    db_user = await user_store.get_user_by_sub(user.sub)
    if db_user is None:
        raise HTTPException(status_code=400, detail="User not found in database")

    expires_at = None
    if body.expires_in_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days)

    raw_key, record = await user_store.create_api_key(
        user_id=db_user["id"],
        org_login=org,
        scopes=scopes,
        label=body.label,
        expires_at=expires_at,
    )

    return JSONResponse(
        content={
            "key": raw_key,
            "id": record["id"],
            "label": record["label"],
            "scopes": record["scopes"],
            "expires_at": record["expires_at"].isoformat() if record["expires_at"] else None,
        },
        status_code=201,
    )


@api_key_router.delete("/{key_id}", response_class=JSONResponse)
async def revoke_api_key(
    request: Request,
    org: str,
    key_id: int,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_ADMIN)),
):
    """Revoke an API key."""
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None:
        raise HTTPException(status_code=503, detail="API key management not available")

    db_user = await user_store.get_user_by_sub(user.sub)
    if db_user is None:
        raise HTTPException(status_code=400, detail="User not found in database")

    revoked = await user_store.revoke_api_key(key_id=key_id, user_id=db_user["id"], org_login=org)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found or already revoked")

    return JSONResponse(content={"ok": True})
