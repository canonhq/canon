"""Device Authorization Grant endpoints for CLI authentication.

The CLI never holds client secrets.  These endpoints proxy the OIDC
Device Authorization flow server-side so the CLI only needs to display
a URL + user code and poll for completion.
"""

from __future__ import annotations

import binascii
import hashlib
import json
import logging
import uuid
from base64 import urlsafe_b64decode
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .jwt import resolve_org_login, validate_access_token
from .providers.protocol import Pending

logger = logging.getLogger(__name__)

device_router = APIRouter(prefix="/auth/device")


def _decode_id_token_claims(id_token: str) -> dict:
    """Return the payload claims from an ID token without signature verification.

    Safe here because ``poll_device_token`` receives the ID token directly from
    the provider's token endpoint over TLS — there is no untrusted intermediary
    that could substitute a forged token. The access token issued in the same
    exchange is separately JWKS-verified and remains the source of truth for
    ``sub`` and any authorization decisions; these claims are used only to
    populate user-profile fields (email / name).
    """
    if not id_token:
        return {}
    if id_token.count(".") != 2:
        logger.warning("Device auth: id_token has unexpected segment count")
        return {}
    try:
        payload = id_token.split(".", 2)[1]
        payload += "=" * (-len(payload) % 4)
        decoded = json.loads(urlsafe_b64decode(payload))
    except (ValueError, TypeError, LookupError, binascii.Error) as exc:
        logger.warning("Device auth: failed to decode id_token payload (%s)", exc, exc_info=True)
        return {}
    if not isinstance(decoded, dict):
        logger.warning(
            "Device auth: id_token payload is not a JSON object (type=%s)",
            type(decoded).__name__,
        )
        return {}
    return decoded


class DeviceCodeRequest(BaseModel):
    """Optional hints the CLI can send when starting device auth.

    This endpoint is unauthenticated, so the ``org`` field is bounded to
    prevent log flooding or unnecessary registry lookups from abusive
    callers. The pattern intentionally allows the full printable-slug
    alphabet (letters, digits, dot/underscore/hyphen) rather than just
    GitHub's stricter rules — the registry lookup handles the rest, and
    we don't want to reject legitimately-escaped slugs here.
    """

    org: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._-]*$")


class DeviceTokenRequest(BaseModel):
    device_code: str


