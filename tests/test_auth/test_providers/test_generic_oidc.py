"""Tests for generic OIDC provider (discovery-based)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from canon.auth.providers.generic_oidc import GenericOIDCProvider
from canon.auth.providers.protocol import (
    DeviceCodeResponse,
    OIDCProvider,
    Pending,
    TokenSet,
)
from canon.settings import Settings

_DISCOVERY_DOC = {
    "issuer": "https://idp.example.com",
    "authorization_endpoint": "https://idp.example.com/authorize",
    "token_endpoint": "https://idp.example.com/token",
    "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
    "end_session_endpoint": "https://idp.example.com/logout",
    "device_authorization_endpoint": "https://idp.example.com/device/authorize",
    "userinfo_endpoint": "https://idp.example.com/userinfo",
}


def _settings(**overrides) -> Settings:
    defaults = dict(
        oidc_issuer="https://idp.example.com",
        oidc_client_id="client-id",
        oidc_client_secret="client-secret",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _mock_discovery_http() -> AsyncMock:
    """Create a mock httpx client that serves the discovery document."""
    http = AsyncMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _DISCOVERY_DOC
    resp.raise_for_status = MagicMock()
    http.get = AsyncMock(return_value=resp)
    return http


class TestImplementsProtocol:
    def test_implements_oidc_provider(self):
        provider = GenericOIDCProvider(settings=_settings())
        assert isinstance(provider, OIDCProvider)


class TestDiscovery:
    async def test_fetches_discovery_document(self):
        http = _mock_discovery_http()
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        await provider._ensure_discovered()
        http.get.assert_awaited_once()
        assert "openid-configuration" in http.get.call_args[0][0]

    async def test_rejects_issuer_mismatch(self):
        """RFC 8414 §3.3: discovery issuer must match configured issuer."""
        http = AsyncMock()
        resp = MagicMock()
        resp.status_code = 200
        mismatched_doc = {**_DISCOVERY_DOC, "issuer": "https://evil.example.com"}
        resp.json.return_value = mismatched_doc
        resp.raise_for_status = MagicMock()
        http.get = AsyncMock(return_value=resp)
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        with pytest.raises(ValueError, match="issuer mismatch"):
            await provider._ensure_discovered()


class TestGetLoginUrl:
    async def test_returns_authorization_url(self):
        http = _mock_discovery_http()
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        url = await provider.get_login_url(
            redirect_uri="https://example.com/callback",
            state="abc",
        )
        assert "idp.example.com/authorize" in url
        assert "client-id" in url
        assert "state=abc" in url


class TestExchangeCode:
    async def test_returns_token_set(self):
        http = _mock_discovery_http()
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {
            "access_token": "at",
            "id_token": "it",
            "refresh_token": "rt",
            "expires_in": 3600,
        }
        token_resp.raise_for_status = MagicMock()
        # First call is discovery, second is token exchange
        http.get = AsyncMock(
            side_effect=[
                MagicMock(
                    status_code=200,
                    json=MagicMock(return_value=_DISCOVERY_DOC),
                    raise_for_status=MagicMock(),
                ),
            ]
        )
        http.post = AsyncMock(return_value=token_resp)
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        result = await provider.exchange_code(code="code", redirect_uri="https://example.com/cb")
        assert isinstance(result, TokenSet)
        assert result.access_token == "at"


class TestGetJwksUri:
    async def test_returns_discovered_jwks_uri(self):
        http = _mock_discovery_http()
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        uri = await provider.get_jwks_uri()
        assert uri == "https://idp.example.com/.well-known/jwks.json"


class TestGetLogoutUrl:
    async def test_returns_end_session_endpoint(self):
        http = _mock_discovery_http()
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        url = await provider.get_logout_url(return_to="https://example.com")
        assert "idp.example.com/logout" in url

    async def test_returns_none_when_no_end_session(self):
        http = AsyncMock()
        discovery_no_logout = {**_DISCOVERY_DOC}
        del discovery_no_logout["end_session_endpoint"]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = discovery_no_logout
        resp.raise_for_status = MagicMock()
        http.get = AsyncMock(return_value=resp)
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        url = await provider.get_logout_url(return_to="https://example.com")
        assert url is None


class TestDeviceCode:
    async def test_returns_device_code_response(self):
        http = _mock_discovery_http()
        device_resp = MagicMock()
        device_resp.status_code = 200
        device_resp.json.return_value = {
            "device_code": "dc",
            "user_code": "UC",
            "verification_uri": "https://idp.example.com/activate",
            "interval": 5,
            "expires_in": 600,
        }
        http.post = AsyncMock(return_value=device_resp)
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        result = await provider.get_device_code()
        assert isinstance(result, DeviceCodeResponse)
        # Default call must not include the Auth0 ``organization`` extension.
        posted = http.post.call_args
        assert "organization" not in posted.kwargs["data"]

    async def test_forwards_organization_when_provided(self):
        """Organization hint is threaded into the POST body as an Auth0 extension."""
        http = _mock_discovery_http()
        device_resp = MagicMock()
        device_resp.status_code = 200
        device_resp.json.return_value = {
            "device_code": "dc",
            "user_code": "UC",
            "verification_uri": "https://idp.example.com/activate",
            "interval": 5,
            "expires_in": 600,
        }
        http.post = AsyncMock(return_value=device_resp)
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)

        await provider.get_device_code(organization="org_abc123")

        posted = http.post.call_args
        assert posted.kwargs["data"]["organization"] == "org_abc123"

    async def test_returns_none_when_no_device_endpoint(self):
        http = AsyncMock()
        discovery_no_device = {**_DISCOVERY_DOC}
        del discovery_no_device["device_authorization_endpoint"]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = discovery_no_device
        resp.raise_for_status = MagicMock()
        http.get = AsyncMock(return_value=resp)
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        result = await provider.get_device_code()
        assert result is None


def _json_response(status_code: int, body: dict) -> MagicMock:
    """Create a mock HTTP response with JSON content-type."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.headers = {"content-type": "application/json"}
    resp.text = ""
    return resp


