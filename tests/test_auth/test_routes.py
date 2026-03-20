"""Tests for auth routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import jwt as pyjwt
import pytest
from fastapi.responses import RedirectResponse
from httpx import ASGITransport, AsyncClient

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


def _mock_provider(
    logout_url: str = "https://test.us.auth0.com/v2/logout?client_id=test-client-id&returnTo=http%3A%2F%2Ftestserver%2F",
) -> AsyncMock:
    """Create a mock OIDC provider that returns a plausible Auth0 logout URL."""
    provider = AsyncMock()
    provider.get_logout_url = AsyncMock(return_value=logout_url)
    provider.get_user_orgs = AsyncMock(return_value=[])
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
    )
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.github_client = _mock_client()
    app.state.oidc_provider = _mock_provider()
    app.state.db_pool = None
    app.state.user_store = None
    app.state.registry = None


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


class TestLogin:
    async def test_login_redirects_to_auth0(self, client: AsyncClient):
        """GET /auth/login should redirect to Auth0 authorize URL."""
        with patch("canon.auth.routes.oauth") as mock_oauth:
            from fastapi.responses import RedirectResponse

            mock_oauth.auth0.authorize_redirect = AsyncMock(
                return_value=RedirectResponse(
                    "https://test.us.auth0.com/authorize?client_id=test-client-id"
                )
            )
            resp = await client.get("/auth/login")
            assert resp.status_code == 307
            assert "test.us.auth0.com" in resp.headers["location"]

    async def test_login_with_org_param(self, client: AsyncClient):
        """GET /auth/login?org=my-org passes org to session for redirect."""
        with patch("canon.auth.routes.oauth") as mock_oauth:
            from fastapi.responses import RedirectResponse

            mock_oauth.auth0.authorize_redirect = AsyncMock(
                return_value=RedirectResponse(
                    "https://test.us.auth0.com/authorize?client_id=test-client-id"
                )
            )
            resp = await client.get("/auth/login?org=my-org")
            assert resp.status_code == 307

    async def test_login_with_connection_hint(self, client: AsyncClient):
        """GET /auth/login?connection=github passes connection kwarg to Auth0."""
        with patch("canon.auth.routes.oauth") as mock_oauth:
            mock_oauth.auth0.authorize_redirect = AsyncMock(
                return_value=RedirectResponse(
                    "https://test.us.auth0.com/authorize?connection=github"
                )
            )
            resp = await client.get("/auth/login?connection=github")
            assert resp.status_code == 307
            # Verify connection was passed as a kwarg
            call_kwargs = mock_oauth.auth0.authorize_redirect.call_args
            assert call_kwargs.kwargs.get("connection") == "github"

    async def test_login_without_connection_skips_kwarg(self, client: AsyncClient):
        """GET /auth/login without connection does not pass connection kwarg."""
        with patch("canon.auth.routes.oauth") as mock_oauth:
            mock_oauth.auth0.authorize_redirect = AsyncMock(
                return_value=RedirectResponse(
                    "https://test.us.auth0.com/authorize?client_id=test-client-id"
                )
            )
            resp = await client.get("/auth/login")
            assert resp.status_code == 307
            call_kwargs = mock_oauth.auth0.authorize_redirect.call_args
            assert "connection" not in call_kwargs.kwargs


class TestCallback:
    async def test_callback_sets_session(self, client: AsyncClient):
        """GET /auth/callback should exchange code and redirect to /app."""
        with patch("canon.auth.routes.oauth") as mock_oauth:
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "auth0|123",
                        "email": "test@example.com",
                        "name": "Test User",
                        "picture": "https://example.com/pic.jpg",
                    },
                }
            )
            resp = await client.get("/auth/callback")
            assert resp.status_code == 307
            assert resp.headers["location"] == "/app"

    async def test_callback_with_org_redirects_to_org_dashboard(self):
        """Callback with org context redirects to /app/{org}/ via login_org."""
        from starlette.testclient import TestClient

        with (
            patch("canon.auth.routes.oauth") as mock_oauth,
            patch("canon.main._get_client", return_value=_mock_client()),
        ):
            mock_oauth.auth0.authorize_redirect = AsyncMock(
                return_value=RedirectResponse("https://test.us.auth0.com/authorize"),
            )
            # Build a real JWT string with org_id + permissions claims
            # (signature verification is skipped in the callback)
            _access_token = pyjwt.encode(
                {"org_id": "org_abc", "permissions": ["specs:read", "specs:write"]},
                "test-secret",
                algorithm="HS256",
            )
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "auth0|123",
                        "email": "test@example.com",
                        "name": "Test",
                        "picture": "",
                    },
                    "access_token": _access_token,
                }
            )

            with TestClient(app) as tc:
                # Set settings AFTER TestClient enters (lifespan overwrites app.state.settings)
                app.state.settings = Settings(
                    web_org="test-org",
                    auth0_domain="test.us.auth0.com",
                    auth0_client_id="test-client-id",
                    auth0_client_secret="test-client-secret",
                    auth0_audience="https://canon.example.com/api",
                )
                # Login with org param — this sets login_org in session
                resp = tc.get("/auth/login?org=my-org", follow_redirects=False)
                assert resp.status_code == 307

                # Callback — should read login_org from session
                resp = tc.get("/auth/callback", follow_redirects=False)
                assert resp.status_code == 307
                # Should redirect to org dashboard since login_org was set
                assert "/app/my-org/" in resp.headers["location"]

    async def test_callback_upserts_user_when_store_available(self):
        """Callback upserts user to DB when user_store is present."""
        from starlette.testclient import TestClient

        mock_user_store = AsyncMock()
        mock_user_store.upsert_user = AsyncMock(return_value={"id": 1})

        with (
            patch("canon.auth.routes.oauth") as mock_oauth,
            patch("canon.main._get_client", return_value=_mock_client()),
        ):
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "auth0|123",
                        "email": "test@example.com",
                        "name": "Test",
                        "picture": "",
                    },
                }
            )
            with TestClient(app) as tc:
                app.state.settings = Settings(
                    web_org="test-org",
                    auth0_domain="test.us.auth0.com",
                    auth0_client_id="test-client-id",
                    auth0_client_secret="test-client-secret",
                )
                app.state.user_store = mock_user_store
                tc.get("/auth/callback", follow_redirects=False)

            mock_user_store.upsert_user.assert_awaited_once()
        app.state.user_store = None

    async def test_callback_redirects_new_user_to_welcome(self):
        """New user (is_new=True) gets redirected to /app/{org}/welcome."""
        from starlette.testclient import TestClient

        mock_user_store = AsyncMock()
        mock_user_store.upsert_user = AsyncMock(return_value={"id": 1, "is_new": True})

        with (
            patch("canon.auth.routes.oauth") as mock_oauth,
            patch("canon.main._get_client", return_value=_mock_client()),
        ):
            mock_oauth.auth0.authorize_redirect = AsyncMock(
                return_value=RedirectResponse("https://test.us.auth0.com/authorize"),
            )
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "auth0|new",
                        "email": "new@example.com",
                        "name": "New User",
                        "picture": "",
                    },
                }
            )

            with TestClient(app) as tc:
                app.state.settings = Settings(
                    web_org="test-org",
                    auth0_domain="test.us.auth0.com",
                    auth0_client_id="test-client-id",
                    auth0_client_secret="test-client-secret",
                    auth0_audience="https://canon.example.com/api",
                )
                app.state.user_store = mock_user_store
                # Login with org param — sets login_org in session
                tc.get("/auth/login?org=my-org", follow_redirects=False)
                # Callback should redirect new user to welcome
                resp = tc.get("/auth/callback", follow_redirects=False)
                assert resp.status_code == 307
                assert "/app/my-org/welcome" in resp.headers["location"]

            app.state.user_store = None

    async def test_callback_redirects_returning_user_to_dashboard(self):
        """Returning user (is_new=False) gets redirected to /app/{org}/."""
        from starlette.testclient import TestClient

        mock_user_store = AsyncMock()
        mock_user_store.upsert_user = AsyncMock(return_value={"id": 1, "is_new": False})

        with (
            patch("canon.auth.routes.oauth") as mock_oauth,
            patch("canon.main._get_client", return_value=_mock_client()),
        ):
            mock_oauth.auth0.authorize_redirect = AsyncMock(
                return_value=RedirectResponse("https://test.us.auth0.com/authorize"),
            )
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "auth0|existing",
                        "email": "existing@example.com",
                        "name": "Existing User",
                        "picture": "",
                    },
                }
            )

            with TestClient(app) as tc:
                app.state.settings = Settings(
                    web_org="test-org",
                    auth0_domain="test.us.auth0.com",
                    auth0_client_id="test-client-id",
                    auth0_client_secret="test-client-secret",
                    auth0_audience="https://canon.example.com/api",
                )
                app.state.user_store = mock_user_store
                tc.get("/auth/login?org=my-org", follow_redirects=False)
                resp = tc.get("/auth/callback", follow_redirects=False)
                assert resp.status_code == 307
                location = resp.headers["location"]
                assert location.endswith("/app/my-org/")
                assert "welcome" not in location

            app.state.user_store = None

    async def test_callback_first_user_promoted_to_admin(self):
        """When the first user signs up, promote_first_user_to_admin is called atomically."""
        from starlette.testclient import TestClient

        mock_user_store = AsyncMock()
        mock_user_store.upsert_user = AsyncMock(return_value={"id": 1, "is_new": True})
        mock_user_store.promote_first_user_to_admin = AsyncMock(return_value=True)

        with (
            patch("canon.auth.routes.oauth") as mock_oauth,
            patch("canon.main._get_client", return_value=_mock_client()),
        ):
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "auth0|first",
                        "email": "first@example.com",
                        "name": "First User",
                        "picture": "",
                    },
                }
            )
            with TestClient(app) as tc:
                app.state.settings = Settings(
                    web_org="test-org",
                    auth0_domain="test.us.auth0.com",
                    auth0_client_id="test-client-id",
                    auth0_client_secret="test-client-secret",
                )
                app.state.user_store = mock_user_store
                tc.get("/auth/callback", follow_redirects=False)

            mock_user_store.promote_first_user_to_admin.assert_awaited_once_with(1)
        app.state.user_store = None

    async def test_callback_second_user_not_promoted_to_admin(self):
        """When a non-new user signs up, promote_first_user_to_admin is NOT called."""
        from starlette.testclient import TestClient

        mock_user_store = AsyncMock()
        mock_user_store.upsert_user = AsyncMock(return_value={"id": 2, "is_new": False})
        mock_user_store.promote_first_user_to_admin = AsyncMock(return_value=False)

        with (
            patch("canon.auth.routes.oauth") as mock_oauth,
            patch("canon.main._get_client", return_value=_mock_client()),
        ):
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "auth0|second",
                        "email": "second@example.com",
                        "name": "Second User",
                        "picture": "",
                    },
                }
            )
            with TestClient(app) as tc:
                app.state.settings = Settings(
                    web_org="test-org",
                    auth0_domain="test.us.auth0.com",
                    auth0_client_id="test-client-id",
                    auth0_client_secret="test-client-secret",
                )
                app.state.user_store = mock_user_store
                tc.get("/auth/callback", follow_redirects=False)

            mock_user_store.promote_first_user_to_admin.assert_not_awaited()
        app.state.user_store = None

    async def test_callback_populates_github_user_from_custom_claim(self):
        """Callback with GitHub custom claim populates session['github_user'].

        Verifies via the /api/session endpoint which reads github_user from
        the session — TestClient preserves cookies between requests.
        """
        from starlette.testclient import TestClient

        with (
            patch("canon.auth.routes.oauth") as mock_oauth,
            patch("canon.main._get_client", return_value=_mock_client()),
        ):
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "github|456",
                        "email": "dev@example.com",
                        "name": "Dev User",
                        "picture": "",
                        "https://canonhq.co/github": {
                            "token": "ghu_abc123",
                            "login": "devuser",
                            "name": "Dev User",
                            "avatar_url": "https://avatars.githubusercontent.com/u/456",
                        },
                    },
                }
            )
            with TestClient(app) as tc:
                app.state.settings = Settings(
                    web_org="test-org",
                    auth0_domain="test.us.auth0.com",
                    auth0_client_id="test-client-id",
                    auth0_client_secret="test-client-secret",
                )
                tc.get("/auth/callback", follow_redirects=False)

                # Session endpoint exposes github_user — verify it was populated
                session_resp = tc.get("/app/test-org/api/session")
                data = session_resp.json()
                assert data["github_user"] is not None
                assert data["github_user"]["login"] == "devuser"
                assert data["github_user"]["name"] == "Dev User"

    async def test_callback_skips_github_user_when_no_claim(self, client: AsyncClient):
        """Callback without GitHub claim doesn't set github_user."""
        with patch("canon.auth.routes.oauth") as mock_oauth:
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "auth0|123",
                        "email": "test@example.com",
                        "name": "Test",
                        "picture": "",
                    },
                }
            )
            resp = await client.get("/auth/callback")
            assert resp.status_code == 307

    async def test_callback_skips_github_user_when_token_empty(self, client: AsyncClient):
        """Callback with GitHub claim but empty token doesn't set github_user."""
        with patch("canon.auth.routes.oauth") as mock_oauth:
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "github|456",
                        "email": "dev@example.com",
                        "name": "Dev",
                        "picture": "",
                        "https://canonhq.co/github": {
                            "token": "",
                            "login": "devuser",
                            "name": "Dev",
                            "avatar_url": "",
                        },
                    },
                }
            )
            resp = await client.get("/auth/callback")
            assert resp.status_code == 307


