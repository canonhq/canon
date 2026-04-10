"""Tests for device authorization grant endpoints."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.auth.providers.protocol import DeviceCodeResponse, Pending, TokenSet
from canon.main import app
from canon.settings import Settings
from canon.web.cache import TTLCache


def _fake_id_token(claims: dict) -> str:
    """Build a three-segment ID token whose payload decodes to *claims*.

    Signature is ignored by :func:`_decode_id_token_claims`, so we use a
    placeholder that keeps the segment count valid.
    """
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def _mock_client() -> AsyncMock:
    client = AsyncMock()
    client.list_installation_repos = AsyncMock(return_value=[])
    client.list_directory = AsyncMock(return_value=[])
    client.get_file_content = AsyncMock(side_effect=Exception("not found"))
    client._get = AsyncMock(side_effect=Exception("not found"))
    return client


def _mock_provider() -> AsyncMock:
    """Create a mock OIDC provider."""
    provider = AsyncMock()
    provider.get_jwks_uri = AsyncMock(
        return_value="https://test.us.auth0.com/.well-known/jwks.json"
    )
    return provider


@pytest.fixture(autouse=True)
def _setup():
    app.state.settings = Settings(
        web_org="test-org",
        auth0_domain="test.us.auth0.com",
        auth0_client_id="test-client-id",
        auth0_client_secret="test-client-secret",
        auth0_device_client_id="test-device-client-id",
        auth0_audience="https://canon.example.com/api",
    )
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.github_client = _mock_client()
    app.state.oidc_provider = _mock_provider()
    app.state.auth_http = AsyncMock()
    app.state.auth0_http = app.state.auth_http
    app.state.db_pool = None
    app.state.user_store = None
    app.state.session_store = None
    app.state.registry = None
    yield
    app.state.user_store = None
    app.state.session_store = None


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


class TestRequestDeviceCode:
    async def test_returns_device_code(self, client: AsyncClient):
        app.state.oidc_provider.get_device_code = AsyncMock(
            return_value=DeviceCodeResponse(
                device_code="dev-code-123",
                user_code="ABCD-1234",
                verification_uri="https://test.us.auth0.com/activate",
                verification_uri_complete="https://test.us.auth0.com/activate?user_code=ABCD-1234",
                interval=5,
                expires_in=900,
            )
        )
        resp = await client.post("/auth/device/code", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["device_code"] == "dev-code-123"
        assert data["user_code"] == "ABCD-1234"
        assert data["interval"] == 5

    async def test_returns_503_when_not_configured(self, client: AsyncClient):
        app.state.oidc_provider = None
        resp = await client.post("/auth/device/code", json={})
        assert resp.status_code == 503

    async def test_returns_501_when_provider_returns_none(self, client: AsyncClient):
        """Provider returns None when device flow is not supported."""
        app.state.oidc_provider.get_device_code = AsyncMock(return_value=None)
        resp = await client.post("/auth/device/code", json={})
        assert resp.status_code == 501

    async def test_returns_502_on_provider_failure(self, client: AsyncClient):
        app.state.oidc_provider.get_device_code = AsyncMock(
            side_effect=Exception("connection error")
        )
        resp = await client.post("/auth/device/code", json={})
        assert resp.status_code == 502

    async def test_forwards_resolved_organization_id(self, client: AsyncClient):
        """When `org` is passed, it's resolved via the registry and forwarded to the provider."""
        app.state.oidc_provider.get_device_code = AsyncMock(
            return_value=DeviceCodeResponse(device_code="dc", user_code="UC")
        )
        mock_registry = AsyncMock()
        mock_registry.get_installation_by_org = AsyncMock(
            return_value=SimpleNamespace(oidc_org_id="org_abc123")
        )
        app.state.registry = mock_registry

        resp = await client.post("/auth/device/code", json={"org": "canonhq"})

        assert resp.status_code == 200
        mock_registry.get_installation_by_org.assert_awaited_once_with("canonhq")
        call = app.state.oidc_provider.get_device_code.await_args
        assert call.kwargs["organization"] == "org_abc123"

    async def test_proceeds_without_organization_when_org_unknown(self, client: AsyncClient):
        """Unknown orgs don't break device code issuance — org falls back to empty."""
        app.state.oidc_provider.get_device_code = AsyncMock(
            return_value=DeviceCodeResponse(device_code="dc", user_code="UC")
        )
        mock_registry = AsyncMock()
        mock_registry.get_installation_by_org = AsyncMock(return_value=None)
        app.state.registry = mock_registry

        resp = await client.post("/auth/device/code", json={"org": "ghost-org"})

        assert resp.status_code == 200
        call = app.state.oidc_provider.get_device_code.await_args
        assert call.kwargs["organization"] == ""

    async def test_rejects_oversized_org(self, client: AsyncClient):
        """Bounded input on an unauthenticated endpoint — 101+ chars must 422."""
        resp = await client.post("/auth/device/code", json={"org": "a" * 101})
        assert resp.status_code == 422

    async def test_rejects_malformed_org(self, client: AsyncClient):
        """Slash/space/etc. must be rejected before hitting the registry."""
        mock_registry = AsyncMock()
        app.state.registry = mock_registry

        resp = await client.post("/auth/device/code", json={"org": "bad slug!"})

        assert resp.status_code == 422
        # Registry was never consulted — rejection happens at the boundary.
        mock_registry.get_installation_by_org.assert_not_awaited()

    async def test_no_org_no_registry_lookup(self, client: AsyncClient):
        """Without an org hint, the registry isn't queried at all."""
        app.state.oidc_provider.get_device_code = AsyncMock(
            return_value=DeviceCodeResponse(device_code="dc", user_code="UC")
        )
        mock_registry = AsyncMock()
        app.state.registry = mock_registry

        resp = await client.post("/auth/device/code", json={})

        assert resp.status_code == 200
        mock_registry.get_installation_by_org.assert_not_awaited()
        call = app.state.oidc_provider.get_device_code.await_args
        assert call.kwargs["organization"] == ""


