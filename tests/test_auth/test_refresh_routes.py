"""Tests for token refresh endpoint."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from canon.auth.providers.protocol import TokenSet
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
    return provider


@pytest.fixture(autouse=True)
def _setup():
    app.state.settings = Settings(
        web_org="test-org",
        auth0_domain="test.us.auth0.com",
        auth0_client_id="test-client-id",
        auth0_client_secret="test-client-secret",
        auth0_device_client_id="test-device-client-id",
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
    app.state.session_store = None


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


class TestRefreshFromBody:
    async def test_refreshes_with_body_token(self, client: AsyncClient):
        old_refresh = "old-refresh-token"
        old_hash = hashlib.sha256(old_refresh.encode()).hexdigest()

        mock_session_store = AsyncMock()
        mock_session_store.get_session_by_refresh_hash = AsyncMock(
            return_value={
                "id": "sess-1",
                "user_id": 1,
                "org_login": "my-org",
                "refresh_hash": old_hash,
            }
        )
        mock_session_store.rotate_refresh = AsyncMock(return_value=True)
        app.state.session_store = mock_session_store

        app.state.oidc_provider.refresh_tokens = AsyncMock(
            return_value=TokenSet(
                access_token="new-at-123",
                refresh_token="new-rt-456",
                expires_in=3600,
            )
        )

        resp = await client.post(
            "/auth/refresh",
            json={"refresh_token": old_refresh},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "new-at-123"
        assert data["refresh_token"] == "new-rt-456"
        assert data["expires_in"] == 3600
        mock_session_store.rotate_refresh.assert_awaited_once()

    async def test_returns_401_with_no_token(self, client: AsyncClient):
        mock_session_store = AsyncMock()
        app.state.session_store = mock_session_store

        resp = await client.post("/auth/refresh", json={"refresh_token": ""})
        assert resp.status_code == 401

    async def test_returns_401_with_invalid_session(self, client: AsyncClient):
        mock_session_store = AsyncMock()
        mock_session_store.get_session_by_refresh_hash = AsyncMock(return_value=None)
        app.state.session_store = mock_session_store

        resp = await client.post(
            "/auth/refresh",
            json={"refresh_token": "invalid-token"},
        )
        assert resp.status_code == 401

    async def test_returns_503_when_no_session_store(self, client: AsyncClient):
        app.state.session_store = None
        resp = await client.post(
            "/auth/refresh",
            json={"refresh_token": "some-token"},
        )
        assert resp.status_code == 503

    async def test_returns_401_when_provider_rejects(self, client: AsyncClient):
        old_refresh = "old-token"
        old_hash = hashlib.sha256(old_refresh.encode()).hexdigest()

        mock_session_store = AsyncMock()
        mock_session_store.get_session_by_refresh_hash = AsyncMock(
            return_value={"id": "sess-1", "user_id": 1, "refresh_hash": old_hash}
        )
        app.state.session_store = mock_session_store

        app.state.oidc_provider.refresh_tokens = AsyncMock(side_effect=Exception("invalid_grant"))

        resp = await client.post(
            "/auth/refresh",
            json={"refresh_token": old_refresh},
        )

        assert resp.status_code == 401

    async def test_rotation_failure_revokes_session(self, client: AsyncClient):
        old_refresh = "old-refresh-token"
        old_hash = hashlib.sha256(old_refresh.encode()).hexdigest()

        mock_session_store = AsyncMock()
        mock_session_store.get_session_by_refresh_hash = AsyncMock(
            return_value={
                "id": "sess-1",
                "user_id": 1,
                "org_login": "my-org",
                "refresh_hash": old_hash,
            }
        )
        mock_session_store.rotate_refresh = AsyncMock(return_value=False)
        mock_session_store.revoke_session = AsyncMock(return_value=True)
        app.state.session_store = mock_session_store

        app.state.oidc_provider.refresh_tokens = AsyncMock(
            return_value=TokenSet(
                access_token="new-at-123",
                refresh_token="new-rt-456",
                expires_in=3600,
            )
        )

        resp = await client.post(
            "/auth/refresh",
            json={"refresh_token": old_refresh},
        )

        assert resp.status_code == 401
        mock_session_store.revoke_session.assert_awaited_once_with(session_id="sess-1", user_id=1)

    async def test_returns_503_when_provider_not_configured(self, client: AsyncClient):
        app.state.oidc_provider = None

        mock_session_store = AsyncMock()
        mock_session_store.get_session_by_refresh_hash = AsyncMock(
            return_value={"id": "sess-1", "user_id": 1, "refresh_hash": "h"}
        )
        app.state.session_store = mock_session_store

        resp = await client.post(
            "/auth/refresh",
            json={"refresh_token": "some-token"},
        )
        assert resp.status_code == 503
