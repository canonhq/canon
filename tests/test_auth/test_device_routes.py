"""Tests for device authorization grant endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.auth.providers.protocol import DeviceCodeResponse, Pending, TokenSet
from canon.main import app
from canon.settings import Settings
from canon.web.cache import TTLCache


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
        app.state.oidc_provider.poll_device_token = AsyncMock(
            return_value=TokenSet(
                access_token="at-123",
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
            mock_validate.return_value = {
                "sub": "auth0|123",
                "email": "test@example.com",
                "name": "Test User",
            }

            resp = await client.post("/auth/device/token", json={"device_code": "dev-code"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["access_token"] == "at-123"
        assert data["refresh_token"] == "rt-456"
        assert data["email"] == "test@example.com"
        mock_user_store.upsert_user.assert_awaited_once()
        mock_session_store.create_session.assert_awaited_once()

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