class TestPollDeviceToken:
    async def test_returns_pending(self, client: AsyncClient):
        app.state.oidc_provider.poll_device_token = AsyncMock(return_value=Pending())
        resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    async def test_returns_slow_down(self, client: AsyncClient):
        """slow_down is folded into pending by the new provider abstraction."""
        app.state.oidc_provider.poll_device_token = AsyncMock(return_value=Pending())
        resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 200
        # Provider maps slow_down → Pending; route returns "pending"
        assert resp.json()["status"] == "pending"

    async def test_returns_expired(self, client: AsyncClient):
        app.state.oidc_provider.poll_device_token = AsyncMock(
            side_effect=RuntimeError("Device auth error: expired_token")
        )
        resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "expired"

    async def test_returns_denied(self, client: AsyncClient):
        app.state.oidc_provider.poll_device_token = AsyncMock(
            side_effect=RuntimeError("Device auth error: access_denied")
        )
        resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "denied"

    async def test_approved_returns_tokens(self, client: AsyncClient):
        """Email/name come from the ID token, not the access token."""
        id_token = _fake_id_token(
            {"sub": "auth0|123", "email": "test@example.com", "name": "Test User"}
        )
        app.state.oidc_provider.poll_device_token = AsyncMock(
            return_value=TokenSet(
                access_token="at-123",
                id_token=id_token,
                refresh_token="rt-456",
                expires_in=86400,
            )
        )

        mock_user_store = AsyncMock()
        mock_user_store.upsert_user = AsyncMock(return_value={"id": 1})
        app.state.user_store = mock_user_store

        mock_session_store = AsyncMock()
        mock_session_store.create_session = AsyncMock(return_value={"id": "sess-1"})
        app.state.session_store = mock_session_store

        with patch("canon.auth.device_routes.validate_access_token") as mock_validate:
            # Access token claims are typical Auth0 shape — no PII.
            mock_validate.return_value = {"sub": "auth0|123"}

            resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["access_token"] == "at-123"
        assert data["refresh_token"] == "rt-456"
        assert data["email"] == "test@example.com"
        mock_user_store.upsert_user.assert_awaited_once()
        upsert_kwargs = mock_user_store.upsert_user.await_args.kwargs
        assert upsert_kwargs["email"] == "test@example.com"
        assert upsert_kwargs["name"] == "Test User"
        mock_session_store.create_session.assert_awaited_once()

    async def test_approved_falls_back_to_access_claims_without_id_token(self, client: AsyncClient):
        """Generic OIDC providers that embed email in the access token still work."""
        app.state.oidc_provider.poll_device_token = AsyncMock(
            return_value=TokenSet(
                access_token="at-123",
                id_token="",
                refresh_token="rt-456",
                expires_in=86400,
            )
        )

        mock_user_store = AsyncMock()
        mock_user_store.upsert_user = AsyncMock(return_value={"id": 1})
        app.state.user_store = mock_user_store

        with patch("canon.auth.device_routes.validate_access_token") as mock_validate:
            mock_validate.return_value = {
                "sub": "oidc|456",
                "email": "fallback@example.com",
                "name": "Fallback User",
            }
            resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "fallback@example.com"

    async def test_approved_with_jwt_validation_failure(self, client: AsyncClient):
        app.state.oidc_provider.poll_device_token = AsyncMock(
            return_value=TokenSet(
                access_token="bad-token",
                refresh_token="rt-456",
                expires_in=86400,
            )
        )

        with patch(
            "canon.auth.device_routes.validate_access_token",
            side_effect=ValueError("Invalid token"),
        ):
            resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 503

    async def test_returns_503_when_not_configured(self, client: AsyncClient):
        app.state.oidc_provider = None
        resp = await client.post("/auth/device/token", json={"device_code": "x"})
        assert resp.status_code == 503

    async def test_rejects_empty_identity(self, client: AsyncClient):
        """Empty sub/email must fail loudly rather than upsert a blank user."""
        app.state.oidc_provider.poll_device_token = AsyncMock(
            return_value=TokenSet(
                access_token="at-123",
                id_token="",
                refresh_token="rt-456",
                expires_in=86400,
            )
        )

        with patch("canon.auth.device_routes.validate_access_token") as mock_validate:
            # Access token has no sub/email and no id_token to fall back on.
            mock_validate.return_value = {}
            resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 500
        assert "identity" in resp.json()["detail"].lower()

    async def test_prefers_access_token_sub_over_id_token(self, client: AsyncClient):
        """``sub`` comes from the JWKS-validated access token, never from the ID token."""
        id_token = _fake_id_token(
            {"sub": "auth0|forged", "email": "real@example.com", "name": "Real User"}
        )
        app.state.oidc_provider.poll_device_token = AsyncMock(
            return_value=TokenSet(
                access_token="at-123",
                id_token=id_token,
                refresh_token="rt-456",
                expires_in=86400,
            )
        )

        mock_user_store = AsyncMock()
        mock_user_store.upsert_user = AsyncMock(return_value={"id": 1})
        app.state.user_store = mock_user_store

        with patch("canon.auth.device_routes.validate_access_token") as mock_validate:
            mock_validate.return_value = {"sub": "auth0|real"}
            resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 200
        upsert_kwargs = mock_user_store.upsert_user.await_args.kwargs
        assert upsert_kwargs["oidc_sub"] == "auth0|real"  # NOT auth0|forged

    async def test_id_token_email_wins_over_access_token_email(self, client: AsyncClient):
        """When both have email, ID token wins (matches the documented fallback order)."""
        id_token = _fake_id_token(
            {"sub": "auth0|123", "email": "from-id-token@example.com", "name": "User"}
        )
        app.state.oidc_provider.poll_device_token = AsyncMock(
            return_value=TokenSet(
                access_token="at-123",
                id_token=id_token,
                refresh_token="rt-456",
                expires_in=86400,
            )
        )

        mock_user_store = AsyncMock()
        mock_user_store.upsert_user = AsyncMock(return_value={"id": 1})
        app.state.user_store = mock_user_store

        with patch("canon.auth.device_routes.validate_access_token") as mock_validate:
            mock_validate.return_value = {
                "sub": "auth0|123",
                "email": "from-access-token@example.com",
            }
            resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 200
        assert resp.json()["email"] == "from-id-token@example.com"


