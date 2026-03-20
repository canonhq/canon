"""Device Authorization Grant endpoints for CLI authentication.

The CLI never holds client secrets.  These endpoints proxy the OIDC
Device Authorization flow server-side so the CLI only needs to display
a URL + user code and poll for completion.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .jwt import resolve_org_login, validate_access_token
from .providers.protocol import Pending

logger = logging.getLogger(__name__)

device_router = APIRouter(prefix="/auth/device")


class DeviceCodeRequest(BaseModel):
    """Optional hints the CLI can send when starting device auth."""

    org: str = ""


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

    try:
        device_code_resp = await provider.get_device_code(audience=audience)
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

    sub = claims.get("sub", "")
    email = (
        claims.get("email", "")
        or claims.get("https://canonhq.co/email", "")
        or claims.get("https://specwright.dev/email", "")
    )
    name = (
        claims.get("name", "")
        or claims.get("https://canonhq.co/name", "")
        or claims.get("https://specwright.dev/name", "")
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