class TestLogout:
    async def test_logout_redirects_to_auth0(self, client: AsyncClient):
        """GET /auth/logout should redirect to the provider's logout endpoint."""
        resp = await client.get("/auth/logout")
        assert resp.status_code == 307
        location = resp.headers["location"]
        assert "test.us.auth0.com/v2/logout" in location
        assert "client_id=test-client-id" in location

    async def test_logout_falls_back_to_home_when_no_provider(self, client: AsyncClient):
        """When no provider is configured, logout redirects to /."""
        app.state.oidc_provider = None
        resp = await client.get("/auth/logout")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/"

    async def test_logout_clears_github_user(self):
        """Logout clears both user and github_user from session."""
        from starlette.testclient import TestClient

        with (
            patch("canon.auth.routes.oauth") as mock_oauth,
            patch("canon.main._get_client", return_value=_mock_client()),
        ):
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "github|456",
                        "email": "dev@example.com",
                        "name": "Dev",
                        "picture": "",
                        "https://canonhq.co/github": {
                            "token": "ghu_abc123",
                            "login": "devuser",
                            "name": "Dev",
                            "avatar_url": "",
                        },
                    },
                }
            )
            with TestClient(app) as tc:
                app.state.settings = Settings(
                    web_org="test-org",
                    auth0_domain="test.us.auth0.com",
                    auth0_client_id="test-client-id",
                    auth0_client_secret="test-client-secret",
                )
                app.state.oidc_provider = _mock_provider()
                # Login to set session
                tc.get("/auth/callback", follow_redirects=False)
                # Logout should clear everything
                resp = tc.get("/auth/logout", follow_redirects=False)
                assert resp.status_code == 307
                assert "test.us.auth0.com/v2/logout" in resp.headers["location"]
