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
async def github_login(request: Request, redirect_to: str | None = None):
    """Redirect to GitHub OAuth authorize page."""
    oauth_client = _get_oauth_client(request)
    if oauth_client is None:
        return RedirectResponse(url="/app", status_code=302)

    state = secrets.token_urlsafe(32)
    request.session["github_oauth_state"] = state
    if (
        redirect_to
        and redirect_to.startswith("/")
        and not redirect_to.startswith("//")
        and "\\" not in redirect_to
    ):
        request.session["github_oauth_redirect"] = redirect_to
    redirect_uri = str(request.url_for("github_callback"))
    url = oauth_client.authorize_url(redirect_uri, state=state)
    return RedirectResponse(url=url, status_code=302)


@github_auth_router.get("/callback", name="github_callback")
async def github_callback(request: Request):
    """Handle GitHub OAuth callback — exchange code for token, persist to DB."""
    oauth_client = _get_oauth_client(request)
    if oauth_client is None:
        return RedirectResponse(url="/app", status_code=302)

    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    redirect_to = request.session.pop("github_oauth_redirect", None)

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
        github_login_name = user_data.get("login", "")
        github_user_id = str(user_data.get("id", ""))

        # Set session for backward compat with editor
        request.session["github_user"] = {
            "login": github_login_name,
            "name": user_data.get("name", ""),
            "email": user_data.get("email", ""),
            "avatar_url": user_data.get("avatar_url", ""),
            "token": access_token,
        }

        # Persist to DB if connection store is available
        connection_store = getattr(request.app.state, "connection_store", None)
        user_store = getattr(request.app.state, "user_store", None)
        if connection_store and user_store:
            session_user = request.session.get("user", {})
            oidc_sub = session_user.get("sub", "")
            if oidc_sub:
                db_user = await user_store.get_user_by_sub(oidc_sub)
                if db_user:
                    scopes = (
                        token_data.get("scope", "").split(",") if token_data.get("scope") else []
                    )
                    await connection_store.upsert_connection(
                        user_id=db_user["id"],
                        provider="github",
                        provider_user_id=github_user_id,
                        provider_login=github_login_name,
                        access_token=access_token,
                        refresh_token=token_data.get("refresh_token"),
                        scopes=scopes,
                    )
                    logger.info("Persisted GitHub connection for user %s", oidc_sub)
    except Exception:
        logger.exception("GitHub OAuth callback failed")
        return RedirectResponse(url="/app?auth_error=github", status_code=302)

    # Redirect to the original page or default
    return RedirectResponse(url=redirect_to or "/app", status_code=302)


@github_auth_router.get("/disconnect")
async def github_disconnect(request: Request):
    """Clear GitHub session data and DB connection."""
    request.session.pop("github_user", None)

    # Also remove from DB if available
    connection_store = getattr(request.app.state, "connection_store", None)
    user_store = getattr(request.app.state, "user_store", None)
    if connection_store and user_store:
        session_user = request.session.get("user", {})
        oidc_sub = session_user.get("sub", "")
        if oidc_sub:
            db_user = await user_store.get_user_by_sub(oidc_sub)
            if db_user:
                await connection_store.delete_connection(db_user["id"], "github")

    return RedirectResponse(url="/app", status_code=302)
