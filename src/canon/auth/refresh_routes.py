"""Token refresh endpoint — serves both web (cookie) and CLI (body) clients."""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

refresh_router = APIRouter(prefix="/auth")

#: Cookie name for the httpOnly refresh token (web clients).
REFRESH_COOKIE = "sw_refresh"


class RefreshRequest(BaseModel):
    """CLI clients send the refresh token in the request body."""

    refresh_token: str = ""


class RevokeRequest(BaseModel):
    """CLI clients send the refresh token to revoke."""

    refresh_token: str = ""


@refresh_router.post("/refresh", response_class=JSONResponse)
async def refresh_token(request: Request, body: RefreshRequest | None = None):
    """Exchange a refresh token for a new access token.

    The refresh token can come from:
    1. An httpOnly cookie ``sw_refresh`` (web clients)
    2. The JSON body ``{"refresh_token": "..."}`` (CLI clients)

    On success the refresh hash is rotated in the DB and new tokens are
    returned.  For cookie-sourced requests the new refresh token is set
    as a cookie; for body-sourced requests it is included in the response
    JSON.
    """
    # Determine source of refresh token
    cookie_token = request.cookies.get(REFRESH_COOKIE, "")
    body_token = body.refresh_token if body else ""
    old_refresh_token = cookie_token or body_token
    source = "cookie" if cookie_token else "body"

    if not old_refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token provided")

    # Look up session
    session_store = getattr(request.app.state, "session_store", None)
    if not session_store:
        raise HTTPException(status_code=503, detail="Session management not available")

    old_hash = hashlib.sha256(old_refresh_token.encode()).hexdigest()
    session = await session_store.get_session_by_refresh_hash(old_hash)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Exchange refresh token with the configured OIDC provider
    provider = getattr(request.app.state, "oidc_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="Auth provider not configured")

    try:
        token_set = await provider.refresh_tokens(refresh_token=old_refresh_token)
    except Exception as exc:
        logger.warning("Provider refresh failed: %s", exc)
        raise HTTPException(status_code=401, detail="Refresh token rejected by provider") from exc

    new_access_token = token_set.access_token
    new_refresh_token = token_set.refresh_token or old_refresh_token
    expires_in = token_set.expires_in or 86400

    # Rotate refresh hash in DB
    new_hash = hashlib.sha256(new_refresh_token.encode()).hexdigest()
    rotated = await session_store.rotate_refresh(
        session_id=session["id"],
        old_hash=old_hash,
        new_hash=new_hash,
    )
    if not rotated:
        logger.warning("Refresh hash rotation race for session %s — revoking", session["id"])
        await session_store.revoke_session(session_id=session["id"], user_id=session["user_id"])
        raise HTTPException(
            status_code=401, detail="Concurrent refresh detected, please re-authenticate"
        )

    result: dict = {
        "access_token": new_access_token,
        "expires_in": expires_in,
    }

    if source == "body":
        result["refresh_token"] = new_refresh_token

    response = JSONResponse(content=result)

    if source == "cookie":
        response.set_cookie(
            REFRESH_COOKIE,
            new_refresh_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=30 * 24 * 3600,  # 30 days
            path="/auth",
        )

    return response


@refresh_router.post("/revoke", response_class=JSONResponse)
async def revoke_session(request: Request, body: RevokeRequest | None = None):
    """Revoke a refresh-token session.

    Accepts the refresh token via cookie or body (same dual-source as refresh).
    Marks the session as revoked in the DB so the token can no longer be used.
    """
    session_store = getattr(request.app.state, "session_store", None)
    if not session_store:
        raise HTTPException(status_code=503, detail="Session management not available")

    cookie_token = request.cookies.get(REFRESH_COOKIE, "")
    body_token = body.refresh_token if body else ""
    token = cookie_token or body_token

    if not token:
        raise HTTPException(status_code=400, detail="No refresh token provided")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = await session_store.get_session_by_refresh_hash(token_hash)
    if not session:
        # Already revoked or expired — return success (idempotent)
        return JSONResponse(content={"ok": True})

    await session_store.revoke_session(session_id=session["id"], user_id=session["user_id"])

    response = JSONResponse(content={"ok": True})
    if cookie_token:
        response.delete_cookie(REFRESH_COOKIE, path="/auth")
    return response
