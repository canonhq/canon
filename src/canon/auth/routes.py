"""Auth routes: login, callback, logout."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from canon import analytics

from .jwt import validate_access_token
from .oauth import oauth
from .permissions import ALL_PERMISSION_VALUES, ROLE_PERMISSIONS, Role

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/auth")

_ALLOWED_CONNECTIONS: frozenset[str] = frozenset({"github", "google-oauth2", "email"})


def _get_authlib_client(settings):
    """Return the correct authlib client object based on configured provider."""
    if settings.auth0_enabled and (not settings.auth_provider or settings.auth_provider == "auth0"):
        client = getattr(oauth, "auth0", None)
    else:
        client = getattr(oauth, "oidc", None)
    if client is None:
        raise RuntimeError(
            "No OIDC client registered — check auth provider settings "
            "(AUTH0_DOMAIN/CLIENT_ID or OIDC_ISSUER/CLIENT_ID)"
        )
    return client


@auth_router.get("/login")
async def login(request: Request, org: str = "", connection: str = ""):
    """Redirect to the OIDC provider's Universal Login.

    If ``?org=<slug>`` is provided and Auth0 Organizations mode is enabled,
    the user authenticates into that specific org so the returned token
    contains ``org_id`` and ``permissions`` claims.
    """
    settings = request.app.state.settings
    if not settings.auth_enabled:
        return RedirectResponse(url="/")

    redirect_uri = str(request.url_for("auth_callback"))
    kwargs: dict = {}

    # Store the requested org as a redirect hint (always, regardless of orgs mode)
    if org:
        request.session["login_org"] = org

    if org and settings.auth0_orgs_enabled:
        # Resolve org slug → OIDC org_id via the installation registry
        registry = getattr(request.app.state, "registry", None)
        oidc_org_id = ""
        if registry:
            try:
                installation = await registry.get_installation_by_org(org)
                if installation and installation.oidc_org_id:
                    oidc_org_id = installation.oidc_org_id
            except Exception:
                logger.debug("Failed to resolve org %s to OIDC org_id", org, exc_info=True)

        if oidc_org_id:
            kwargs["organization"] = oidc_org_id

    # `connection` is an Auth0-specific parameter — don't pass it for generic OIDC
    if connection and connection in _ALLOWED_CONNECTIONS and settings.auth0_enabled:
        kwargs["connection"] = connection

    authlib_client = _get_authlib_client(settings)
    return await authlib_client.authorize_redirect(request, redirect_uri, **kwargs)


@auth_router.get("/callback", name="auth_callback")
async def callback(request: Request):
    """Handle OIDC callback — exchange code for tokens, set session."""
    settings = request.app.state.settings
    if not settings.auth_enabled:
        return RedirectResponse(url="/")

    # Provider may return an error instead of an authorization code
    error = request.query_params.get("error")
    if error:
        error_desc = request.query_params.get("error_description", "")
        logger.warning("Auth callback error: %s — %s", error, error_desc)
        return RedirectResponse(url="/auth/login")

    authlib_client = _get_authlib_client(settings)
    token = await authlib_client.authorize_access_token(request)
    userinfo = token.get("userinfo", {})

    org_id = ""
    org_login = ""
    permissions: list[str] = []

    # Extract permissions (and optionally org) from the access token.
    # RBAC permissions require auth0_audience (or oidc_audience) to be set so
    # the provider returns a JWT access token instead of an opaque one.
    # Organizations (org_id) are an independent Auth0 feature — only extracted
    # when present in claims.
    audience = settings.auth0_audience or settings.oidc_audience
    if audience:
        access_token_claims: dict = {}
        raw_access_token = token.get("access_token", "")
        if raw_access_token:
            try:
                # Use provider JWKS URI when available for provider-agnostic validation
                provider = getattr(request.app.state, "oidc_provider", None)
                jwks_uri = ""
                if provider:
                    jwks_uri = await provider.get_jwks_uri()
                access_token_claims = await validate_access_token(
                    raw_access_token, settings, jwks_uri=jwks_uri
                )
            except Exception as exc:
                logger.warning(
                    "Access token verification failed — permissions not extracted",
                    exc_info=True,
                )
                analytics.capture_exception(exc, properties={"context": "auth_callback"})

        permissions = access_token_claims.get("permissions", [])

        # Org extraction — only present when Auth0 Organizations are used
        org_id = access_token_claims.get("org_id", "")
        if org_id:
            registry = getattr(request.app.state, "registry", None)
            if registry:
                try:
                    installation = await registry.get_installation_by_oidc_org(org_id)
                    if installation:
                        org_login = installation.org_login
                except Exception:
                    logger.debug("Failed to resolve org_id %s", org_id, exc_info=True)

    # Fallback: use login_org from session if we couldn't resolve from token
    if not org_login:
        org_login = request.session.pop("login_org", "")

    # Upsert user in DB
    is_new_user = False
    user_store = getattr(request.app.state, "user_store", None)
    if user_store and userinfo.get("sub"):
        try:
            user_record = await user_store.upsert_user(
                oidc_sub=userinfo["sub"],
                email=userinfo.get("email", ""),
                name=userinfo.get("name", ""),
                picture=userinfo.get("picture", ""),
            )
            is_new_user = user_record.get("is_new", False)
        except Exception:
            logger.error("Failed to upsert user sub=%s", userinfo.get("sub", ""), exc_info=True)
            return RedirectResponse(url="/auth/login?error=user_creation_failed")

        # First-user bootstrap: atomically promote the very first user to admin.
        # Uses a single UPDATE ... WHERE NOT EXISTS to avoid TOCTOU races
        # when two users sign up simultaneously.
        if is_new_user:
            try:
                promoted = await user_store.promote_first_user_to_admin(user_record["id"])
                if promoted:
                    logger.info("First user %s promoted to admin", userinfo.get("email", ""))
            except Exception:
                logger.error(
                    "Failed to bootstrap first user %s as admin",
                    userinfo.get("email", ""),
                    exc_info=True,
                )

    # If no JWT-based permissions (e.g. single-tenant without audience),
    # resolve from DB role so sessions don't fall back to read-only.
    if not permissions and user_store and userinfo.get("sub"):
        try:
            user_record_for_role = await user_store.get_user_by_sub(userinfo["sub"])
            if user_record_for_role:
                role_str = user_record_for_role.get("role", "viewer")
                try:
                    role = Role(role_str)
                except ValueError:
                    role = Role.VIEWER
                role_perms = ROLE_PERMISSIONS.get(role, frozenset())
                permissions = [p.value for p in role_perms if p.value in ALL_PERMISSION_VALUES]
        except Exception:
            logger.warning("Failed to resolve DB role for session permissions", exc_info=True)

    request.session["user"] = {
        "sub": userinfo.get("sub", ""),
        "email": userinfo.get("email", ""),
        "name": userinfo.get("name", ""),
        "picture": userinfo.get("picture", ""),
        "org_id": org_id,
        "org_login": org_login,
        "permissions": permissions,
    }

    # Fetch org memberships for multi-tenant dropdown filtering via provider.
    # Cross-references provider orgs with the installation registry so the
    # dropdown only shows orgs the user actually belongs to.
    provider = getattr(request.app.state, "oidc_provider", None)
    user_sub = userinfo.get("sub")
    if provider and user_sub:
        try:
            provider_orgs = await provider.get_user_orgs(user_sub)
            registry = getattr(request.app.state, "registry", None)
            if registry and provider_orgs:
                results = await asyncio.gather(
                    *(registry.get_installation_by_oidc_org(o.id) for o in provider_orgs),
                    return_exceptions=True,
                )
                org_logins = [
                    inst.org_login
                    for inst in results
                    if inst is not None and not isinstance(inst, Exception)
                ]
                if org_logins:
                    request.session["user"]["org_memberships"] = org_logins
        except Exception:
            logger.warning("Failed to fetch provider org memberships", exc_info=True)

    # Auth0-specific: if Auth0 passed the GitHub identity via custom claim, populate the
    # github_user session so the editor works immediately (no second OAuth).
    github_claim = userinfo.get("https://canonhq.co/github") or userinfo.get(
        "https://specwright.dev/github"
    )
    if isinstance(github_claim, dict) and github_claim.get("token"):
        request.session["github_user"] = {
            "login": github_claim.get("login", ""),
            "name": github_claim.get("name", ""),
            "email": userinfo.get("email", ""),
            "avatar_url": github_claim.get("avatar_url", ""),
            "token": github_claim["token"],
        }

    # Use OIDC sub (opaque, stable) as distinct_id to avoid sending PII to PostHog.
    # identify() links the sub to email/name for display in the PostHog UI.
    oidc_sub = userinfo.get("sub", "")
    if oidc_sub:
        analytics.identify(
            oidc_sub,
            {
                "email": userinfo.get("email", ""),
                "name": userinfo.get("name", ""),
                "org": org_login,
            },
        )
    analytics.track(
        "user_logged_in",
        distinct_id=oidc_sub or analytics.SERVER_ACTOR,
        properties={"is_new_user": is_new_user, "org": org_login},
        groups={"organization": org_login} if org_login else None,
    )

    # Redirect to the org dashboard if we know which org
    if org_login:
        if is_new_user:
            return RedirectResponse(url=f"/app/{org_login}/welcome")
        return RedirectResponse(url=f"/app/{org_login}/")
    return RedirectResponse(url="/app")


@auth_router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to provider logout."""
    request.session.pop("user", None)
    request.session.pop("github_user", None)
    return_url = str(request.base_url)

    # Use provider logout URL when available
    provider = getattr(request.app.state, "oidc_provider", None)
    if provider:
        try:
            logout_url = await provider.get_logout_url(return_to=return_url)
            if logout_url:
                return RedirectResponse(logout_url)
        except Exception:
            logger.error(
                "Failed to get provider logout URL — IDP session may still be active",
                exc_info=True,
            )
            # Local session is cleared but IDP session persists.
            # Redirect to home with a query param so the frontend can warn the user.
            return RedirectResponse(url="/?partial_logout=1")

    # Fallback: local-only session clear (no provider or provider has no logout endpoint)
    return RedirectResponse(url="/")
