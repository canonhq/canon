"""API routes for managing user connections and org integrations."""

from __future__ import annotations

import json
import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..auth.deps import require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import Permission
from ..settings import Settings
from ..sync.jira_auth import refresh_jira_token
from .cache import TTLCache

logger = logging.getLogger(__name__)


def _check_org_ownership(user: CurrentUser, org: str) -> None:
    """Ensure the authenticated user belongs to the requested org."""
    if user.org_login != org:
        raise HTTPException(status_code=403, detail="Cannot access integrations for another org")


integration_router = APIRouter()

# Rate limit: 1 test per provider per minute. TTLCache auto-expires entries
# so this doesn't grow unboundedly. Still per-process, which is acceptable
# for a rate limit that's UX-protective rather than security-critical.
_test_rate_limit = TTLCache(ttl_seconds=60)


def _get_connection_store(request: Request):
    return getattr(request.app.state, "connection_store", None)


def _get_integration_store(request: Request):
    return getattr(request.app.state, "integration_store", None)


def _get_user_id_from_store(request: Request, user: CurrentUser) -> int | None:
    """Resolve the DB user ID from the session or user store."""
    # Check session first (set during login)
    if hasattr(request, "session"):
        uid = request.session.get("user_db_id")
        if uid:
            return int(uid)
    return None


# ─── User Connections ─────────────────────────────────────


