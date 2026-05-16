"""Tests for auth middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
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


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


class TestAuthMiddlewareEnabled:
    """Tests with auth0 configured — /app/* should require session."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        app.state.settings = Settings(
            web_org="test-org",
            auth0_domain="test.us.auth0.com",
            auth0_client_id="test-client-id",
            auth0_client_secret="test-client-secret",
        )
        app.state.cache = TTLCache(ttl_seconds=60)
        app.state.github_client = _mock_client()

    async def test_app_routes_redirect_when_no_session(self, client: AsyncClient):
        resp = await client.get("/app")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/auth/login"

    async def test_app_subroutes_redirect(self, client: AsyncClient):
        resp = await client.get("/app/repos/org/repo")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/auth/login"

    async def test_api_request_returns_401_not_redirect(self, client: AsyncClient):
        """API requests (Accept: application/json) get 401 instead of redirect."""
        resp = await client.get(
            "/app/test-org/api/profile",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["detail"] == "Not authenticated"

    async def test_api_path_returns_401_without_accept_header(self, client: AsyncClient):
        """Unauthenticated /app/{org}/api/* returns 401 even without Accept header."""
        resp = await client.get("/app/test-org/api/session")
        assert resp.status_code == 401
        body = resp.json()
        assert body["detail"] == "Not authenticated"

    async def test_non_api_path_still_redirects(self, client: AsyncClient):
        """Non-API paths without Accept header still redirect to login."""
        resp = await client.get("/app/test-org/dashboard")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/auth/login"

    async def test_public_routes_unaffected(self, client: AsyncClient):
        """Health, readyz, and webhook routes remain public."""
        app.state.db_pool = None
        resp = await client.get("/healthz")
        assert resp.status_code == 200

        resp = await client.get("/readyz")
        assert resp.status_code == 200

    async def test_landing_page_unaffected(self, client: AsyncClient):
        resp = await client.get("/")
        assert resp.status_code == 200

    async def test_app_routes_pass_with_valid_session(self):
        """Authenticated session allows /app access."""
        from unittest.mock import patch

        from starlette.testclient import TestClient

        # Go through the callback to set a real signed session cookie
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
            with TestClient(app, cookies={}) as tc:
                app.state.settings = Settings(
                    web_org="test-org",
                    auth0_domain="test.us.auth0.com",
                    auth0_client_id="test-client-id",
                    auth0_client_secret="test-client-secret",
                )
                # Hit callback to set session
                resp = tc.get("/auth/callback", follow_redirects=False)
                assert resp.status_code == 307
                # Now use the session cookie to access /app/
                resp = tc.get("/app/")
                assert resp.status_code == 200


class TestAuthMiddlewareDisabled:
    """Tests without auth0 configured — everything works as before."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        app.state.settings = Settings(web_org="test-org")
        app.state.cache = TTLCache(ttl_seconds=60)
        app.state.github_client = _mock_client()

    async def test_app_routes_pass_without_auth(self, client: AsyncClient):
        # follow_redirects=False but /app should return 200 or at least not 307→/auth/login
        follow_client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
        )
        resp = await follow_client.get("/app")
        assert resp.status_code == 200

    async def test_public_routes_still_work(self, client: AsyncClient):
        app.state.db_pool = None
        resp = await client.get("/healthz")
        assert resp.status_code == 200


class TestTenantIsolation:
    """Tests with Auth0 Organizations mode — enforce org matching."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        app.state.settings = Settings(
            web_org="test-org",
            auth0_domain="test.us.auth0.com",
            auth0_client_id="test-client-id",
            auth0_client_secret="test-client-secret",
            auth0_audience="https://canon.example.com/api",
            auth0_orgs_enabled=True,
        )
        app.state.cache = TTLCache(ttl_seconds=60)
        app.state.github_client = _mock_client()

    async def test_org_mismatch_redirects_to_login(self):
        """User without verified org membership cannot access any org's dashboard."""
        from unittest.mock import patch

        from starlette.testclient import TestClient

        with (
            patch("canon.auth.routes.oauth") as mock_oauth,
            patch("canon.main._get_client", return_value=_mock_client()),
        ):
            # Token has NO org_id claim — user is not a member of any org.
            mock_oauth.auth0.authorize_redirect = AsyncMock(
                side_effect=lambda req, uri, **kw: __import__(
                    "fastapi.responses", fromlist=["RedirectResponse"]
                ).RedirectResponse("https://auth0.example.com/authorize"),
            )
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
            with TestClient(app, cookies={}) as tc:
                app.state.settings = Settings(
                    web_org="test-org",
                    auth0_domain="test.us.auth0.com",
                    auth0_client_id="test-client-id",
                    auth0_client_secret="test-client-secret",
                    auth0_audience="https://canon.example.com/api",
                    auth0_orgs_enabled=True,
                )
                # Login with org param — stores login_org in session
                tc.get("/auth/login?org=my-org", follow_redirects=False)
                # Callback — login_org is NOT trusted as org_login anymore.
                # Without org_id in token and no GitHub membership, user goes to no-org.
                resp = tc.get("/auth/callback", follow_redirects=False)
                assert resp.status_code == 307
                assert "/app/no-org" in resp.headers["location"]

                # Accessing /app/other-org/ → should redirect because org doesn't match
                resp = tc.get("/app/other-org/", follow_redirects=False)
                assert resp.status_code == 307
                assert "/auth/login" in resp.headers["location"]

    async def test_admin_routes_bypass_org_check(self):
        """Admin routes (/app/admin/*) should not be blocked by org matching.

        The middleware allows /app/admin/* through without org comparison,
        even when auth0_orgs_enabled is true.
        """
        from unittest.mock import patch

        from starlette.testclient import TestClient

        with (
            patch("canon.auth.routes.oauth") as mock_oauth,
            patch("canon.main._get_client", return_value=_mock_client()),
        ):
            mock_oauth.auth0.authorize_access_token = AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "auth0|admin",
                        "email": "admin@example.com",
                        "name": "Admin",
                        "picture": "",
                    },
                    "access_token_claims": {
                        "permissions": [
                            "specs:read",
                            "specs:write",
                            "specs:admin",
                            "org:manage",
                        ],
                    },
                }
            )
            with TestClient(app, cookies={}) as tc:
                resp = tc.get("/auth/callback", follow_redirects=False)
                assert resp.status_code == 307
                # Admin indexing page — middleware should not redirect to /auth/login
                # The route itself may return 200 or an error, but NOT a 307 auth redirect
                resp = tc.get("/app/admin/indexing", follow_redirects=False)
                assert resp.status_code != 307 or "/auth/login" not in resp.headers.get(
                    "location", ""
                )

    async def test_api_key_cross_org_blocked(self, client: AsyncClient):
        """API key scoped to org-a cannot access /app/org-b/ routes."""
        mock_user_store = AsyncMock()
        key = "sw_testcrossorg"
        mock_user_store.get_api_key_by_hash = AsyncMock(
            return_value={
                "user_sub": "auth0|456",
                "user_email": "api@example.com",
                "user_name": "API User",
                "org_login": "org-a",
                "scopes": ["specs:read"],
                "revoked_at": None,
                "expires_at": None,
            }
        )
        app.state.user_store = mock_user_store

        # API key is for org-a, but requesting org-b
        resp = await client.get(
            "/app/org-b/",
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
            },
        )
        assert resp.status_code == 403
        app.state.user_store = None

    async def test_deactivated_user_blocked_via_api_key(self, client: AsyncClient):
        """Deactivated users should be blocked from API key access."""
        mock_user_store = AsyncMock()
        mock_user_store.get_api_key_by_hash = AsyncMock(
            return_value={
                "user_sub": "auth0|deactivated",
                "user_email": "deactivated@example.com",
                "user_name": "Deactivated",
                "org_login": "test-org",
                "scopes": ["specs:read"],
                "revoked_at": None,
                "expires_at": None,
                "user_id": 42,
                "user_status": "deactivated",
            }
        )
        app.state.user_store = mock_user_store

        resp = await client.get(
            "/app/test-org/api/profile",
            headers={
                "Authorization": "Bearer sw_testkey",
                "Accept": "application/json",
            },
        )
        assert resp.status_code == 403
        app.state.user_store = None

    async def test_api_key_same_org_allowed(self, client: AsyncClient):
        """API key scoped to org-a CAN access /app/org-a/ routes."""
        from unittest.mock import patch

        mock_user_store = AsyncMock()
        key = "sw_testsameorg"
        mock_user_store.get_api_key_by_hash = AsyncMock(
            return_value={
                "user_sub": "auth0|456",
                "user_email": "api@example.com",
                "user_name": "API User",
                "org_login": "my-org",
                "scopes": ["specs:read"],
                "revoked_at": None,
                "expires_at": None,
            }
        )
        app.state.user_store = mock_user_store

        with patch("canon.main._get_client", return_value=_mock_client()):
            resp = await client.get(
                "/app/my-org/",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Accept": "text/html",
                },
            )
        # Should NOT be a 403 or redirect to /auth/login
        assert resp.status_code != 403
        assert resp.status_code != 307 or "/auth/login" not in resp.headers.get("location", "")
        app.state.user_store = None
