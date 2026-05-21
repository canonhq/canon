"""Profile API route for the Spec Explorer web app."""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth.deps import get_current_user, require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import (
    ALL_PERMISSION_VALUES,
    PERMISSION_DESCRIPTIONS,
    ROLE_PERMISSIONS,
    Permission,
    Role,
)
from .models import (
    AccountPatch,
    AccountResponse,
    AppearancePreferences,
    AppearancePreferencesPatch,
    LinkedAccountsResponse,
    LinkedGitHub,
    LinkedSlack,
    NotificationPreferences,
    NotificationPreferencesPatch,
    ProfileGitHubUser,
    ProfileResponse,
    ProfileSession,
    ProfileSessionsResponse,
    RevokeOthersResponse,
)

logger = logging.getLogger(__name__)

profile_router = APIRouter()


def _infer_role(permissions: frozenset[Permission]) -> str:
    """Infer the highest role whose permissions are a subset of the user's."""
    # Check from highest to lowest
    for role in (Role.ADMIN, Role.EDITOR, Role.VIEWER):
        if ROLE_PERMISSIONS[role] <= permissions:
            return role.value
    return "viewer"


@profile_router.get("/app/{org}/api/profile", response_model=ProfileResponse)
async def api_profile(
    request: Request,
    org: str,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> ProfileResponse:
    """Return the current user's profile information."""
    # Fetch last_login_at from user store if available
    last_login_at: str | None = None
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is not None and user.sub:
        try:
            db_user = await user_store.get_user_by_sub(user.sub)
            if db_user and db_user.get("last_login_at"):
                last_login_at = db_user["last_login_at"].isoformat()
        except Exception:
            logger.warning("Failed to fetch user from store", exc_info=True)

    # Get GitHub user from session
    github_user: ProfileGitHubUser | None = None
    if hasattr(request, "session"):
        gh = request.session.get("github_user")
        if gh:
            github_user = ProfileGitHubUser(
                login=gh.get("login", ""),
                name=gh.get("name", ""),
            )

    return ProfileResponse(
        sub=user.sub,
        email=user.email,
        name=user.name,
        picture=user.picture,
        org_login=user.org_login,
        org_id=user.org_id,
        permissions=sorted(p.value for p in user.permissions),
        all_permissions=sorted(ALL_PERMISSION_VALUES),
        permission_descriptions=PERMISSION_DESCRIPTIONS,
        auth_method=user.auth_method,
        github_user=github_user,
        last_login_at=last_login_at,
        inferred_role=_infer_role(user.permissions),
    )


#: Cookie name carrying the httpOnly refresh token. Note the cookie is set
#: with ``path="/auth"`` in ``auth.refresh_routes``, so a browser will *never*
#: send it to this `/app/{org}/api/profile/...` endpoint. ``sessions`` table
#: rows are currently only created by the CLI device-flow (`auth.device_routes`);
#: web OIDC sessions live in the Starlette session cookie and aren't tracked
#: there. That means in production the "Sessions" tab lists CLI logins, and
#: from any browser request there is no current row in the table to mark —
#: `_resolve_current_session_id` returns ``None`` and every row gets
#: ``is_current=False``. The cookie lookup below stays in place so any
#: future code path that *does* present the refresh cookie (e.g. an API
#: client calling these routes from the auth-scoped path) gets correct
#: `is_current` flagging without further changes.
_REFRESH_COOKIE = "sw_refresh"


async def _resolve_user_db_id(request: Request, sub: str) -> int | None:
    """Look up the database PK for the OIDC subject of the current request."""
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None or not sub:
        return None
    try:
        row = await user_store.get_user_by_sub(sub)
    except Exception:
        logger.warning("Failed to fetch user by sub", exc_info=True)
        return None
    if not row:
        return None
    return row.get("id")


async def _resolve_current_session_id(request: Request) -> str | None:
    """Resolve the session row id matching the request's refresh cookie if any.

    See the ``_REFRESH_COOKIE`` docstring for why this usually returns None
    from a browser-issued request.
    """
    cookie = request.cookies.get(_REFRESH_COOKIE, "")
    if not cookie:
        return None
    session_store = getattr(request.app.state, "session_store", None)
    if session_store is None:
        return None
    try:
        row = await session_store.get_session_by_refresh_hash(
            hashlib.sha256(cookie.encode()).hexdigest()
        )
    except Exception:
        logger.warning("Failed to resolve current session id", exc_info=True)
        return None
    return row.get("id") if row else None


async def _emit_profile_audit(
    request: Request,
    *,
    event_type: str,
    user: CurrentUser,
    resource_id: str | None = None,
    detail: dict | None = None,
) -> None:
    """Best-effort audit-log emission for self-service profile actions."""
    audit_store = getattr(request.app.state, "audit_store", None)
    if audit_store is None:
        return
    try:
        # Local import to avoid a circular dependency with admin.routes.
        from ..admin.routes import _client_ip
    except Exception:  # pragma: no cover
        _client_ip = lambda _r: None  # noqa: E731
    try:
        await audit_store.log(
            event_type=event_type,
            resource_type="user_session",
            resource_id=resource_id,
            actor_id=None,
            actor_sub=user.sub,
            org=user.org_login,
            detail=detail or {},
            ip_address=_client_ip(request),
        )
    except Exception:
        logger.warning("Failed to record audit event %s", event_type, exc_info=True)


def _serialize_session(row: dict, *, current_id: str | None) -> ProfileSession:
    return ProfileSession(
        id=str(row["id"]),
        device_label=row.get("device_label", "") or "",
        created_at=row["created_at"].isoformat(),
        last_used_at=row["last_used_at"].isoformat(),
        expires_at=row["expires_at"].isoformat(),
        is_current=current_id is not None and str(row["id"]) == current_id,
    )


@profile_router.get(
    "/app/{org}/api/profile/security/sessions",
    response_model=ProfileSessionsResponse,
)
async def list_security_sessions(
    request: Request,
    org: str,
    user: CurrentUser = Depends(get_current_user),
) -> ProfileSessionsResponse:
    """List the caller's active sessions in this org."""
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_store = getattr(request.app.state, "session_store", None)
    if session_store is None:
        raise HTTPException(status_code=503, detail="Session management not available")
    user_id = await _resolve_user_db_id(request, user.sub)
    if user_id is None:
        return ProfileSessionsResponse(sessions=[])
    rows = await session_store.list_sessions(user_id=user_id, org_login=org)
    current_id = await _resolve_current_session_id(request)
    return ProfileSessionsResponse(
        sessions=[_serialize_session(r, current_id=current_id) for r in rows]
    )


@profile_router.delete(
    "/app/{org}/api/profile/security/sessions/{session_id}",
    status_code=204,
)
async def revoke_security_session(
    request: Request,
    org: str,
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Revoke a single session belonging to the caller.

    Returns 404 (not 403) when the session id is not the caller's — collapsing
    the two cases keeps the endpoint from leaking session-id existence to
    other users.
    """
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_store = getattr(request.app.state, "session_store", None)
    if session_store is None:
        raise HTTPException(status_code=503, detail="Session management not available")
    user_id = await _resolve_user_db_id(request, user.sub)
    if user_id is None:
        raise HTTPException(status_code=404, detail="Session not found")
    revoked = await session_store.revoke_session(session_id=session_id, user_id=user_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Session not found")
    await _emit_profile_audit(
        request,
        event_type="profile.session.revoked",
        user=user,
        resource_id=session_id,
    )
    return Response(status_code=204)


@profile_router.post(
    "/app/{org}/api/profile/security/sessions/revoke-others",
    response_model=RevokeOthersResponse,
)
async def revoke_other_security_sessions(
    request: Request,
    org: str,
    user: CurrentUser = Depends(get_current_user),
) -> RevokeOthersResponse:
    """Revoke every session for the caller except the one making this request.

    Refuses with 409 when the request can't pin a "current" session row
    (no ``sw_refresh`` cookie). Without that pin we would silently revoke
    every row including the caller's own — possible foot-gun for any
    future API client. Browser callers don't live in the ``sessions``
    table at all (their session is the Starlette session cookie) and
    should revoke individual CLI rows via the DELETE endpoint instead.
    """
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_store = getattr(request.app.state, "session_store", None)
    if session_store is None:
        raise HTTPException(status_code=503, detail="Session management not available")
    user_id = await _resolve_user_db_id(request, user.sub)
    if user_id is None:
        return RevokeOthersResponse(revoked=0)
    current_id = await _resolve_current_session_id(request)
    if current_id is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot identify the current session. Revoke individual "
                "sessions from the list instead."
            ),
        )
    count = await session_store.revoke_all_sessions(user_id=user_id, except_session_id=current_id)
    await _emit_profile_audit(
        request,
        event_type="profile.session.revoked_all",
        user=user,
        detail={"revoked_count": count, "kept_session_id": current_id},
    )
    return RevokeOthersResponse(revoked=count)


@profile_router.post("/app/{org}/api/profile/security/password-reset")
async def request_self_password_reset(
    request: Request,
    org: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Trigger a password reset ticket for the caller's own identity.

    Wraps the same Auth0 Management API the admin endpoint
    (`/admin/users/{id}/password-reset`) calls, with the admin check removed
    and `user_id` pinned to ``user.sub``. Returns ``{email_sent: true}`` to
    the SPA; the ticket URL is only echoed back when ``environment ==
    "development"`` so QA can click through without an outbound email.
    """
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")

    provider = getattr(request.app.state, "oidc_provider", None)
    if provider is None or not hasattr(provider, "create_password_change_ticket"):
        raise HTTPException(
            status_code=501,
            detail=(
                "Self-serve password reset is not supported by this identity "
                "provider — use your IdP's password-reset flow directly."
            ),
        )

    if not user.sub:
        raise HTTPException(status_code=400, detail="Authenticated user has no oidc_sub")

    try:
        ticket = await provider.create_password_change_ticket(user_id=user.sub)
    except Exception as exc:
        # Forward only a generic message to the client. ``str(exc)`` on an
        # httpx.HTTPStatusError can carry the Auth0 response body and a
        # user-existence oracle ("The user does not exist."). Server-side
        # detail is captured via ``exc_info=True``.
        logger.warning("Self-serve password reset ticket failed", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Unable to send password reset email. Please try again later.",
        ) from exc

    await _emit_profile_audit(
        request,
        event_type="profile.password_reset",
        user=user,
        # Audit detail intentionally omits the ticket URL — it's a single-use
        # credential and rotates per request anyway.
        detail={"self_serve": True},
    )

    response: dict = {"email_sent": True}
    settings = request.app.state.settings
    if settings.environment == "development":
        ticket_url = ticket.get("ticket") if isinstance(ticket, dict) else None
        if ticket_url:
            response["ticket_url"] = ticket_url
    return response


_NOTIFICATION_FIELDS = (
    "slack_dm_enabled",
    "slack_dm_pr_comments",
    "slack_dm_spec_drift",
    "email_digest_cadence",
    "email_pr_comments",
)
_APPEARANCE_FIELDS = ("theme", "timezone", "relative_time")


async def _require_user_id_and_prefs(request: Request, user: CurrentUser) -> tuple[int, object]:
    """Common preamble for prefs routes — resolve user_id + prefs store or 401/503."""
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")
    prefs_store = getattr(request.app.state, "user_preferences_store", None)
    if prefs_store is None:
        raise HTTPException(status_code=503, detail="Preferences store not available")
    user_id = await _resolve_user_db_id(request, user.sub)
    if user_id is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user_id, prefs_store


def _validate_timezone(tz: str) -> None:
    """Reject obviously bogus IANA zone names so the DB never stores junk."""
    if tz == "":
        return
    try:
        from zoneinfo import ZoneInfo, available_timezones
    except Exception:  # pragma: no cover
        return
    if tz not in available_timezones():
        # Fall back to constructor to allow rare zones not in the enumerated
        # set (e.g. fresh tzdata entries); raises ZoneInfoNotFoundError on bad.
        try:
            ZoneInfo(tz)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Unknown timezone: {tz}") from exc


@profile_router.get("/app/{org}/api/profile/notifications", response_model=NotificationPreferences)
async def get_notifications(
    request: Request,
    org: str,
    user: CurrentUser = Depends(get_current_user),
) -> NotificationPreferences:
    user_id, prefs_store = await _require_user_id_and_prefs(request, user)
    row = await prefs_store.get(user_id=user_id, org_login=org)
    return NotificationPreferences(**{k: row[k] for k in _NOTIFICATION_FIELDS})


@profile_router.patch(
    "/app/{org}/api/profile/notifications", response_model=NotificationPreferences
)
async def update_notifications(
    request: Request,
    org: str,
    patch_body: NotificationPreferencesPatch,
    user: CurrentUser = Depends(get_current_user),
) -> NotificationPreferences:
    user_id, prefs_store = await _require_user_id_and_prefs(request, user)
    patch_dict = patch_body.model_dump(exclude_none=True)
    row = await prefs_store.update(user_id=user_id, org_login=org, patch=patch_dict)
    return NotificationPreferences(**{k: row[k] for k in _NOTIFICATION_FIELDS})


@profile_router.get("/app/{org}/api/profile/preferences", response_model=AppearancePreferences)
async def get_preferences(
    request: Request,
    org: str,
    user: CurrentUser = Depends(get_current_user),
) -> AppearancePreferences:
    user_id, prefs_store = await _require_user_id_and_prefs(request, user)
    row = await prefs_store.get(user_id=user_id, org_login=org)
    return AppearancePreferences(**{k: row[k] for k in _APPEARANCE_FIELDS})


@profile_router.patch("/app/{org}/api/profile/preferences", response_model=AppearancePreferences)
async def update_preferences(
    request: Request,
    org: str,
    patch_body: AppearancePreferencesPatch,
    user: CurrentUser = Depends(get_current_user),
) -> AppearancePreferences:
    user_id, prefs_store = await _require_user_id_and_prefs(request, user)
    if patch_body.timezone is not None:
        _validate_timezone(patch_body.timezone)
    patch_dict = patch_body.model_dump(exclude_none=True)
    row = await prefs_store.update(user_id=user_id, org_login=org, patch=patch_dict)
    return AppearancePreferences(**{k: row[k] for k in _APPEARANCE_FIELDS})


# --- User-scoped API keys (Profile → Security → API keys) -------------------

from datetime import UTC, datetime, timedelta  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402


class _CreateApiKeyBody(BaseModel):
    label: str = ""
    scopes: list[str] = Field(default_factory=list)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


def _serialize_api_key(row: dict) -> dict:
    out = dict(row)
    for field in ("created_at", "expires_at", "revoked_at", "last_used_at"):
        if out.get(field) is not None:
            out[field] = out[field].isoformat()
    return out


@profile_router.get("/app/{org}/api/profile/security/api-keys")
async def list_profile_api_keys(
    request: Request,
    org: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None:
        raise HTTPException(status_code=503, detail="API key store not available")
    user_id = await _resolve_user_db_id(request, user.sub)
    if user_id is None:
        return {"keys": []}
    keys = await user_store.list_api_keys(user_id=user_id, org_login=org)
    return {"keys": [_serialize_api_key(k) for k in keys]}


@profile_router.post("/app/{org}/api/profile/security/api-keys", status_code=201)
async def create_profile_api_key(
    request: Request,
    org: str,
    body: _CreateApiKeyBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None:
        raise HTTPException(status_code=503, detail="API key store not available")

    # Validate scopes against the known permission set; refuse any scope the
    # caller doesn't currently hold (privilege-escalation guard).
    for scope in body.scopes:
        if scope not in ALL_PERMISSION_VALUES:
            raise HTTPException(status_code=400, detail=f"Invalid scope: {scope}")
        if not user.has_permission(Permission(scope)):
            raise HTTPException(
                status_code=403,
                detail=f"Cannot grant scope you don't have: {scope}",
            )

    user_id = await _resolve_user_db_id(request, user.sub)
    if user_id is None:
        raise HTTPException(status_code=400, detail="User not found in database")

    scopes = body.scopes or [Permission.SPECS_READ.value]
    expires_at = (
        datetime.now(UTC) + timedelta(days=body.expires_in_days)
        if body.expires_in_days is not None
        else None
    )
    raw_key, record = await user_store.create_api_key(
        user_id=user_id,
        org_login=org,
        scopes=scopes,
        label=body.label,
        expires_at=expires_at,
    )
    await _emit_profile_audit(
        request,
        event_type="profile.api_key.created",
        user=user,
        resource_id=str(record["id"]),
        detail={"label": body.label, "scopes": scopes},
    )
    return {
        "key": raw_key,
        "id": record["id"],
        "label": record["label"],
        "scopes": record["scopes"],
        "expires_at": record["expires_at"].isoformat() if record["expires_at"] else None,
    }


@profile_router.delete("/app/{org}/api/profile/security/api-keys/{key_id}", status_code=204)
async def revoke_profile_api_key(
    request: Request,
    org: str,
    key_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None:
        raise HTTPException(status_code=503, detail="API key store not available")
    user_id = await _resolve_user_db_id(request, user.sub)
    if user_id is None:
        raise HTTPException(status_code=404, detail="API key not found")
    revoked = await user_store.revoke_api_key(key_id=key_id, user_id=user_id, org_login=org)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found")
    await _emit_profile_audit(
        request,
        event_type="profile.api_key.revoked",
        user=user,
        resource_id=str(key_id),
    )
    return Response(status_code=204)


# --- Account (editable identity) --------------------------------------------


def _account_response_from_user(user: CurrentUser, db_row: dict | None) -> AccountResponse:
    return AccountResponse(
        name=user.name or "",
        nickname=(db_row or {}).get("nickname", "") or "",
        picture=user.picture or "",
        email=user.email or "",
        email_verified=bool((db_row or {}).get("email_verified", True)),
    )


@profile_router.get("/app/{org}/api/profile/account", response_model=AccountResponse)
async def get_account(
    request: Request,
    org: str,
    user: CurrentUser = Depends(get_current_user),
) -> AccountResponse:
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_store = getattr(request.app.state, "user_store", None)
    row = None
    if user_store is not None and user.sub:
        try:
            row = await user_store.get_user_by_sub(user.sub)
        except Exception:
            logger.warning("Failed to fetch user from store", exc_info=True)
    return _account_response_from_user(user, row)


@profile_router.patch("/app/{org}/api/profile/account", response_model=AccountResponse)
async def update_account(
    request: Request,
    org: str,
    patch_body: AccountPatch,
    user: CurrentUser = Depends(get_current_user),
) -> AccountResponse:
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")

    if patch_body.picture and not patch_body.picture.startswith("https://"):
        raise HTTPException(status_code=422, detail="picture must be an https:// URL")

    provider = getattr(request.app.state, "oidc_provider", None)
    if provider is None or not hasattr(provider, "update_user"):
        raise HTTPException(
            status_code=501,
            detail="Profile editing is not supported by this identity provider",
        )

    patch_dict = patch_body.model_dump(exclude_none=True)
    if not patch_dict:
        # Empty patch — return current state without an upstream round-trip.
        return await get_account(request, org, user)  # type: ignore[arg-type]

    try:
        updated = await provider.update_user(user.sub, patch_dict)
    except Exception as exc:
        # Same anti-pattern as the password-reset 502 (see review feedback in
        # 5b79ada4): ``str(exc)`` on httpx.HTTPStatusError may carry the
        # Auth0 response body, including user-existence oracles.
        logger.warning("Provider update_user failed", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Unable to update profile. Please try again later.",
        ) from exc

    # Refresh the in-memory session so the next page render reflects the change
    # without forcing a re-login. Only safe for cookie-session auth.
    if hasattr(request, "session") and request.session.get("user"):
        session_user = request.session["user"]
        for key in ("name", "nickname", "picture"):
            if key in patch_dict:
                session_user[key] = patch_dict[key]
        request.session["user"] = session_user

    # Best-effort mirror to canon's `users` row (name/picture only — email is
    # T9's job since it requires verification before we trust it).
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is not None and user.sub:
        try:
            await user_store.upsert_user(
                oidc_sub=user.sub,
                email=user.email,
                name=patch_dict.get("name", user.name),
                picture=patch_dict.get("picture", user.picture),
            )
        except Exception:
            logger.warning("Failed to mirror account update to users table", exc_info=True)

    await _emit_profile_audit(
        request,
        event_type="profile.account.updated",
        user=user,
        detail={"fields": list(patch_dict.keys())},
    )

    return AccountResponse(
        name=patch_dict.get("name", user.name or ""),
        nickname=patch_dict.get("nickname", "") if "nickname" in patch_dict else "",
        picture=patch_dict.get("picture", user.picture or ""),
        email=user.email or "",
        email_verified=bool((updated or {}).get("email_verified", True)),
    )


# --- Linked accounts --------------------------------------------------------


@profile_router.get("/app/{org}/api/profile/linked", response_model=LinkedAccountsResponse)
async def get_linked_accounts(
    request: Request,
    org: str,
    user: CurrentUser = Depends(get_current_user),
) -> LinkedAccountsResponse:
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")

    github: LinkedGitHub | None = None
    if hasattr(request, "session"):
        gh = request.session.get("github_user")
        if gh and gh.get("login"):
            github = LinkedGitHub(login=gh.get("login", ""), name=gh.get("name", ""))

    slack: LinkedSlack | None = None
    if hasattr(request, "session"):
        sl = request.session.get("slack_user")
        if sl and sl.get("user_id"):
            slack = LinkedSlack(
                team_id=sl.get("team_id", ""),
                user_id=sl.get("user_id", ""),
                user_name=sl.get("user_name", ""),
            )

    # IdP connection is the prefix of the OIDC sub (`auth0|abc`, `github|123`,
    # `google-oauth2|…`). Pure best-effort — strings with no `|` mean unknown.
    idp_connection = ""
    if "|" in user.sub:
        idp_connection = user.sub.split("|", 1)[0]

    return LinkedAccountsResponse(github=github, slack=slack, idp_connection=idp_connection)


@profile_router.post("/app/{org}/api/profile/linked/slack/unlink", status_code=204)
async def unlink_slack(
    request: Request,
    org: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    if user.is_anonymous:
        raise HTTPException(status_code=401, detail="Authentication required")
    # Slack identity is stored in the request session today; clear it.
    if hasattr(request, "session"):
        request.session.pop("slack_user", None)

    # Disable downstream Slack DM dispatch for this user/org pair.
    prefs_store = getattr(request.app.state, "user_preferences_store", None)
    user_id = await _resolve_user_db_id(request, user.sub)
    if prefs_store is not None and user_id is not None:
        try:
            await prefs_store.update(
                user_id=user_id,
                org_login=org,
                patch={"slack_dm_enabled": False},
            )
        except Exception:
            logger.warning("Failed to disable slack_dm_enabled after unlink", exc_info=True)

    await _emit_profile_audit(
        request,
        event_type="profile.linked.slack_unlinked",
        user=user,
    )
    return Response(status_code=204)