class TestRegistryErrorPropagation:
    """Operational registry errors must not be silently swallowed."""

    async def test_registry_operational_error_propagates(self, client: AsyncClient):
        """A DB exception during org lookup is not the same as 'unknown org' and must surface.

        In production, an uncaught exception becomes a 500 via FastAPI's default
        handler; under ``ASGITransport`` it re-raises into the test client. Both
        behaviours are preferable to the previous silent fallback — which is
        exactly the bug this PR is fixing.
        """
        app.state.oidc_provider.get_device_code = AsyncMock(
            return_value=DeviceCodeResponse(device_code="dc", user_code="UC")
        )
        mock_registry = AsyncMock()
        mock_registry.get_installation_by_org = AsyncMock(
            side_effect=RuntimeError("connection refused")
        )
        app.state.registry = mock_registry

        with pytest.raises(RuntimeError, match="connection refused"):
            await client.post("/auth/device/code", json={"org": "canonhq"})

        # Provider was never called because registry failed first — no silent fallback.
        app.state.oidc_provider.get_device_code.assert_not_awaited()


class TestDecodeIdTokenClaims:
    """Direct unit tests for _decode_id_token_claims defensive branches."""

    def test_empty_string_returns_empty_dict(self):
        from canon.auth.device_routes import _decode_id_token_claims

        assert _decode_id_token_claims("") == {}

    def test_wrong_segment_count_returns_empty_dict(self):
        from canon.auth.device_routes import _decode_id_token_claims

        assert _decode_id_token_claims("only.two") == {}
        assert _decode_id_token_claims("one") == {}
        assert _decode_id_token_claims("a.b.c.d") == {}

    def test_invalid_base64_returns_empty_dict(self):
        from canon.auth.device_routes import _decode_id_token_claims

        # Middle segment has characters that aren't valid urlsafe base64.
        assert _decode_id_token_claims("hdr.!!!not-base64!!!.sig") == {}

    def test_non_json_payload_returns_empty_dict(self):
        from canon.auth.device_routes import _decode_id_token_claims

        # Base64-encode something that isn't JSON.
        bad = base64.urlsafe_b64encode(b"not json at all").rstrip(b"=").decode()
        assert _decode_id_token_claims(f"hdr.{bad}.sig") == {}

    def test_non_dict_json_returns_empty_dict(self):
        from canon.auth.device_routes import _decode_id_token_claims

        # Valid JSON, but an array rather than an object.
        arr = base64.urlsafe_b64encode(b'["not", "a", "dict"]').rstrip(b"=").decode()
        assert _decode_id_token_claims(f"hdr.{arr}.sig") == {}

    def test_happy_path(self):
        from canon.auth.device_routes import _decode_id_token_claims

        claims = {"sub": "user-1", "email": "u@e.com"}
        token = _fake_id_token(claims)
        assert _decode_id_token_claims(token) == claims