@integration_router.get("/app/{org}/api/settings/connections")
async def list_connections(
    request: Request,
    org: str,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    """List the current user's VCS connections (no tokens)."""
    _check_org_ownership(user, org)
    store = _get_connection_store(request)
    if store is None:
        return JSONResponse({"connections": []})

    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None:
        return JSONResponse({"connections": []})

    db_user = await user_store.get_user_by_sub(user.sub)
    if not db_user:
        return JSONResponse({"connections": []})

    connections = await store.list_connections(db_user["id"])
    # Serialize datetimes to ISO strings
    for conn in connections:
        for key in ("connected_at", "updated_at", "token_expires_at"):
            if conn.get(key) is not None:
                conn[key] = conn[key].isoformat()
        # Convert UUID to string
        if conn.get("id"):
            conn["id"] = str(conn["id"])
    return JSONResponse({"connections": connections})


@integration_router.delete("/app/{org}/api/settings/connections/{provider}")
async def disconnect_provider(
    request: Request,
    org: str,
    provider: str,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    """Disconnect a VCS provider (delete connection + clear session)."""
    _check_org_ownership(user, org)
    store = _get_connection_store(request)
    if store is None:
        return JSONResponse({"ok": False, "error": "Database not configured"}, status_code=500)

    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None:
        return JSONResponse({"ok": False, "error": "Database not configured"}, status_code=500)

    db_user = await user_store.get_user_by_sub(user.sub)
    if not db_user:
        return JSONResponse({"ok": False, "error": "User not found"}, status_code=404)

    deleted = await store.delete_connection(db_user["id"], provider)

    # Also clear session data for backward compat
    if provider == "github" and hasattr(request, "session"):
        request.session.pop("github_user", None)

    return JSONResponse({"ok": deleted})


# ─── Org Integrations ─────────────────────────────────────


@integration_router.get("/app/{org}/api/settings/integrations")
async def list_integrations(
    request: Request,
    org: str,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    """List all org-level integrations (no decrypted credentials)."""
    _check_org_ownership(user, org)
    store = _get_integration_store(request)
    if store is None:
        return JSONResponse({"integrations": []})

    integrations = await store.list_integrations(org)
    for integ in integrations:
        for key in ("connected_at", "updated_at"):
            if integ.get(key) is not None:
                integ[key] = integ[key].isoformat()
        if integ.get("id"):
            integ["id"] = str(integ["id"])
    return JSONResponse({"integrations": integrations})


@integration_router.delete("/app/{org}/api/settings/integrations/{provider}")
async def disconnect_integration(
    request: Request,
    org: str,
    provider: str,
    user: CurrentUser = Depends(require_permission(Permission.ORG_MANAGE)),
) -> JSONResponse:
    """Disconnect an org-level integration (admin only).

    Also deregisters any auto-created webhooks with the provider.
    """
    _check_org_ownership(user, org)
    store = _get_integration_store(request)
    if store is None:
        return JSONResponse({"ok": False, "error": "Database not configured"}, status_code=500)

    # Attempt to deregister webhook before deleting credentials
    integration = await store.get_integration(org, provider)
    if integration:
        metadata = integration.get("provider_metadata", {})
        # Parse JSONB if it's a string
        if isinstance(metadata, str):
            import json

            metadata = json.loads(metadata)
        webhook_id = metadata.get("webhook_id")
        if webhook_id:
            config = await store.get_integration_config(org, provider)
            if config:
                await _deregister_webhook(provider, config, webhook_id)

    deleted = await store.delete_integration(org, provider)
    return JSONResponse({"ok": deleted})


async def _deregister_webhook(provider: str, config: dict, webhook_id: str) -> None:
    """Best-effort webhook deregistration on disconnect."""
    try:
        if provider == "jira":
            from ..sync.webhook_registration import deregister_jira_webhook

            await deregister_jira_webhook(
                cloud_id=config.get("cloud_id", ""),
                access_token=config.get("access_token", ""),
                webhook_id=webhook_id,
            )
        elif provider == "linear":
            from ..sync.webhook_registration import deregister_linear_webhook

            await deregister_linear_webhook(
                access_token=config.get("access_token", ""),
                webhook_id=webhook_id,
            )
    except Exception:
        logger.warning("Failed to deregister %s webhook %s (non-fatal)", provider, webhook_id)


@integration_router.get("/app/{org}/api/settings/integrations/summary")
async def integration_summary(
    request: Request,
    org: str,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    """Get integration status summary for the dashboard."""
    _check_org_ownership(user, org)
    store = _get_integration_store(request)
    if store is None:
        return JSONResponse({"total": 0, "connected": 0, "needs_attention": 0})

    summary = await store.get_summary(org)
    return JSONResponse(summary)


# ─── Health Checks ─────────────────────────────────────────


@integration_router.post("/app/{org}/api/settings/integrations/{provider}/test")
async def test_integration(
    request: Request,
    org: str,
    provider: str,
    user: CurrentUser = Depends(require_permission(Permission.ORG_MANAGE)),
) -> JSONResponse:
    """Test an integration connection by calling the provider's API."""
    _check_org_ownership(user, org)
    # Rate limit: 1 test per provider per minute (TTLCache auto-expires)
    rate_key = f"test:{org}:{provider}"
    if _test_rate_limit.get(rate_key):
        return JSONResponse(
            {"ok": False, "message": "Rate limited — try again in a minute", "latency_ms": 0},
            status_code=429,
        )

    store = _get_integration_store(request)
    if store is None:
        return JSONResponse(
            {"ok": False, "message": "Database not configured", "latency_ms": 0}, status_code=500
        )

    config = await store.get_integration_config(org, provider)
    if config is None:
        return JSONResponse(
            {"ok": False, "message": f"No {provider} integration configured", "latency_ms": 0},
            status_code=404,
        )

    start = time.monotonic()
    try:
        if provider == "jira":
            ok, msg = await _test_jira(config, store=store, org=org)
        elif provider == "linear":
            ok, msg = await _test_linear(config)
        else:
            ok, msg = False, f"Health check not implemented for {provider}"
    except Exception as exc:
        ok, msg = False, str(exc)

    latency_ms = round((time.monotonic() - start) * 1000)

    # Set rate limit after test completes (so failed requests don't consume quota)
    _test_rate_limit.set(rate_key, True)

    # Update status based on result
    if not ok:
        await store.update_status(org, provider, "error")
    elif (await store.get_integration(org, provider) or {}).get("status") != "active":
        await store.update_status(org, provider, "active")

    return JSONResponse({"ok": ok, "message": msg, "latency_ms": latency_ms})


async def _jira_myself(cloud_id: str, access_token: str) -> httpx.Response:
    """Call Jira /rest/api/3/myself to verify credentials."""
    async with httpx.AsyncClient(timeout=10) as client:
        return await client.get(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )


def _parse_metadata(raw) -> dict:
    """Ensure provider_metadata is a dict (may be stored as JSON string)."""
    if isinstance(raw, str):
        return json.loads(raw)
    return raw if isinstance(raw, dict) else {}


async def _test_jira(config: dict, *, store=None, org: str = "") -> tuple[bool, str]:
    """Test Jira connection by calling /rest/api/3/myself.

    If the initial call returns 401, re-reads config from the store (in case
    the cron just refreshed), then attempts a token refresh and retries.
    Tokens are only persisted after the retry succeeds.
    """
    cloud_id = config.get("cloud_id", "")
    access_token = config.get("access_token", "")
    if not cloud_id or not access_token:
        return False, "Missing cloud_id or access_token"

    resp = await _jira_myself(cloud_id, access_token)

    if resp.status_code == 401:
        # Re-read config from store — the cron may have refreshed tokens already
        if store and org:
            fresh_config = await store.get_integration_config(org, "jira")
            if fresh_config and fresh_config.get("access_token") != access_token:
                logger.info("Using cron-refreshed token for org %s", org)
                access_token = fresh_config["access_token"]
                config = fresh_config
                resp = await _jira_myself(cloud_id, access_token)
                if resp.status_code != 401:
                    resp.raise_for_status()
                    data = resp.json()
                    return (
                        True,
                        f"Connected as {data.get('displayName', data.get('emailAddress', 'unknown'))}",
                    )

        # Still 401 — attempt our own token refresh
        settings = Settings()
        rt = config.get("refresh_token", "")
        if not rt or not settings.jira_oauth_client_id:
            return False, "Authentication failed — token expired and no refresh credentials"

        refreshed = await refresh_jira_token(
            refresh_token=rt,
            client_id=settings.jira_oauth_client_id,
            client_secret=settings.jira_oauth_client_secret,
        )
        if refreshed is None:
            return False, "Authentication failed — token expired and refresh failed"

        new_access = refreshed.get("access_token", "")
        new_refresh = refreshed.get("refresh_token", rt)
        if not new_access:
            return False, "Authentication failed — refresh response missing access_token"

        # Retry with the refreshed token
        resp = await _jira_myself(cloud_id, new_access)
        if resp.status_code == 401:
            return False, "Authentication failed — token expired even after refresh"

        # Persist tokens immediately — the Atlassian exchange succeeded and
        # the old refresh token may have been rotated. A transient Jira error
        # (500, 429) doesn't invalidate the tokens; losing them here would
        # require manual re-auth. If this DB write fails, let the exception
        # propagate — the integration is effectively broken (rotated refresh
        # token lost) and should show "error" to prompt re-auth.
        if store and org:
            new_config = {**config, "access_token": new_access, "refresh_token": new_refresh}
            existing = await store.get_integration(org, "jira")
            metadata = _parse_metadata(existing.get("provider_metadata", {})) if existing else {}
            metadata["token_refreshed_at"] = time.time()
            await store.update_config(org, "jira", config=new_config, provider_metadata=metadata)
            logger.info("Jira token refreshed during test for org %s", org)

        # Now validate the /myself response for the test result
        resp.raise_for_status()
        data = resp.json()
        return (
            True,
            f"Connected as {data.get('displayName', data.get('emailAddress', 'unknown'))}",
        )

    resp.raise_for_status()
    data = resp.json()
    return True, f"Connected as {data.get('displayName', data.get('emailAddress', 'unknown'))}"


async def _test_linear(config: dict) -> tuple[bool, str]:
    """Test Linear connection by querying the viewer."""
    access_token = config.get("access_token", "")
    if not access_token:
        return False, "Missing access_token"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://api.linear.app/graphql",
            json={"query": "{ viewer { id name } }"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code == 401:
        return False, "Authentication failed — token may be invalid"
    resp.raise_for_status()
    data = resp.json()
    viewer = data.get("data", {}).get("viewer", {})
    return True, f"Connected as {viewer.get('name', 'unknown')}"
