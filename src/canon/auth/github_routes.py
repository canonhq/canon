"""GitHub OAuth routes for web editor authentication."""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

github_auth_router = APIRouter(prefix="/auth/github")


def _get_oauth_client(request: Request):
    """Get the GitHubOAuthClient from app state."""
    return getattr(request.app.state, "github_oauth_client", None)


@github_auth_router.get("/login")
async def github_login(request: Request):
    """Redirect to GitHub OAuth authorize page."""
    oauth_client = _get_oauth_client(request)
    if oauth_client is None:
        return RedirectResponse(url="/app", status_code=302)

    state = secrets.token_urlsafe(32)
    request.session["github_oauth_state"] = state
    redirect_uri = str(request.url_for("github_callback"))
    url = oauth_client.authorize_url(redirect_uri, state=state)
    return RedirectResponse(url=url, status_code=302)


@github_auth_router.get("/callback", name="github_callback")
async def github_callback(request: Request):
    """Handle GitHub OAuth callback — exchange code for token."""
    oauth_client = _get_oauth_client(request)
    if oauth_client is None:
        return RedirectResponse(url="/app", status_code=302)

    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")

    # Validate state
    expected_state = request.session.pop("github_oauth_state", "")
    if not state or state != expected_state:
        logger.warning("GitHub OAuth state mismatch")
        return RedirectResponse(url="/app?auth_error=state_mismatch", status_code=302)

    try:
        redirect_uri = str(request.url_for("github_callback"))
        token_data = await oauth_client.exchange_code(code, redirect_uri)
        access_token = token_data.get("access_token", "")

        if not access_token:
            logger.warning("GitHub OAuth: no access_token in response")
            return RedirectResponse(url="/app?auth_error=no_token", status_code=302)

        user_data = await oauth_client.get_user(access_token)
        request.session["github_user"] = {
            "login": user_data.get("login", ""),
            "name": user_data.get("name", ""),
            "email": user_data.get("email", ""),
            "avatar_url": user_data.get("avatar_url", ""),
            "token": access_token,
        }
    except Exception:
        logger.exception("GitHub OAuth callback failed")
        return RedirectResponse(url="/app?auth_error=github", status_code=302)

    return RedirectResponse(url="/app", status_code=302)


@github_auth_router.get("/disconnect")
async def github_disconnect(request: Request):
    """Clear GitHub session data."""
    request.session.pop("github_user", None)
    return RedirectResponse(url="/app", status_code=302)
