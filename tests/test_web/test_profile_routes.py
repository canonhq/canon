"""Tests for profile routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from canon.auth.permissions import Permission
from canon.main import app
from canon.settings import Settings
from canon.web.cache import TTLCache
from canon.web.profile_routes import _infer_role


def _mock_client() -> AsyncMock:
    client = AsyncMock()
    client.list_installation_repos = AsyncMock(return_value=[])
    return client


@pytest.fixture(autouse=True)
def _setup_app_state():
    """Set up app state for profile route tests."""
    app.state.settings = Settings(web_org="test-org")
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.github_client = _mock_client()
    app.state.github_oauth_client = None
    app.state.search_index = None
    app.state.embed_client = None
    app.state.registry = None
    app.state.agent_store = None
    app.state.user_store = None
    yield


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


class TestInferRole:
    def test_viewer(self):
        perms = frozenset({Permission.SPECS_READ})
        assert _infer_role(perms) == "viewer"

    def test_editor(self):
        perms = frozenset({Permission.SPECS_READ, Permission.SPECS_WRITE})
        assert _infer_role(perms) == "editor"

    def test_admin(self):
        perms = frozenset(Permission)
        assert _infer_role(perms) == "admin"

    def test_empty_permissions_defaults_to_viewer(self):
        assert _infer_role(frozenset()) == "viewer"

    def test_write_only_defaults_to_viewer(self):
        # SPECS_WRITE without SPECS_READ doesn't match editor
        perms = frozenset({Permission.SPECS_WRITE})
        assert _infer_role(perms) == "viewer"


class TestProfileRoute:
    @pytest.mark.asyncio
    async def test_unauthenticated_redirects_to_login(self, client):
        """Without a session and auth0 enabled, the profile endpoint redirects to login."""
        app.state.settings = Settings(
            web_org="test-org",
            auth0_domain="test.auth0.com",
            auth0_client_id="test-id",
            auth0_client_secret="test-secret",
        )
        resp = await client.get("/app/test-org/api/profile")
        assert resp.status_code in (307, 401)
        if resp.status_code == 307:
            assert "/auth/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_anonymous_returns_profile_when_auth_disabled(self, client):
        """Without auth0 enabled, anonymous user gets a profile response."""
        resp = await client.get("/app/test-org/api/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sub"] == "anonymous"
        assert data["auth_method"] == "anonymous"
        assert data["inferred_role"] == "admin"  # anonymous gets all permissions

    @pytest.mark.asyncio
    async def test_anonymous_profile_includes_all_permissions(self, client):
        """The all_permissions field contains every defined permission."""
        resp = await client.get("/app/test-org/api/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert "all_permissions" in data
        assert set(data["all_permissions"]) == {
            "specs:read",
            "specs:write",
            "specs:admin",
            "org:manage",
        }

    @pytest.mark.asyncio
    async def test_profile_includes_permission_descriptions(self, client):
        """The permission_descriptions field maps each permission to a label."""
        resp = await client.get("/app/test-org/api/profile")
        assert resp.status_code == 200
        data = resp.json()
        descs = data["permission_descriptions"]
        assert descs["specs:read"] == "Read access to specs"
        assert descs["specs:write"] == "Create and edit specs"
        assert descs["specs:admin"] == "Manage spec settings and configuration"
        assert descs["org:manage"] == "Manage organization settings"

    @pytest.mark.asyncio
    async def test_profile_with_user_store_includes_last_login(self, client):
        """When user_store has the user, last_login_at appears in the response."""
        mock_store = AsyncMock()
        mock_store.get_user_by_sub = AsyncMock(
            return_value={
                "oidc_sub": "anonymous",
                "email": "",
                "name": "Anonymous",
                "last_login_at": datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC),
            }
        )
        app.state.user_store = mock_store

        resp = await client.get("/app/test-org/api/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_login_at"] == "2026-02-20T12:00:00+00:00"
        mock_store.get_user_by_sub.assert_awaited_once_with("anonymous")

    @pytest.mark.asyncio
    async def test_profile_without_user_store_omits_last_login(self, client):
        """When user_store is None, last_login_at is null in the response."""
        app.state.user_store = None
        resp = await client.get("/app/test-org/api/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_login_at"] is None

    @pytest.mark.asyncio
    async def test_profile_graceful_on_user_store_failure(self, client):
        """Profile route still returns 200 when user_store raises an exception."""
        mock_store = AsyncMock()
        mock_store.get_user_by_sub = AsyncMock(side_effect=RuntimeError("DB down"))
        app.state.user_store = mock_store

        resp = await client.get("/app/test-org/api/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_login_at"] is None

    @pytest.mark.asyncio
    async def test_org_login_not_populated_from_url(self, client):
        """The org_login field comes from the user, not the URL path."""
        # Anonymous user has empty org_login; URL org should NOT backfill it
        resp = await client.get("/app/some-other-org/api/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["org_login"] == ""

    @pytest.mark.asyncio
    async def test_anonymous_profile_includes_org_id(self, client):
        """The org_id field is present (empty for anonymous user)."""
        resp = await client.get("/app/test-org/api/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["org_id"] == ""


class TestProfileResponseModel:
    """Test that ProfileResponse serializes correctly."""

    def test_profile_response_shape(self):
        from canon.web.models import ProfileGitHubUser, ProfileResponse

        profile = ProfileResponse(
            sub="auth0|123",
            email="test@example.com",
            name="Test User",
            picture="https://example.com/pic.jpg",
            org_login="test-org",
            org_id="org_abc123",
            permissions=["specs:read", "specs:write"],
            all_permissions=["org:manage", "specs:admin", "specs:read", "specs:write"],
            permission_descriptions={"specs:read": "Read access to specs"},
            auth_method="session",
            github_user=ProfileGitHubUser(login="testuser", name="Test User"),
            last_login_at="2026-02-20T12:00:00+00:00",
            inferred_role="editor",
        )
        data = profile.model_dump()
        assert data["sub"] == "auth0|123"
        assert data["inferred_role"] == "editor"
        assert data["permissions"] == ["specs:read", "specs:write"]
        assert data["github_user"] == {"login": "testuser", "name": "Test User"}
        assert data["last_login_at"] == "2026-02-20T12:00:00+00:00"
        assert data["all_permissions"] == ["org:manage", "specs:admin", "specs:read", "specs:write"]
        assert data["org_id"] == "org_abc123"
        assert data["permission_descriptions"] == {"specs:read": "Read access to specs"}

    def test_profile_response_optional_fields(self):
        from canon.web.models import ProfileResponse

        profile = ProfileResponse(
            sub="auth0|456",
            email="minimal@example.com",
            name="",
            picture="",
            org_login="test-org",
            permissions=[],
            all_permissions=["org:manage", "specs:admin", "specs:read", "specs:write"],
            auth_method="session",
            inferred_role="viewer",
        )
        data = profile.model_dump()
        assert data["github_user"] is None
        assert data["last_login_at"] is None
        assert data["org_id"] == ""
        assert data["permission_descriptions"] == {}
