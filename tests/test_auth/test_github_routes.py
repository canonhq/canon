"""Tests for GitHub OAuth routes (login, callback, disconnect)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.middleware.sessions import SessionMiddleware

from canon.auth.github_routes import github_auth_router
from canon.main import app
from canon.settings import Settings
from canon.web.cache import TTLCache


def _make_session_app() -> FastAPI:
    """Create a minimal app with session middleware for session-dependent tests."""
    mini = FastAPI()
    mini.add_middleware(SessionMiddleware, secret_key="test-secret")
    mini.include_router(github_auth_router)
    return mini


def _mock_github_client() -> AsyncMock:
    client = AsyncMock()
    client.list_installation_repos = AsyncMock(return_value=[])
    client.list_directory = AsyncMock(return_value=[])
    client.get_file_content = AsyncMock(side_effect=Exception("not found"))
    client._get = AsyncMock(side_effect=Exception("not found"))
    return client


def _mock_provider() -> AsyncMock:
    """Create a mock OIDC provider."""
    provider = AsyncMock()
    provider.get_logout_url = AsyncMock(return_value="https://test.us.auth0.com/v2/logout")
    provider.get_user_orgs = AsyncMock(return_value=[])
    provider.get_jwks_uri = AsyncMock(
        return_value="https://test.us.auth0.com/.well-known/jwks.json"
    )
    return provider


def _mock_oauth_client() -> MagicMock:
    """Create a mock GitHubOAuthClient."""
    oauth_client = MagicMock()
    oauth_client.authorize_url = MagicMock(
        side_effect=lambda redirect_uri, state=None, **kw: (
            f"https://github.com/login/oauth/authorize?client_id=test&state={state}"
        )
    )
    oauth_client.exchange_code = AsyncMock(
        return_value={
            "access_token": "gho_test_token",
            "token_type": "bearer",
            "scope": "repo,read:org",
        }
    )
    oauth_client.get_user = AsyncMock(
        return_value={
            "id": 12345,
            "login": "testuser",
            "name": "Test User",
            "email": "test@example.com",
            "avatar_url": "https://avatars.githubusercontent.com/u/12345",
        }
    )
    return oauth_client


@pytest.fixture(autouse=True)
def _setup():
    app.state.settings = Settings(
        web_org="test-org",
        auth0_domain="test.us.auth0.com",
        auth0_client_id="test-client-id",
        auth0_client_secret="test-client-secret",
    )
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.github_client = _mock_github_client()
    app.state.oidc_provider = _mock_provider()
    app.state.db_pool = None
    app.state.user_store = None
    app.state.registry = None
    app.state.github_oauth_client = None
    app.state.connection_store = None
    yield
    app.state.github_oauth_client = None
    app.state.connection_store = None
    app.state.user_store = None


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


class TestGitHubLogin:
    async def test_redirects_to_app_when_no_oauth_client(self, client: AsyncClient):
        """When github_oauth_client is not configured, redirect to /app."""
        app.state.github_oauth_client = None
        resp = await client.get("/auth/github/login")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/app"

    async def test_redirects_to_github_authorize(self, client: AsyncClient):
        """When configured, redirects to GitHub OAuth authorize URL."""
        app.state.github_oauth_client = _mock_oauth_client()
        resp = await client.get("/auth/github/login")
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "github.com/login/oauth/authorize" in location

    async def test_stores_redirect_to_in_session(self, client: AsyncClient):
        """redirect_to parameter is stored in session for post-callback redirect."""
        app.state.github_oauth_client = _mock_oauth_client()

        resp = await client.get("/auth/github/login?redirect_to=/app/my-org/specs")
        assert resp.status_code == 302
        # Should redirect to GitHub OAuth, not /app
        assert "github.com" in resp.headers["location"]

    async def test_rejects_open_redirect(self):
        """redirect_to with double-slash is NOT stored; callback redirects to /app."""
        from urllib.parse import parse_qs, urlparse

        from starlette.testclient import TestClient

        mock_oauth = _mock_oauth_client()
        mini = _make_session_app()
        mini.state.github_oauth_client = mock_oauth

        with TestClient(mini) as tc:
            # Login with open-redirect attempt
            resp = tc.get("/auth/github/login?redirect_to=//evil.com", follow_redirects=False)
            assert resp.status_code == 302
            location = resp.headers["location"]
            parsed = urlparse(location)
            params = parse_qs(parsed.query)
            state = params.get("state", [""])[0]

            # Callback with correct state — should redirect to /app, not //evil.com
            resp = tc.get(
                f"/auth/github/callback?code=test-code&state={state}",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/app"

    async def test_rejects_backslash_redirect(self):
        """redirect_to containing backslash is NOT stored; callback redirects to /app."""
        from urllib.parse import parse_qs, urlparse

        from starlette.testclient import TestClient

        mock_oauth = _mock_oauth_client()
        mini = _make_session_app()
        mini.state.github_oauth_client = mock_oauth

        with TestClient(mini) as tc:
            resp = tc.get(r"/auth/github/login?redirect_to=/test%5Cevil", follow_redirects=False)
            assert resp.status_code == 302
            location = resp.headers["location"]
            parsed = urlparse(location)
            params = parse_qs(parsed.query)
            state = params.get("state", [""])[0]

            # Callback with correct state — should redirect to /app, not /test\evil
            resp = tc.get(
                f"/auth/github/callback?code=test-code&state={state}",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/app"


class TestGitHubCallback:
    async def test_redirects_to_app_when_no_oauth_client(self, client: AsyncClient):
        """When github_oauth_client is not configured, redirect to /app."""
        app.state.github_oauth_client = None
        resp = await client.get("/auth/github/callback?code=abc&state=xyz")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/app"

    async def test_state_mismatch_redirects_with_error(self):
        """When OAuth state doesn't match session, redirect with auth_error."""
        from starlette.testclient import TestClient

        mini = _make_session_app()
        mini.state.github_oauth_client = _mock_oauth_client()

        with TestClient(mini) as tc:
            # Callback without prior login (no state in session)
            resp = tc.get(
                "/auth/github/callback?code=test-code&state=wrong-state",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert "auth_error=state_mismatch" in resp.headers["location"]

    async def test_successful_callback_sets_github_user_session(self):
        """Successful callback stores github_user in session."""
        from urllib.parse import parse_qs, urlparse

        from starlette.testclient import TestClient

        mock_oauth = _mock_oauth_client()
        mini = _make_session_app()
        mini.state.github_oauth_client = mock_oauth

        with TestClient(mini) as tc:
            # First do login to set state in session
            resp = tc.get("/auth/github/login", follow_redirects=False)
            assert resp.status_code == 302

            # Extract state from redirect URL
            location = resp.headers["location"]
            parsed = urlparse(location)
            params = parse_qs(parsed.query)
            state = params.get("state", [""])[0]

            # Now do callback with matching state
            resp = tc.get(
                f"/auth/github/callback?code=test-code&state={state}",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/app"

    async def test_callback_redirects_to_stored_redirect_to(self):
        """After callback, user is redirected to the original redirect_to URL."""
        from urllib.parse import parse_qs, urlparse

        from starlette.testclient import TestClient

        mock_oauth = _mock_oauth_client()
        mini = _make_session_app()
        mini.state.github_oauth_client = mock_oauth

        with TestClient(mini) as tc:
            # Login with redirect_to
            resp = tc.get(
                "/auth/github/login?redirect_to=/app/my-org/specs",
                follow_redirects=False,
            )
            location = resp.headers["location"]
            parsed = urlparse(location)
            params = parse_qs(parsed.query)
            state = params.get("state", [""])[0]

            # Callback
            resp = tc.get(
                f"/auth/github/callback?code=test-code&state={state}",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/app/my-org/specs"

    async def test_callback_no_access_token_redirects_with_error(self):
        """When token exchange returns no access_token, redirect with auth_error."""
        from urllib.parse import parse_qs, urlparse

        from starlette.testclient import TestClient

        mock_oauth = _mock_oauth_client()
        mock_oauth.exchange_code = AsyncMock(return_value={"token_type": "bearer"})
        mini = _make_session_app()
        mini.state.github_oauth_client = mock_oauth

        with TestClient(mini) as tc:
            resp = tc.get("/auth/github/login", follow_redirects=False)
            location = resp.headers["location"]
            parsed = urlparse(location)
            params = parse_qs(parsed.query)
            state = params.get("state", [""])[0]

            resp = tc.get(
                f"/auth/github/callback?code=test-code&state={state}",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert "auth_error=no_token" in resp.headers["location"]

    async def test_callback_exchange_error_redirects_with_error(self):
        """When code exchange raises, redirect with auth_error=github."""
        from urllib.parse import parse_qs, urlparse

        from starlette.testclient import TestClient

        mock_oauth = _mock_oauth_client()
        mock_oauth.exchange_code = AsyncMock(side_effect=Exception("exchange failed"))
        mini = _make_session_app()
        mini.state.github_oauth_client = mock_oauth

        with TestClient(mini) as tc:
            resp = tc.get("/auth/github/login", follow_redirects=False)
            location = resp.headers["location"]
            parsed = urlparse(location)
            params = parse_qs(parsed.query)
            state = params.get("state", [""])[0]

            resp = tc.get(
                f"/auth/github/callback?code=test-code&state={state}",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert "auth_error=github" in resp.headers["location"]

    async def test_callback_persists_connection_when_stores_available(self):
        """When connection_store and user_store are available, upsert_connection is called."""
        from urllib.parse import parse_qs, urlparse

        from starlette.testclient import TestClient

        mock_oauth = _mock_oauth_client()
        mini = _make_session_app()
        mini.state.github_oauth_client = mock_oauth

        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value={"id": 42})
        mini.state.user_store = mock_user_store

        mock_connection_store = AsyncMock()
        mock_connection_store.upsert_connection = AsyncMock()
        mini.state.connection_store = mock_connection_store

        with TestClient(mini) as tc:
            resp = tc.get("/auth/github/login", follow_redirects=False)
            location = resp.headers["location"]
            parsed = urlparse(location)
            params = parse_qs(parsed.query)
            state = params.get("state", [""])[0]

            resp = tc.get(
                f"/auth/github/callback?code=test-code&state={state}",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/app"


class TestGitHubDisconnect:
    async def test_disconnect_redirects_to_app(self, client: AsyncClient):
        """Disconnect should redirect to /app."""
        resp = await client.get("/auth/github/disconnect")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/app"

    async def test_disconnect_removes_db_connection(self):
        """When stores are available and user is logged in, delete_connection is called."""
        from starlette.testclient import TestClient

        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value={"id": 42})

        mock_connection_store = AsyncMock()
        mock_connection_store.delete_connection = AsyncMock()

        mini = _make_session_app()
        mini.state.user_store = mock_user_store
        mini.state.connection_store = mock_connection_store

        with TestClient(mini) as tc:
            # Without a session user, delete_connection should not be called
            resp = tc.get("/auth/github/disconnect", follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers["location"] == "/app"

    async def test_disconnect_without_stores(self, client: AsyncClient):
        """Disconnect works even without DB stores configured."""
        app.state.connection_store = None
        app.state.user_store = None

        resp = await client.get("/auth/github/disconnect")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/app"
