"""JWKS-based JWT validation for access tokens.

This module provides the shared JWT helpers used by both the auth middleware
(tenant isolation) and the FastAPI dependency layer (``get_current_user``).
Keeping them here avoids a circular import between ``middleware.py`` and
``deps.py``.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial

import jwt as pyjwt
from jwt import PyJWKClient

from ..settings import Settings

logger = logging.getLogger(__name__)

# Module-level JWKS client cache (per URI).
_jwks_clients: dict[str, PyJWKClient] = {}


def _get_jwks_client(jwks_uri: str) -> PyJWKClient:
    """Get or create a cached PyJWKClient for the given JWKS URI."""
    if jwks_uri not in _jwks_clients:
        _jwks_clients[jwks_uri] = PyJWKClient(jwks_uri, cache_keys=True, lifespan=300)
    return _jwks_clients[jwks_uri]


async def validate_access_token(token: str, settings: Settings, *, jwks_uri: str = "") -> dict:
    """Validate an OIDC access token and return its claims.

    Args:
        token: The raw JWT access token string.
        settings: Application settings (used to derive JWKS URI / audience when
            ``jwks_uri`` is not provided).
        jwks_uri: Optional override for the JWKS URI.  When provided, this is
            used directly instead of deriving from ``auth0_domain``.  Callers
            (e.g. ``deps.py``) can obtain this from ``provider.get_jwks_uri()``.

    Raises ``Exception`` on any validation failure.
    """
    # Determine JWKS URI
    if jwks_uri:
        resolved_jwks_uri = jwks_uri
        # Determine audience + issuer from settings
        audience = settings.oidc_audience or settings.auth0_audience
        # Derive issuer from oidc_issuer or auth0_domain.
        # Don't force a trailing slash — use the configured value as-is so it
        # matches the IDP's `iss` claim exactly.  Auth0 includes a trailing
        # slash; Keycloak, Okta, Zitadel, and Entra ID typically do not.
        if settings.oidc_issuer:
            issuer = settings.oidc_issuer
        elif settings.auth0_domain:
            issuer = f"https://{settings.auth0_domain}/"
        else:
            raise ValueError(
                "Cannot validate JWT: no issuer configured. Set OIDC_ISSUER or AUTH0_DOMAIN."
            )
    else:
        # Legacy path: derive from auth0_domain (backward compatibility)
        if not settings.auth0_domain or not settings.auth0_audience:
            raise ValueError("Auth0 domain and audience must be configured for JWT validation")
        resolved_jwks_uri = f"https://{settings.auth0_domain}/.well-known/jwks.json"
        audience = settings.auth0_audience
        issuer = f"https://{settings.auth0_domain}/"

    jwks_client = _get_jwks_client(resolved_jwks_uri)
    # JWKS fetch is synchronous (HTTP call on cache miss) — run in executor
    loop = asyncio.get_running_loop()
    signing_key = await loop.run_in_executor(
        None, partial(jwks_client.get_signing_key_from_jwt, token)
    )

    decode_kwargs: dict = {
        "algorithms": ["RS256", "ES256"],
    }
    if audience:
        decode_kwargs["audience"] = audience
    else:
        # Missing audience means any JWT from this issuer is accepted,
        # regardless of intended service — a confused deputy risk.
        raise ValueError(
            "JWT audience must be configured (OIDC_AUDIENCE or AUTH0_AUDIENCE). "
            "Without it, any JWT from the issuer would be accepted."
        )
    decode_kwargs["issuer"] = issuer

    claims = pyjwt.decode(
        token,
        signing_key.key,
        **decode_kwargs,
    )

    return claims


async def resolve_org_login(claims: dict, registry: object | None) -> str:
    """Resolve org_login from JWT claims and the installation registry.

    Strategies (in order):
    1. ``org_id`` claim → registry lookup (Auth0 Organizations flow)
    2. Single-org fallback → if the registry has exactly one active
       installation, use that org.  In Auth0 cloud mode this is safe because
       login is gated by the ``restrict_signups`` Action.  In generic OIDC
       mode, the operator must restrict access at the IDP level.

    Returns the org_login string, or ``""`` if resolution fails.
    """
    if not registry:
        return ""

    # Strategy 1: org_id claim (web auth with Auth0 Organizations)
    org_id = claims.get("org_id", "")
    if org_id:
        try:
            installation = await registry.get_installation_by_oidc_org(org_id)
            if installation:
                return installation.org_login
        except Exception:
            logger.debug("Failed to resolve org_id %s", org_id, exc_info=True)

    # Strategy 2: single-org fallback (device auth without org_id).
    # In generic OIDC mode, ensure IDP-level access control is configured —
    # any authenticated user gets mapped to the only org automatically.
    try:
        orgs = await registry.list_orgs()
        if len(orgs) == 1:
            logger.debug(
                "Single-org fallback: mapping authenticated user to %s",
                orgs[0],
            )
            return orgs[0]
    except Exception:
        logger.debug("Failed to list orgs for single-org fallback", exc_info=True)

    return ""


async def resolve_jwt_org(token: str, settings: Settings, registry, *, provider=None) -> str | None:
    """Validate a JWT and resolve its org_id to an org_login.

    Returns the ``org_login`` string, or ``None`` if the token is invalid
    or the org cannot be resolved.  This is the shared helper used by both
    the auth middleware and the dependency layer.
    """
    jwks_uri = ""
    if provider:
        try:
            jwks_uri = await provider.get_jwks_uri()
        except Exception:
            logger.warning("JWKS URI lookup failed — cannot validate JWT", exc_info=True)
            return None
    try:
        claims = await validate_access_token(token, settings, jwks_uri=jwks_uri)
    except Exception:
        logger.debug("JWT validation failed in resolve_jwt_org", exc_info=True)
        return None

    org_login = await resolve_org_login(claims, registry)
    return org_login or None
