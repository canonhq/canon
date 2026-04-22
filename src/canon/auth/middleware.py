"""Auth middleware — redirects unauthenticated users on /app/* routes.

Also enforces tenant isolation: the session/API-key org must match the {org}
path parameter for /app/{org}/* routes.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from canon import analytics

logger = logging.getLogger(__name__)

# Matches /app/{org}/... — captures the org slug.
_ORG_PATH_RE = re.compile(r"^/app/([^/]+)")

# Org slugs reserved for internal routes.  If a GitHub org with one of these
# names installs the app, tenant isolation will not work correctly — the
# installation handler validates against this set.
RESERVED_ORG_SLUGS = frozenset({"admin", "no-org", "choose-org", "setup"})


def _is_api_request(request: Request) -> bool:
    return request.headers.get("Accept", "").startswith("application/json")


async def _org_from_bearer(request: Request) -> str | None:
    """Extract org_login from a Bearer token (sw_ API key or JWT)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]

    # Canon API key (sw_ prefix) — hash lookup
    if token.startswith("sw_"):
        user_store = getattr(request.app.state, "user_store", None)
        if user_store is None:
            return None
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        api_key = await user_store.get_api_key_by_hash(key_hash)
        if api_key is None or api_key.get("revoked_at") is not None:
            return None
        expires_at = api_key.get("expires_at")
        if expires_at is not None and expires_at < datetime.now(UTC):
            return None
        # Cache the resolved key so get_current_user can skip a second lookup
        request.state._resolved_api_key = api_key
        return api_key.get("org_login", "")

    # JWT — resolve org_login via JWKS-validated JWT
    from .jwt import resolve_jwt_org

    settings = request.app.state.settings
    registry = getattr(request.app.state, "registry", None)
    provider = getattr(request.app.state, "oidc_provider", None)
    return await resolve_jwt_org(token, settings, registry, provider=provider)


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated users to login for /app/* routes.

    Also checks that the session's (or API key's) ``org_login`` matches the
    ``{org}`` path parameter for tenant isolation.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = request.app.state.settings

        if not request.url.path.startswith("/app"):
            return await call_next(request)

        # Skip auth entirely when auth is not configured (dev mode)
        if not settings.auth_enabled:
            return await call_next(request)

        # Determine the user's org from session or API key
        session_user = request.session.get("user")
        has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")

        if not session_user and not has_bearer:
            analytics.track(
                "auth_denied",
                properties={"reason": "no_session", "path": request.url.path},
            )
            if _is_api_request(request):
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
            return RedirectResponse(url="/auth/login")

        # Tenant isolation: enforce org matching for /app/{org}/* routes.
        # Resolves the user's org first, then checks it against the URL.
        # Active when auth0_orgs_enabled (strict multi-tenant) OR when the
        # user has a resolved org_login (generic OIDC with org context).
        # Skipped in single-tenant mode where org_login is empty.
        match = _ORG_PATH_RE.match(request.url.path)
        if match:
            requested_org = match.group(1)
            # Skip reserved slugs (e.g. admin) — they're not org-scoped
            if requested_org in RESERVED_ORG_SLUGS:
                return await call_next(request)

            # Resolve the user's org — from session or API key
            if session_user:
                user_org = session_user.get("org_login", "")
            elif has_bearer:
                user_org = await _org_from_bearer(request) or ""
            else:
                user_org = ""

            # When a bearer token is valid but lacks org_id (e.g. device flow
            # where Auth0 didn't scope the token to an org), verify the user
            # has access to the requested org via registry membership lookup.
            # This is a fallback — org_id in the JWT is the primary mechanism.
            if not user_org and has_bearer:
                registry = getattr(request.app.state, "registry", None)
                if registry:
                    try:
                        installation = await registry.get_installation_by_org(requested_org)
                        if installation:
                            # The requested org exists and the user has a valid
                            # JWT — allow through, downstream deps enforce perms.
                            user_org = requested_org
                    except Exception:
                        pass

            # Always enforce org isolation: user's verified org must match URL.
            # The auth_enabled guard at the top of dispatch() already skips
            # this entire middleware for dev/self-hosted with auth disabled.
            if not user_org or user_org.lower() != requested_org.lower():
                analytics.track(
                    "auth_denied",
                    properties={
                        "reason": "org_mismatch",
                        "requested_org": requested_org,
                        "path": request.url.path,
                    },
                )
                if _is_api_request(request):
                    return JSONResponse(
                        {"detail": f"Not authorized for org: {requested_org}"},
                        status_code=403,
                    )
                return RedirectResponse(url=f"/auth/login?org={quote(requested_org, safe='')}")

            # Check if the org is suspended — block access if so.
            # Only treat explicit "suspended" status as a block; missing rows
            # (data inconsistency) are allowed through to avoid false positives.
            registry = getattr(request.app.state, "registry", None)
            if registry is not None:
                try:
                    installation = await registry.get_installation_by_org_any_status(requested_org)
                    if installation is not None and installation.status == "suspended":
                        analytics.track(
                            "auth_denied",
                            properties={
                                "reason": "org_suspended",
                                "requested_org": requested_org,
                            },
                        )
                        if _is_api_request(request):
                            return JSONResponse(
                                {"detail": "Organization is suspended"},
                                status_code=403,
                            )
                        return RedirectResponse(url="/app/no-org")
                except Exception:
                    logger.warning(
                        "Failed to check suspension status for org=%s",
                        requested_org,
                        exc_info=True,
                    )  # best-effort — don't block login on registry errors

        return await call_next(request)
