"""HTTP-level tests for API key management routes (create, list, revoke)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.auth.models import CurrentUser
from canon.auth.permissions import Permission
from canon.main import app
from canon.settings import Settings
from canon.web.cache import TTLCache

_ADMIN_USER = CurrentUser(
    sub="auth0|admin",
    email="admin@test.com",
    name="Admin",
    org_login="test-org",
    permissions=frozenset(Permission),
    auth_method="session",
)

_READ_ONLY_USER = CurrentUser(
    sub="auth0|reader",
    email="reader@test.com",
    name="Reader",
    org_login="test-org",
    permissions=frozenset({Permission.SPECS_READ}),
    auth_method="session",
)


def _mock_client() -> AsyncMock:
    client = AsyncMock()
    client.list_installation_repos = AsyncMock(return_value=[])
    client.list_directory = AsyncMock(return_value=[])
    client.get_file_content = AsyncMock(side_effect=Exception("not found"))
    client._get = AsyncMock(side_effect=Exception("not found"))
    return client


@pytest.fixture(autouse=True)
def _setup():
    # Disable auth middleware so we can test route logic directly with patched deps
    app.state.settings = Settings(web_org="test-org")
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.github_client = _mock_client()
    app.state.db_pool = None
    app.state.user_store = None
    app.state.registry = None
    yield
    app.state.user_store = None


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


class TestListApiKeys:
    async def test_list_returns_keys(self, client: AsyncClient):
        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value={"id": 1})
        mock_user_store.list_api_keys = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "label": "my key",
                    "org_login": "test-org",
                    "scopes": ["specs:read"],
                    "created_at": datetime.now(UTC),
                    "expires_at": None,
                    "revoked_at": None,
                    "last_used_at": None,
                },
            ]
        )
        app.state.user_store = mock_user_store

        with patch("canon.auth.deps.get_current_user", return_value=_ADMIN_USER):
            resp = await client.get("/app/test-org/settings/api-keys/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["keys"]) == 1
        assert data["keys"][0]["label"] == "my key"

    async def test_list_empty_when_no_db_user(self, client: AsyncClient):
        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value=None)
        app.state.user_store = mock_user_store

        with patch("canon.auth.deps.get_current_user", return_value=_ADMIN_USER):
            resp = await client.get("/app/test-org/settings/api-keys/")
        assert resp.status_code == 200
        assert resp.json() == {"keys": []}

    async def test_list_returns_503_when_no_store(self, client: AsyncClient):
        with patch("canon.auth.deps.get_current_user", return_value=_ADMIN_USER):
            resp = await client.get("/app/test-org/settings/api-keys/")
        assert resp.status_code == 503

    async def test_list_requires_admin_permission(self, client: AsyncClient):
        """A user with only specs:read should get 403."""
        with patch("canon.auth.deps.get_current_user", return_value=_READ_ONLY_USER):
            resp = await client.get("/app/test-org/settings/api-keys/")
        assert resp.status_code == 403


class TestCreateApiKey:
    async def test_create_success(self, client: AsyncClient):
        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value={"id": 1})
        mock_user_store.create_api_key = AsyncMock(
            return_value=(
                "sw_newkey123",
                {
                    "id": 42,
                    "label": "test",
                    "scopes": ["specs:read"],
                    "expires_at": None,
                },
            )
        )
        app.state.user_store = mock_user_store

        with patch("canon.auth.deps.get_current_user", return_value=_ADMIN_USER):
            resp = await client.post(
                "/app/test-org/settings/api-keys/",
                json={"label": "test", "scopes": ["specs:read"]},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["key"] == "sw_newkey123"
        assert data["id"] == 42

    async def test_create_rejects_invalid_scope(self, client: AsyncClient):
        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value={"id": 1})
        app.state.user_store = mock_user_store

        with patch("canon.auth.deps.get_current_user", return_value=_ADMIN_USER):
            resp = await client.post(
                "/app/test-org/settings/api-keys/",
                json={"scopes": ["invalid:scope"]},
            )
        assert resp.status_code == 400
        assert "Invalid scope" in resp.json()["detail"]

    async def test_create_rejects_scope_user_lacks(self, client: AsyncClient):
        """User with only specs:read can't grant specs:admin."""
        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value={"id": 1})
        app.state.user_store = mock_user_store

        # This user has all permissions via _ADMIN_USER, but let's make a custom one
        limited_admin = CurrentUser(
            sub="auth0|limited",
            permissions=frozenset({Permission.SPECS_READ, Permission.SPECS_ADMIN}),
            auth_method="session",
        )
        with patch("canon.auth.deps.get_current_user", return_value=limited_admin):
            resp = await client.post(
                "/app/test-org/settings/api-keys/",
                json={"scopes": ["specs:write"]},
            )
        assert resp.status_code == 403
        assert "Cannot grant scope" in resp.json()["detail"]

    async def test_create_rejects_negative_expires(self, client: AsyncClient):
        """Negative expires_in_days should be rejected by validation."""
        mock_user_store = AsyncMock()
        app.state.user_store = mock_user_store

        with patch("canon.auth.deps.get_current_user", return_value=_ADMIN_USER):
            resp = await client.post(
                "/app/test-org/settings/api-keys/",
                json={"expires_in_days": -1},
            )
        assert resp.status_code == 422  # Pydantic validation error

    async def test_create_rejects_zero_expires(self, client: AsyncClient):
        """Zero expires_in_days should be rejected (ge=1)."""
        mock_user_store = AsyncMock()
        app.state.user_store = mock_user_store

        with patch("canon.auth.deps.get_current_user", return_value=_ADMIN_USER):
            resp = await client.post(
                "/app/test-org/settings/api-keys/",
                json={"expires_in_days": 0},
            )
        assert resp.status_code == 422


class TestRevokeApiKey:
    async def test_revoke_success(self, client: AsyncClient):
        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value={"id": 1})
        mock_user_store.revoke_api_key = AsyncMock(return_value=True)
        app.state.user_store = mock_user_store

        with patch("canon.auth.deps.get_current_user", return_value=_ADMIN_USER):
            resp = await client.delete("/app/test-org/settings/api-keys/42")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        # Verify org_login was passed
        mock_user_store.revoke_api_key.assert_awaited_once_with(
            key_id=42, user_id=1, org_login="test-org"
        )

    async def test_revoke_not_found(self, client: AsyncClient):
        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value={"id": 1})
        mock_user_store.revoke_api_key = AsyncMock(return_value=False)
        app.state.user_store = mock_user_store

        with patch("canon.auth.deps.get_current_user", return_value=_ADMIN_USER):
            resp = await client.delete("/app/test-org/settings/api-keys/999")
        assert resp.status_code == 404

    async def test_revoke_requires_admin(self, client: AsyncClient):
        with patch("canon.auth.deps.get_current_user", return_value=_READ_ONLY_USER):
            resp = await client.delete("/app/test-org/settings/api-keys/1")
        assert resp.status_code == 403