@device_router.post("/code", response_class=JSONResponse)
async def request_device_code(request: Request, body: DeviceCodeRequest):
    """Start the device authorization flow by requesting a code from the provider."""
    provider = getattr(request.app.state, "oidc_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="Device auth not configured")

    settings = request.app.state.settings
    audience = settings.auth0_audience or settings.oidc_audience
    if not audience:
        logger.error(
            "No audience configured — device auth requires an API audience (AUTH0_AUDIENCE or OIDC_AUDIENCE)"
        )
        raise HTTPException(status_code=503, detail="Device auth not configured")

    # Resolve an optional org hint to its IDP organization id so the resulting
    # access token carries an ``org_id`` claim. An unknown slug (registry
    # returns ``None``) is non-fatal: unauthenticated device code issuance is
    # fine and org resolution falls back to the single-org heuristic at
    # token-exchange time. Operational errors (DB down, etc.) are *not*
    # swallowed here — they propagate to the outer handler as 502 so ops
    # actually finds out.
    organization_id = ""
    if body.org:
        registry = getattr(request.app.state, "registry", None)
        if registry is None:
            logger.warning(
                "Device auth: org hint %s supplied but registry unavailable — "
                "continuing without organization hint",
                body.org,
            )
        else:
            installation = await registry.get_installation_by_org(body.org)
            if installation and installation.oidc_org_id:
                organization_id = installation.oidc_org_id
            else:
                logger.warning(
                    "Device auth: no oidc_org_id for org=%s — continuing without organization hint",
                    body.org,
                )

    try:
        device_code_resp = await provider.get_device_code(
            audience=audience, organization=organization_id
        )
    except Exception as exc:
        logger.warning("Provider device/code failed", exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to start device auth") from exc

    if device_code_resp is None:
        raise HTTPException(status_code=501, detail="Device auth not supported by provider")

    return JSONResponse(
        content={
            "device_code": device_code_resp.device_code,
            "user_code": device_code_resp.user_code,
            "verification_uri": device_code_resp.verification_uri,
            "verification_uri_complete": device_code_resp.verification_uri_complete,
            "interval": device_code_resp.interval,
            "expires_in": device_code_resp.expires_in,
        }
    )


@device_router.post("/token", response_class=JSONResponse)
async def poll_device_token(request: Request, body: DeviceTokenRequest):
    """Poll the provider for the device token.  Returns status + tokens on approval."""
    provider = getattr(request.app.state, "oidc_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="Device auth not configured")

    try:
        result = await provider.poll_device_token(body.device_code)
    except RuntimeError as exc:
        error_str = str(exc)
        if "expired_token" in error_str:
            return JSONResponse(content={"status": "expired"})
        if "access_denied" in error_str:
            return JSONResponse(content={"status": "denied"})
        logger.warning("Provider device/token error: %s", exc)
        return JSONResponse(content={"status": "error", "detail": error_str})
    except Exception:
        logger.warning("Provider device/token failed", exc_info=True)
        return JSONResponse(
            content={"status": "error", "detail": "Token exchange failed"},
            status_code=502,
        )

    # Still pending — map Pending to appropriate response.
    # Include slow_down hint so CLI can back off its polling interval.
    if isinstance(result, Pending):
        return JSONResponse(content={"status": "pending", "slow_down": result.slow_down})

    # Token approved — validate, upsert user, create session
    settings = request.app.state.settings
    access_token = result.access_token
    id_token = result.id_token
    refresh_token = result.refresh_token
    expires_in = result.expires_in

    # Validate access token and extract claims
    try:
        jwks_uri = await provider.get_jwks_uri()
        claims = await validate_access_token(access_token, settings, jwks_uri=jwks_uri)
    except ValueError as exc:
        # Missing configuration (e.g. AUTH0_AUDIENCE)
        logger.error("Device auth: server misconfiguration: %s", exc)
        raise HTTPException(status_code=503, detail="Auth service misconfigured") from exc
    except Exception as exc:
        logger.warning("Device auth: access token validation failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Access token validation failed") from exc

    # Identity (``sub``) comes exclusively from the JWKS-validated access
    # token — we never derive identity from the unverified ID token payload.
    # The ID token is decoded only for PII fields (``email`` / ``name``),
    # which Auth0 omits from access tokens; generic OIDC providers that do
    # embed these in the access token are handled by the fallback chain.
    id_claims = _decode_id_token_claims(id_token)
    sub = claims.get("sub", "")
    email = (
        id_claims.get("email", "")
        or claims.get("email", "")
        or claims.get("https://canonhq.co/email", "")
        or claims.get("https://specwright.dev/email", "")
    )
    name = (
        id_claims.get("name", "")
        or claims.get("name", "")
        or claims.get("https://canonhq.co/name", "")
        or claims.get("https://specwright.dev/name", "")
    )

    # Refuse to mint a session when we can't identify the user. Returning a
    # "successful" response with empty sub/email would upsert a blank user
    # and silently corrupt the user table — much worse than a loud 500.
    if not sub or not email:
        logger.error(
            "Device auth: could not extract identity from token response "
            "(sub=%r, email_present=%s, id_token_present=%s)",
            sub,
            bool(email),
            bool(id_token),
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to extract user identity from token response",
        )

    # Resolve org
    registry = getattr(request.app.state, "registry", None)
    org_login = await resolve_org_login(claims, registry)

    # Upsert user + first-user bootstrap (mirrors web callback in routes.py)
    user_store = getattr(request.app.state, "user_store", None)
    user_record = None
    if user_store and sub:
        try:
            user_record = await user_store.upsert_user(
                oidc_sub=sub,
                email=email,
                name=name,
            )
            # First-user bootstrap: promote to admin so self-hosters using
            # `canon login` (CLI) as their first action get admin access.
            if user_record and user_record.get("is_new"):
                try:
                    promoted = await user_store.promote_first_user_to_admin(user_record["id"])
                    if promoted:
                        logger.info("First user %s promoted to admin (device flow)", email)
                except Exception:
                    logger.error(
                        "Failed to bootstrap first user %s as admin (device flow)",
                        email,
                        exc_info=True,
                    )
        except Exception:
            logger.warning("Device auth: failed to upsert user", exc_info=True)

    # Create session
    session_created = False
    session_store = getattr(request.app.state, "session_store", None)
    if session_store and user_record and refresh_token:
        refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        session_id = str(uuid.uuid4())
        try:
            await session_store.create_session(
                session_id=session_id,
                user_id=user_record["id"],
                org_login=org_login,
                device_label="cli",
                refresh_hash=refresh_hash,
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            session_created = True
        except Exception:
            logger.warning("Device auth: failed to create session", exc_info=True)

    return JSONResponse(
        content={
            "status": "approved",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "email": email,
            "org": org_login,
            "session_created": session_created,
        }
    )
