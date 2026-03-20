"""OIDC provider protocol — defines the interface all auth providers implement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TokenSet:
    """Tokens returned from code exchange or refresh."""

    access_token: str
    id_token: str = ""
    refresh_token: str = ""
    expires_in: int = 0


@dataclass(frozen=True)
class DeviceCodeResponse:
    """Response from starting a device authorization flow."""

    device_code: str
    user_code: str
    verification_uri: str = ""
    verification_uri_complete: str = ""
    interval: int = 5
    expires_in: int = 900


@dataclass(frozen=True)
class OrgInfo:
    """Organization membership info from a management API."""

    id: str
    name: str = ""
    display_name: str = ""


@dataclass(frozen=True)
class Pending:
    """Sentinel returned by poll_device_token when authorization is still pending.

    When ``slow_down`` is True (RFC 8628 ``slow_down`` error), the client
    should increase its polling interval.
    """

    slow_down: bool = False


@runtime_checkable
class OIDCProvider(Protocol):
    """Minimal interface for any OIDC-compliant auth provider."""

    async def get_login_url(self, *, redirect_uri: str, state: str, org_hint: str = "") -> str: ...

    async def exchange_code(self, *, code: str, redirect_uri: str) -> TokenSet: ...

    async def refresh_tokens(self, *, refresh_token: str) -> TokenSet: ...

    async def get_jwks_uri(self) -> str: ...

    async def get_logout_url(self, *, return_to: str) -> str | None: ...

    async def get_device_code(
        self, *, audience: str = "", scope: str = ""
    ) -> DeviceCodeResponse | None: ...

    async def poll_device_token(self, device_code: str) -> TokenSet | Pending: ...

    async def get_user_orgs(self, user_id: str) -> list[OrgInfo]: ...

    async def aclose(self) -> None: ...
