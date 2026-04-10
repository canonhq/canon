"""FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import HTTPException, Request

from canon import analytics

from .jwt import resolve_org_login, validate_access_token
from .models import ANONYMOUS_USER, CurrentUser, PermissionDenied
from .permissions import ALL_PERMISSION_VALUES, ROLE_PERMISSIONS, Permission, Role

logger = logging.getLogger(__name__)


async def get_current_user(request: Request) -> CurrentUser:
    """Resolve the current user from session, API key, or anonymous.

    Priority:
    1. Authorization: Bearer header (API key hash lookup or JWT)
    2. Session cookie (OIDC provider)
    3. Anonymous (dev mode — all permissions when auth is disabled)
    """
    settings = request.app.state.settings

    # 1. Check Authorization header (API key)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        # API key format: sw_<base64url>
        if token.startswith("sw_"):
            return await _resolve_api_key(request, token)
        # JWT (OIDC access token)
        return await _resolve_jwt(request, token)

    # 2. Session cookie
    session_user = request.session.get("user") if hasattr(request, "session") else None
    if session_user:
        # Check if user has been deactivated since their session was created.
        # Fail open on DB errors so a pool hiccup doesn't 500 every request.
        user_store = getattr(request.app.state, "user_store", None)
        if user_store is not None:
            sub = session_user.get("sub", "")
            if sub:
                try:
                    db_user = await user_store.get_user_by_sub(sub)
                except (OSError, TimeoutError):
                    db_user = None
                if db_user and db_user.get("status") == "deactivated":
                    analytics.track("auth_denied", properties={"reason": "deactivated_user"})
                    raise HTTPException(status_code=403, detail="Account has been deactivated")
        return _session_to_current_user(session_user)

    # 3. Anonymous — grant all permissions when auth is disabled
    if not settings.auth_enabled:
        return ANONYMOUS_USER

    analytics.track("auth_denied", properties={"reason": "unauthenticated"})
    raise HTTPException(status_code=401, detail="Authentication required")


def _session_to_current_user(session_user: dict) -> CurrentUser:
    """Convert a session dict into a CurrentUser."""
    # Parse permissions from session (set during callback)
    raw_perms = session_user.get("permissions", [])
    permissions = frozenset(Permission(p) for p in raw_perms if p in ALL_PERMISSION_VALUES)
    # Fallback: if no permissions stored yet (pre-migration sessions or RBAC
    # not fully wired), grant read-only.  Users can re-login to acquire write
    # permissions via JWT claims or DB role lookup.
    if not permissions and session_user.get("sub"):
        logger.warning(
            "Session for sub=%s has no stored permissions — granting read-only. "
            "Configure OIDC_AUDIENCE for JWT-based RBAC or assign DB roles for write access.",
            session_user.get("sub", ""),
        )
        permissions = frozenset({Permission.SPECS_READ})

    return CurrentUser(
        sub=session_user.get("sub", ""),
        email=session_user.get("email", ""),
        name=session_user.get("name", ""),
        picture=session_user.get("picture", ""),
        org_id=session_user.get("org_id", ""),
        org_login=session_user.get("org_login", ""),
        permissions=permissions,
        auth_method="session",
    )


async def _resolve_api_key(request: Request, token: str) -> CurrentUser:
    """Look up an API key by its SHA-256 hash and build a CurrentUser."""
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None:
        analytics.track("auth_denied", properties={"reason": "api_key_unavailable"})
        raise HTTPException(status_code=401, detail="API key auth not available")

    # Reuse the lookup from middleware if available (avoids a second DB hit)
    api_key = getattr(request.state, "_resolved_api_key", None)
    if api_key is None:
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        api_key = await user_store.get_api_key_by_hash(key_hash)
    if api_key is None:
        analytics.track("auth_denied", properties={"reason": "invalid_api_key"})
        raise HTTPException(status_code=401, detail="Invalid API key")

    if api_key.get("revoked_at") is not None:
        analytics.track("auth_denied", properties={"reason": "revoked_api_key"})
        raise HTTPException(status_code=401, detail="API key has been revoked")

    # Check expiry
    expires_at = api_key.get("expires_at")
    if expires_at is not None and expires_at < datetime.now(UTC):
        analytics.track("auth_denied", properties={"reason": "expired_api_key"})
        raise HTTPException(status_code=401, detail="API key has expired")

    if api_key.get("user_status") == "deactivated":
        raise HTTPException(status_code=403, detail="Account has been deactivated")

    scopes = api_key.get("scopes", [])
    permissions = frozenset(Permission(s) for s in scopes if s in ALL_PERMISSION_VALUES)

    return CurrentUser(
        sub=api_key.get("user_sub", ""),
        email=api_key.get("user_email", ""),
        name=api_key.get("user_name", ""),
        org_id="",
        org_login=api_key.get("org_login", ""),
        permissions=permissions,
        auth_method="api_key",
    )


async def _resolve_permissions(request: Request, claims: dict, sub: str) -> frozenset[Permission]:
    """Resolve permissions for a user based on configuration.

    When ``auth0_orgs_enabled`` is True (multi-tenant cloud), permissions come
    from JWT claims (existing behavior).  When it is False (single-tenant OSS),
    look up ``users.role`` from DB and map via ``ROLE_PERMISSIONS``.
    """
    settings = request.app.state.settings

    if settings.auth0_orgs_enabled:
        # Multi-tenant cloud: permissions from JWT claims
        raw_perms = claims.get("permissions", [])
        return frozenset(Permission(p) for p in raw_perms if p in ALL_PERMISSION_VALUES)

    # Single-tenant OSS: map DB role → permissions
    user_store = getattr(request.app.state, "user_store", None)
    if user_store and sub:
        try:
            user_record = await user_store.get_user_by_sub(sub)
        except (OSError, TimeoutError) as exc:
            # Network/DB connectivity errors — fail visibly rather than
            # silently downgrading permissions (confused deputy risk).
            logger.error("DB lookup failed for sub=%s: %s", sub, exc, exc_info=True)
            raise HTTPException(
                status_code=503, detail="Permission lookup temporarily unavailable"
            ) from exc
        if user_record:
            role_str = user_record.get("role", "viewer")
            try:
                role = Role(role_str)
            except ValueError:
                logger.warning("Unknown role %r for sub=%s — defaulting to viewer", role_str, sub)
                role = Role.VIEWER
            return ROLE_PERMISSIONS.get(role, frozenset())

    # Fallback: read-only (no user_store or user not found in DB)
    return frozenset({Permission.SPECS_READ})


async def _resolve_jwt(request: Request, token: str) -> CurrentUser:
    """Validate a JWT access token and build a CurrentUser."""
    try:
        settings = request.app.state.settings
        # Use provider JWKS URI when available — do NOT fall back to legacy
        # path on failure, as that could validate against the wrong JWKS.
        provider = getattr(request.app.state, "oidc_provider", None)
        jwks_uri = ""
        if provider:
            jwks_uri = await provider.get_jwks_uri()
        claims = await validate_access_token(token, settings, jwks_uri=jwks_uri)
    except Exception as exc:
        logger.debug("JWT validation failed", exc_info=True)
        analytics.capture_exception(exc, properties={"context": "jwt_validation"})
        analytics.track("auth_denied", properties={"reason": "invalid_jwt"})
        raise HTTPException(status_code=401, detail="Invalid access token") from None

    sub = claims.get("sub", "")

    # Check if user has been deactivated since the JWT was issued
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is not None and sub:
        try:
            db_user = await user_store.get_user_by_sub(sub)
        except (OSError, TimeoutError):
            db_user = None  # registry errors: defer to _resolve_permissions which handles these
        if db_user and db_user.get("status") == "deactivated":
            analytics.track("auth_denied", properties={"reason": "deactivated_user"})
            raise HTTPException(status_code=403, detail="Account has been deactivated")

    permissions = await _resolve_permissions(request, claims, sub)

    org_id = claims.get("org_id", "")
    registry = getattr(request.app.state, "registry", None)
    org_login = await resolve_org_login(claims, registry)

    return CurrentUser(
        sub=sub,
        email=claims.get("email", ""),
        name=claims.get("name", ""),
        org_id=org_id,
        org_login=org_login,
        permissions=permissions,
        auth_method="jwt",
    )


def require_permission(perm: Permission) -> Callable:
    """Factory for a FastAPI dependency that enforces a permission.

    Usage::

        @router.get("/admin")
        async def admin(user: CurrentUser = Depends(require_permission(Permission.SPECS_ADMIN))):
            ...
    """

    async def _check(request: Request) -> CurrentUser:
        user = await get_current_user(request)
        try:
            user.require_permission(perm)
        except PermissionDenied as exc:
            analytics.track(
                "auth_denied",
                distinct_id=user.sub or analytics.SERVER_ACTOR,
                properties={"reason": "permission_denied", "permission": perm.value},
            )
            raise HTTPException(status_code=403, detail=str(exc)) from None
        return user

    return _check