class TestPollDeviceToken:
    async def test_returns_pending_on_authorization_pending(self):
        """Status 400 with authorization_pending returns Pending sentinel."""
        http = _mock_discovery_http()
        http.post = AsyncMock(return_value=_json_response(400, {"error": "authorization_pending"}))
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        result = await provider.poll_device_token("device-code-123")
        assert isinstance(result, Pending)

    async def test_returns_pending_on_slow_down(self):
        """Status 400 with slow_down also returns Pending sentinel."""
        http = _mock_discovery_http()
        http.post = AsyncMock(return_value=_json_response(400, {"error": "slow_down"}))
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        result = await provider.poll_device_token("device-code-123")
        assert isinstance(result, Pending)

    async def test_returns_token_set_on_success(self):
        """Status 200 returns a TokenSet with tokens."""
        http = _mock_discovery_http()
        http.post = AsyncMock(
            return_value=_json_response(
                200,
                {
                    "access_token": "at-device",
                    "id_token": "it-device",
                    "refresh_token": "rt-device",
                    "expires_in": 3600,
                },
            )
        )
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        result = await provider.poll_device_token("device-code-123")
        assert isinstance(result, TokenSet)
        assert result.access_token == "at-device"
        assert result.id_token == "it-device"
        assert result.refresh_token == "rt-device"
        assert result.expires_in == 3600

    async def test_raises_on_expired_token(self):
        """Status 400 with expired_token raises RuntimeError."""
        http = _mock_discovery_http()
        http.post = AsyncMock(return_value=_json_response(400, {"error": "expired_token"}))
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        with pytest.raises(RuntimeError, match="expired_token"):
            await provider.poll_device_token("device-code-123")

    async def test_raises_on_non_200_non_400(self):
        """Non-200, non-400 status raises RuntimeError."""
        http = _mock_discovery_http()
        http.post = AsyncMock(return_value=_json_response(500, {}))
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        with pytest.raises(RuntimeError, match="500"):
            await provider.poll_device_token("device-code-123")


class TestRefreshTokens:
    async def test_returns_new_token_set(self):
        """Refresh returns a new TokenSet with updated tokens."""
        http = _mock_discovery_http()
        refresh_resp = MagicMock()
        refresh_resp.status_code = 200
        refresh_resp.json.return_value = {
            "access_token": "at-new",
            "id_token": "it-new",
            "refresh_token": "rt-new",
            "expires_in": 7200,
        }
        refresh_resp.raise_for_status = MagicMock()
        http.post = AsyncMock(return_value=refresh_resp)
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        result = await provider.refresh_tokens(refresh_token="rt-old")
        assert isinstance(result, TokenSet)
        assert result.access_token == "at-new"
        assert result.id_token == "it-new"
        assert result.refresh_token == "rt-new"
        assert result.expires_in == 7200

    async def test_preserves_original_refresh_token_when_omitted(self):
        """When response omits refresh_token, the original is preserved."""
        http = _mock_discovery_http()
        refresh_resp = MagicMock()
        refresh_resp.status_code = 200
        refresh_resp.json.return_value = {
            "access_token": "at-refreshed",
            "id_token": "it-refreshed",
            # No refresh_token in response
            "expires_in": 3600,
        }
        refresh_resp.raise_for_status = MagicMock()
        http.post = AsyncMock(return_value=refresh_resp)
        provider = GenericOIDCProvider(settings=_settings(), http_client=http)
        result = await provider.refresh_tokens(refresh_token="rt-original")
        assert result.refresh_token == "rt-original"
        assert result.access_token == "at-refreshed"


class TestGetUserOrgs:
    async def test_always_returns_empty(self):
        """Generic OIDC has no management API — always returns empty."""
        provider = GenericOIDCProvider(settings=_settings())
        orgs = await provider.get_user_orgs("sub123")
        assert orgs == []
