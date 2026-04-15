"""OAuth routes for third-party integrations (Jira Cloud, Linear)."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..auth.deps import require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import Permission
from ..sync.webhook_registration import register_jira_webhook, register_linear_webhook


def _check_org_ownership(user: CurrentUser, org: str) -> None:
    """Ensure the authenticated user belongs to the requested org."""
    if user.org_login != org:
        raise HTTPException(status_code=403, detail="Cannot configure integrations for another org")


logger = logging.getLogger(__name__)

oauth_integration_router = APIRouter()

# ─── Jira Cloud OAuth 2.0 (3LO) ─────────────────────────

JIRA_AUTH_URL = "https://auth.atlassian.com/authorize"
JIRA_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
JIRA_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"


@oauth_integration_router.get("/app/{org}/api/settings/integrations/jira/connect")
async def jira_connect(
    request: Request,
    org: str,
    user: CurrentUser = Depends(require_permission(Permission.ORG_MANAGE)),
):
    """Initiate Jira Cloud OAuth 2.0 3LO flow."""
    _check_org_ownership(user, org)
    settings = request.app.state.settings
    client_id = settings.jira_oauth_client_id
    if not client_id:
        return RedirectResponse(
            url=f"/app/{org}/settings/integrations?error=jira_not_configured",
            status_code=302,
        )

    state = secrets.token_urlsafe(32)
    request.session["jira_oauth_state"] = state
    request.session["jira_oauth_org"] = org

    callback_url = str(request.url_for("jira_oauth_callback"))
    params = {
        "audience": "api.atlassian.com",
        "client_id": client_id,
        "scope": "read:jira-work write:jira-work read:me offline_access",
        "redirect_uri": callback_url,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    return RedirectResponse(url=f"{JIRA_AUTH_URL}?{urlencode(params)}", status_code=302)


@oauth_integration_router.get("/auth/integrations/jira/callback", name="jira_oauth_callback")
async def jira_callback(request: Request):
    """Handle Jira OAuth callback — exchange code for tokens."""
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    expected_state = request.session.pop("jira_oauth_state", "")
    org = request.session.pop("jira_oauth_org", "")

    if not state or state != expected_state:
        logger.warning("Jira OAuth state mismatch")
        return RedirectResponse(
            url=f"/app/{org}/settings/integrations?error=state_mismatch", status_code=302
        )

    settings = request.app.state.settings
    callback_url = str(request.url_for("jira_oauth_callback"))

    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for tokens
            token_resp = await client.post(
                JIRA_TOKEN_URL,
                json={
                    "grant_type": "authorization_code",
                    "client_id": settings.jira_oauth_client_id,
                    "client_secret": settings.jira_oauth_client_secret,
                    "code": code,
                    "redirect_uri": callback_url,
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

            access_token = token_data["access_token"]
            refresh_token = token_data.get("refresh_token", "")

            # Fetch accessible resources (cloud sites)
            resources_resp = await client.get(
                JIRA_RESOURCES_URL,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            resources_resp.raise_for_status()
            resources = resources_resp.json()

        if not resources:
            return RedirectResponse(
                url=f"/app/{org}/settings/integrations?error=jira_no_sites",
                status_code=302,
            )

        # Use the first accessible resource
        site = resources[0]
        cloud_id = site["id"]
        site_url = site.get("url", "")
        site_name = site.get("name", site_url)

        # Store encrypted config
        integration_store = getattr(request.app.state, "integration_store", None)
        if integration_store is None:
            return RedirectResponse(
                url=f"/app/{org}/settings/integrations?error=db_not_configured",
                status_code=302,
            )

        # Resolve connected_by user ID
        connected_by = None
        user_store = getattr(request.app.state, "user_store", None)
        session_user = request.session.get("user", {})
        if user_store and session_user.get("sub"):
            db_user = await user_store.get_user_by_sub(session_user["sub"])
            if db_user:
                connected_by = db_user["id"]

        # Auto-register webhook for reverse sync.
        # Jira webhook signature verification uses settings.jira_webhook_secret
        # (env var) — Jira's dynamic webhook API doesn't support client-provided
        # signing secrets, so we only store the webhook_id for cleanup.
        webhook_id = ""
        canon_base_url = settings.canon_base_url
        if canon_base_url:
            try:
                wh_result = await register_jira_webhook(
                    cloud_id=cloud_id,
                    access_token=access_token,
                    base_url=canon_base_url,
                )
                webhook_id = wh_result.get("webhook_id", "")
            except Exception:
                logger.warning("Jira webhook auto-registration failed (non-fatal)", exc_info=True)

        # Non-sensitive metadata only — webhook_id for cleanup on disconnect
        metadata = {
            "site_name": site_name,
            "cloud_id": cloud_id,
            "site_url": site_url,
            "webhook_id": webhook_id,
        }

        config_data: dict[str, str] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "cloud_id": cloud_id,
            "site_url": site_url,
        }

        await integration_store.upsert_integration(
            org_login=org,
            provider="jira",
            display_name=site_name,
            config=config_data,
            provider_metadata=metadata,
            connected_by=connected_by,
        )
        logger.info("Jira OAuth completed for org %s, site %s", org, site_name)

    except Exception:
        logger.exception("Jira OAuth callback failed")
        return RedirectResponse(
            url=f"/app/{org}/settings/integrations?error=jira_oauth_failed",
            status_code=302,
        )

    return RedirectResponse(url=f"/app/{org}/settings/integrations?connected=jira", status_code=302)


# ─── Linear OAuth 2.0 ────────────────────────────────────

LINEAR_AUTH_URL = "https://linear.app/oauth/authorize"
LINEAR_TOKEN_URL = "https://api.linear.app/oauth/token"
LINEAR_API_URL = "https://api.linear.app/graphql"


@oauth_integration_router.get("/app/{org}/api/settings/integrations/linear/connect")
async def linear_connect(
    request: Request,
    org: str,
    user: CurrentUser = Depends(require_permission(Permission.ORG_MANAGE)),
):
    """Initiate Linear OAuth 2.0 flow."""
    _check_org_ownership(user, org)
    settings = request.app.state.settings
    client_id = settings.linear_oauth_client_id
    if not client_id:
        return RedirectResponse(
            url=f"/app/{org}/settings/integrations?error=linear_not_configured",
            status_code=302,
        )

    state = secrets.token_urlsafe(32)
    request.session["linear_oauth_state"] = state
    request.session["linear_oauth_org"] = org

    callback_url = str(request.url_for("linear_oauth_callback"))
    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "state": state,
        "response_type": "code",
        "scope": "read,write,issues:create",
    }
    return RedirectResponse(url=f"{LINEAR_AUTH_URL}?{urlencode(params)}", status_code=302)


@oauth_integration_router.get("/auth/integrations/linear/callback", name="linear_oauth_callback")
async def linear_callback(request: Request):
    """Handle Linear OAuth callback — exchange code for token."""
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    expected_state = request.session.pop("linear_oauth_state", "")
    org = request.session.pop("linear_oauth_org", "")

    if not state or state != expected_state:
        logger.warning("Linear OAuth state mismatch")
        return RedirectResponse(
            url=f"/app/{org}/settings/integrations?error=state_mismatch", status_code=302
        )

    settings = request.app.state.settings
    callback_url = str(request.url_for("linear_oauth_callback"))

    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for token
            token_resp = await client.post(
                LINEAR_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.linear_oauth_client_id,
                    "client_secret": settings.linear_oauth_client_secret,
                    "code": code,
                    "redirect_uri": callback_url,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data["access_token"]

            # Fetch workspace info
            gql_resp = await client.post(
                LINEAR_API_URL,
                json={"query": "{ viewer { organization { id name } } }"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
            gql_resp.raise_for_status()
            gql_data = gql_resp.json()

        org_data = gql_data.get("data", {}).get("viewer", {}).get("organization", {})
        workspace_id = org_data.get("id", "")
        workspace_name = org_data.get("name", "Linear Workspace")

        # Store encrypted config
        integration_store = getattr(request.app.state, "integration_store", None)
        if integration_store is None:
            return RedirectResponse(
                url=f"/app/{org}/settings/integrations?error=db_not_configured",
                status_code=302,
            )

        connected_by = None
        user_store = getattr(request.app.state, "user_store", None)
        session_user = request.session.get("user", {})
        if user_store and session_user.get("sub"):
            db_user = await user_store.get_user_by_sub(session_user["sub"])
            if db_user:
                connected_by = db_user["id"]

        # Auto-register webhook for reverse sync
        webhook_id = ""
        webhook_secret = ""
        canon_base_url = settings.canon_base_url
        if canon_base_url:
            try:
                wh_result = await register_linear_webhook(
                    access_token=access_token,
                    base_url=canon_base_url,
                )
                webhook_id = wh_result.get("webhook_id", "")
                webhook_secret = wh_result.get("webhook_secret", "")
            except Exception:
                logger.warning("Linear webhook auto-registration failed (non-fatal)", exc_info=True)

        # Non-sensitive metadata only — webhook_id for cleanup on disconnect
        metadata = {
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "webhook_id": webhook_id,
        }

        # Sensitive credentials in encrypted config — includes webhook_secret
        config_data: dict[str, str] = {
            "access_token": access_token,
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
        }
        if webhook_secret:
            config_data["webhook_secret"] = webhook_secret

        await integration_store.upsert_integration(
            org_login=org,
            provider="linear",
            display_name=workspace_name,
            config=config_data,
            provider_metadata=metadata,
            connected_by=connected_by,
        )
        logger.info("Linear OAuth completed for org %s, workspace %s", org, workspace_name)

    except Exception:
        logger.exception("Linear OAuth callback failed")
        return RedirectResponse(
            url=f"/app/{org}/settings/integrations?error=linear_oauth_failed",
            status_code=302,
        )

    return RedirectResponse(
        url=f"/app/{org}/settings/integrations?connected=linear", status_code=302
    )
