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
RESERVED_ORG_SLUGS = frozenset({"admin", "no-org", "choose-org"})


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

        return await call_next(request)
