"""Generic OIDC provider — discovery-based, works with any compliant IDP."""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlencode

import httpx

from ...settings import Settings
from .protocol import DeviceCodeResponse, OrgInfo, Pending, TokenSet

logger = logging.getLogger(__name__)


class GenericOIDCProvider:
    """Discovery-based OIDC provider for OSS bring-your-own-IDP deployments."""

    def __init__(self, *, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        if not settings.oidc_issuer:
            raise ValueError("oidc_issuer is required for GenericOIDCProvider")
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(timeout=30)
        self._issuer = settings.oidc_issuer.rstrip("/")
        self._client_id = settings.oidc_client_id
        self._client_secret = settings.oidc_client_secret
        self._audience = settings.oidc_audience
        self._scopes = settings.oidc_scopes
        # Discovered endpoints (populated lazily with TTL)
        self._discovered_at: float = 0.0
        self._discovery_ttl: float = 3600.0  # Re-fetch discovery doc every hour
        self._discovery_lock = asyncio.Lock()
        self._authorization_endpoint = ""
        self._token_endpoint = ""
        self._jwks_uri = ""
        self._end_session_endpoint: str | None = None
        self._device_authorization_endpoint: str | None = None
        self._userinfo_endpoint = ""

    async def _ensure_discovered(self) -> None:
        """Fetch and cache the discovery document (with TTL and concurrency guard)."""
        if self._discovered_at and (time.monotonic() - self._discovered_at) < self._discovery_ttl:
            return
        async with self._discovery_lock:
            # Double-check after acquiring lock
            if (
                self._discovered_at
                and (time.monotonic() - self._discovered_at) < self._discovery_ttl
            ):
                return
            url = f"{self._issuer}/.well-known/openid-configuration"
            try:
                resp = await self._http.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"OIDC discovery failed for {self._issuer}: HTTP {exc.response.status_code}"
                ) from exc
            doc = resp.json()
            # RFC 8414 §3.3: verify the returned issuer matches what we expected
            returned_issuer = doc.get("issuer", "").rstrip("/")
            if returned_issuer != self._issuer.rstrip("/"):
                raise ValueError(
                    f"OIDC discovery issuer mismatch: "
                    f"expected {self._issuer!r}, got {doc.get('issuer')!r}"
                )
            self._authorization_endpoint = doc["authorization_endpoint"]
            self._token_endpoint = doc["token_endpoint"]
            self._jwks_uri = doc["jwks_uri"]
            self._end_session_endpoint = doc.get("end_session_endpoint")
            self._device_authorization_endpoint = doc.get("device_authorization_endpoint")
            self._userinfo_endpoint = doc.get("userinfo_endpoint", "")
            self._discovered_at = time.monotonic()

    async def get_login_url(self, *, redirect_uri: str, state: str, org_hint: str = "") -> str:
        await self._ensure_discovered()
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": self._scopes,
            "state": state,
        }
        if self._audience:
            params["audience"] = self._audience
        return f"{self._authorization_endpoint}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> TokenSet:
        await self._ensure_discovered()
        resp = await self._http.post(
            self._token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        access_token = data.get("access_token")
        if not access_token:
            raise RuntimeError("Token exchange returned no access_token")
        return TokenSet(
            access_token=access_token,
            id_token=data.get("id_token", ""),
            refresh_token=data.get("refresh_token", ""),
            expires_in=data.get("expires_in", 0),
        )

    async def refresh_tokens(self, *, refresh_token: str) -> TokenSet:
        await self._ensure_discovered()
        resp = await self._http.post(
            self._token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        access_token = data.get("access_token")
        if not access_token:
            raise RuntimeError("Token refresh returned no access_token")
        return TokenSet(
            access_token=access_token,
            id_token=data.get("id_token", ""),
            refresh_token=data.get("refresh_token", refresh_token),
            expires_in=data.get("expires_in", 0),
        )

    async def get_jwks_uri(self) -> str:
        await self._ensure_discovered()
        return self._jwks_uri

    async def get_logout_url(self, *, return_to: str) -> str | None:
        await self._ensure_discovered()
        if not self._end_session_endpoint:
            return None
        params = urlencode(
            {
                "client_id": self._client_id,
                "post_logout_redirect_uri": return_to,
            }
        )
        return f"{self._end_session_endpoint}?{params}"

    async def get_device_code(
        self, *, audience: str = "", scope: str = ""
    ) -> DeviceCodeResponse | None:
        await self._ensure_discovered()
        if not self._device_authorization_endpoint:
            return None
        # RFC 8628: device authorization is typically used by public clients;
        # don't send client_secret to the device authorization endpoint as some
        # providers reject it.  The token endpoint (poll_device_token) does
        # authenticate the client.
        payload: dict = {
            "client_id": self._client_id,
            "scope": scope or self._scopes + " offline_access",
        }
        effective_audience = audience or self._audience
        if effective_audience:
            payload["audience"] = effective_audience
        resp = await self._http.post(self._device_authorization_endpoint, data=payload)
        if resp.status_code != 200:
            logger.warning(
                "OIDC device code request failed: status=%d body=%s",
                resp.status_code,
                resp.text[:500],
            )
            return None
        data = resp.json()
        return DeviceCodeResponse(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data.get("verification_uri", ""),
            verification_uri_complete=data.get("verification_uri_complete", ""),
            interval=data.get("interval", 5),
            expires_in=data.get("expires_in", 900),
        )

    async def poll_device_token(self, device_code: str) -> TokenSet | Pending:
        await self._ensure_discovered()
        resp = await self._http.post(
            self._token_endpoint,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "device_code": device_code,
            },
        )
        # Parse JSON safely — some proxies return HTML error pages
        content_type = resp.headers.get("content-type", "")
        if "application/json" not in content_type:
            raise RuntimeError(
                f"Device token endpoint returned unexpected content-type: {content_type} "
                f"(status={resp.status_code})"
            )
        data = resp.json()
        # RFC 8628 §3.5 specifies 400 for authorization_pending, but some
        # providers (e.g. Auth0) return 403.  Handle both.
        if resp.status_code in (400, 403):
            error = data.get("error", "")
            if error in ("authorization_pending", "slow_down"):
                return Pending(slow_down=error == "slow_down")
            raise RuntimeError(f"Device auth error: {error}")
        if resp.status_code != 200:
            raise RuntimeError(f"Device token request failed: {resp.status_code}")
        access_token = data.get("access_token")
        if not access_token:
            raise RuntimeError("Device token response missing access_token")
        return TokenSet(
            access_token=access_token,
            id_token=data.get("id_token", ""),
            refresh_token=data.get("refresh_token", ""),
            expires_in=data.get("expires_in", 0),
        )

    async def get_user_orgs(self, user_id: str) -> list[OrgInfo]:
        """Generic OIDC has no management API — always returns empty."""
        return []

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
