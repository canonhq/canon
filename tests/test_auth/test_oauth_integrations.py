"""Tests for OAuth integration routes (Jira Cloud and Linear OAuth flows)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from canon.auth.models import CurrentUser
from canon.auth.oauth_integrations import _check_org_ownership, oauth_integration_router
from canon.auth.permissions import Permission
from canon.settings import Settings


def _admin_user(org_login: str = "test-org") -> CurrentUser:
    """Build a CurrentUser with ORG_MANAGE permission."""
    return CurrentUser(
        sub="auth0|admin",
        email="admin@example.com",
        name="Admin User",
        org_id="org_123",
        org_login=org_login,
        permissions=frozenset(
            {Permission.ORG_MANAGE, Permission.SPECS_READ, Permission.SPECS_WRITE}
        ),
        auth_method="session",
    )


def _make_mini_app(settings: Settings | None = None) -> FastAPI:
    """Create a minimal FastAPI app with the OAuth router and session middleware.

    This avoids the full app's lifespan (which resets state) and auth
    middleware (which intercepts /app/* routes before the handler runs).
    """
    mini = FastAPI()
    mini.add_middleware(SessionMiddleware, secret_key="test-secret")
    mini.include_router(oauth_integration_router)

    if settings is None:
        settings = Settings(
            web_org="test-org",
            auth0_domain="test.us.auth0.com",
            auth0_client_id="test-client-id",
            auth0_client_secret="test-client-secret",
            jira_oauth_client_id="jira-client-id",
            jira_oauth_client_secret="jira-client-secret",
            linear_oauth_client_id="linear-client-id",
            linear_oauth_client_secret="linear-client-secret",
        )

    mini.state.settings = settings
    mini.state.integration_store = None
    mini.state.user_store = None
    return mini


class TestCheckOrgOwnership:
    """Unit tests for _check_org_ownership helper."""

    def test_passes_when_org_matches(self):
        """No exception when user.org_login matches the requested org."""
        user = _admin_user(org_login="my-org")
        _check_org_ownership(user, "my-org")  # should not raise

    def test_raises_403_when_org_mismatches(self):
        """HTTPException 403 when user tries to configure another org."""
        from fastapi import HTTPException

        user = _admin_user(org_login="my-org")
        with pytest.raises(HTTPException) as exc_info:
            _check_org_ownership(user, "other-org")
        assert exc_info.value.status_code == 403


class TestJiraConnect:
    """Tests for the Jira OAuth connect initiation route."""

    async def test_redirects_to_jira_auth(self):
        """Jira connect should redirect to Atlassian authorization URL."""
        mini = _make_mini_app()
        async with AsyncClient(
            transport=ASGITransport(app=mini), base_url="http://test", follow_redirects=False
        ) as client:
            with patch("canon.auth.deps.get_current_user", AsyncMock(return_value=_admin_user())):
                resp = await client.get("/app/test-org/api/settings/integrations/jira/connect")

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "auth.atlassian.com/authorize" in location
        assert "jira-client-id" in location

    async def test_redirects_with_error_when_not_configured(self):
        """When jira_oauth_client_id is empty, redirect with error."""
        mini = _make_mini_app(
            Settings(
                web_org="test-org",
                auth0_domain="test.us.auth0.com",
                auth0_client_id="test-client-id",
                auth0_client_secret="test-client-secret",
                jira_oauth_client_id="",
            )
        )
        async with AsyncClient(
            transport=ASGITransport(app=mini), base_url="http://test", follow_redirects=False
        ) as client:
            with patch("canon.auth.deps.get_current_user", AsyncMock(return_value=_admin_user())):
                resp = await client.get("/app/test-org/api/settings/integrations/jira/connect")

        assert resp.status_code == 302
        assert "error=jira_not_configured" in resp.headers["location"]

    async def test_rejects_different_org(self):
        """Connecting Jira for a different org should be forbidden."""
        mini = _make_mini_app()
        async with AsyncClient(
            transport=ASGITransport(app=mini), base_url="http://test", follow_redirects=False
        ) as client:
            with patch(
                "canon.auth.deps.get_current_user",
                AsyncMock(return_value=_admin_user(org_login="my-org")),
            ):
                resp = await client.get("/app/other-org/api/settings/integrations/jira/connect")

        assert resp.status_code == 403


class TestJiraCallback:
    """Tests for the Jira OAuth callback route."""

    def test_state_mismatch_redirects_with_error(self):
        """State mismatch redirects back with error=state_mismatch."""
        mini = _make_mini_app()
        with TestClient(mini) as tc:
            resp = tc.get(
                "/auth/integrations/jira/callback?code=test-code&state=wrong-state",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert "error=state_mismatch" in resp.headers["location"]

    @patch("canon.auth.oauth_integrations.register_jira_webhook", new_callable=AsyncMock)
    def test_successful_callback_stores_integration(self, mock_register_webhook):
        """Successful Jira callback exchanges code, fetches resources, and upserts integration."""
        import httpx
        import respx

        mock_register_webhook.return_value = {"webhook_id": "wh-123"}

        mini = _make_mini_app()

        mock_integration_store = AsyncMock()
        mock_integration_store.upsert_integration = AsyncMock()
        mini.state.integration_store = mock_integration_store
        mini.state.settings.canon_base_url = "https://canonhq.co"

        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value={"id": 1})
        mini.state.user_store = mock_user_store

        with respx.mock:
            # Mock token exchange
            respx.post("https://auth.atlassian.com/oauth/token").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "access_token": "jira-access-token",
                        "refresh_token": "jira-refresh-token",
                    },
                )
            )
            # Mock accessible resources
            respx.get("https://api.atlassian.com/oauth/token/accessible-resources").mock(
                return_value=httpx.Response(
                    200,
                    json=[
                        {
                            "id": "cloud-123",
                            "url": "https://mysite.atlassian.net",
                            "name": "My Jira Site",
                        }
                    ],
                )
            )

            with TestClient(mini) as tc:
                # Initiate connect to set session state
                with patch(
                    "canon.auth.deps.get_current_user",
                    AsyncMock(return_value=_admin_user()),
                ):
                    resp = tc.get(
                        "/app/test-org/api/settings/integrations/jira/connect",
                        follow_redirects=False,
                    )
                    assert resp.status_code == 302

                # Extract state from the redirect URL
                from urllib.parse import parse_qs, urlparse

                location = resp.headers["location"]
                parsed = urlparse(location)
                params = parse_qs(parsed.query)
                state = params.get("state", [""])[0]

                resp = tc.get(
                    f"/auth/integrations/jira/callback?code=test-code&state={state}",
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                assert "connected=jira" in resp.headers["location"]

        mock_integration_store.upsert_integration.assert_awaited_once()
        call_kwargs = mock_integration_store.upsert_integration.call_args.kwargs
        assert call_kwargs["org_login"] == "test-org"
        assert call_kwargs["provider"] == "jira"
        assert call_kwargs["display_name"] == "My Jira Site"
        assert call_kwargs["config"]["access_token"] == "jira-access-token"
        assert call_kwargs["config"]["refresh_token"] == "jira-refresh-token"
        assert call_kwargs["config"]["cloud_id"] == "cloud-123"

    def test_callback_no_sites_redirects_with_error(self):
        """When Jira returns no accessible resources, redirect with error."""
        import httpx
        import respx

        mini = _make_mini_app()

        with respx.mock:
            respx.post("https://auth.atlassian.com/oauth/token").mock(
                return_value=httpx.Response(
                    200,
                    json={"access_token": "jira-token", "refresh_token": "jira-rt"},
                )
            )
            respx.get("https://api.atlassian.com/oauth/token/accessible-resources").mock(
                return_value=httpx.Response(200, json=[])
            )

            with TestClient(mini) as tc:
                with patch(
                    "canon.auth.deps.get_current_user",
                    AsyncMock(return_value=_admin_user()),
                ):
                    resp = tc.get(
                        "/app/test-org/api/settings/integrations/jira/connect",
                        follow_redirects=False,
                    )

                from urllib.parse import parse_qs, urlparse

                location = resp.headers["location"]
                parsed = urlparse(location)
                params = parse_qs(parsed.query)
                state = params.get("state", [""])[0]

                resp = tc.get(
                    f"/auth/integrations/jira/callback?code=test-code&state={state}",
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                assert "error=jira_no_sites" in resp.headers["location"]

    def test_callback_no_integration_store_redirects_with_error(self):
        """When integration_store is not available, redirect with db error."""
        import httpx
        import respx

        mini = _make_mini_app()
        mini.state.integration_store = None

        with respx.mock:
            respx.post("https://auth.atlassian.com/oauth/token").mock(
                return_value=httpx.Response(
                    200,
                    json={"access_token": "jira-token", "refresh_token": "jira-rt"},
                )
            )
            respx.get("https://api.atlassian.com/oauth/token/accessible-resources").mock(
                return_value=httpx.Response(
                    200,
                    json=[{"id": "cloud-1", "url": "https://site.atlassian.net", "name": "Site"}],
                )
            )

            with TestClient(mini) as tc:
                with patch(
                    "canon.auth.deps.get_current_user",
                    AsyncMock(return_value=_admin_user()),
                ):
                    resp = tc.get(
                        "/app/test-org/api/settings/integrations/jira/connect",
                        follow_redirects=False,
                    )

                from urllib.parse import parse_qs, urlparse

                location = resp.headers["location"]
                parsed = urlparse(location)
                params = parse_qs(parsed.query)
                state = params.get("state", [""])[0]

                resp = tc.get(
                    f"/auth/integrations/jira/callback?code=test-code&state={state}",
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                assert "error=db_not_configured" in resp.headers["location"]

    def test_callback_token_exchange_failure(self):
        """When token exchange fails, redirect with oauth_failed error."""
        import httpx
        import respx

        mini = _make_mini_app()

        with respx.mock:
            respx.post("https://auth.atlassian.com/oauth/token").mock(
                return_value=httpx.Response(400, json={"error": "invalid_grant"})
            )

            with TestClient(mini) as tc:
                with patch(
                    "canon.auth.deps.get_current_user",
                    AsyncMock(return_value=_admin_user()),
                ):
                    resp = tc.get(
                        "/app/test-org/api/settings/integrations/jira/connect",
                        follow_redirects=False,
                    )

                from urllib.parse import parse_qs, urlparse

                location = resp.headers["location"]
                parsed = urlparse(location)
                params = parse_qs(parsed.query)
                state = params.get("state", [""])[0]

                resp = tc.get(
                    f"/auth/integrations/jira/callback?code=test-code&state={state}",
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                assert "error=jira_oauth_failed" in resp.headers["location"]


class TestLinearConnect:
    """Tests for the Linear OAuth connect initiation route."""

    async def test_redirects_to_linear_auth(self):
        """Linear connect should redirect to Linear authorization URL."""
        mini = _make_mini_app()
        async with AsyncClient(
            transport=ASGITransport(app=mini), base_url="http://test", follow_redirects=False
        ) as client:
            with patch("canon.auth.deps.get_current_user", AsyncMock(return_value=_admin_user())):
                resp = await client.get("/app/test-org/api/settings/integrations/linear/connect")

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "linear.app/oauth/authorize" in location
        assert "linear-client-id" in location

    async def test_redirects_with_error_when_not_configured(self):
        """When linear_oauth_client_id is empty, redirect with error."""
        mini = _make_mini_app(
            Settings(
                web_org="test-org",
                auth0_domain="test.us.auth0.com",
                auth0_client_id="test-client-id",
                auth0_client_secret="test-client-secret",
                linear_oauth_client_id="",
            )
        )
        async with AsyncClient(
            transport=ASGITransport(app=mini), base_url="http://test", follow_redirects=False
        ) as client:
            with patch("canon.auth.deps.get_current_user", AsyncMock(return_value=_admin_user())):
                resp = await client.get("/app/test-org/api/settings/integrations/linear/connect")

        assert resp.status_code == 302
        assert "error=linear_not_configured" in resp.headers["location"]

    async def test_rejects_different_org(self):
        """Connecting Linear for a different org should be forbidden."""
        mini = _make_mini_app()
        async with AsyncClient(
            transport=ASGITransport(app=mini), base_url="http://test", follow_redirects=False
        ) as client:
            with patch(
                "canon.auth.deps.get_current_user",
                AsyncMock(return_value=_admin_user(org_login="my-org")),
            ):
                resp = await client.get("/app/other-org/api/settings/integrations/linear/connect")

        assert resp.status_code == 403


class TestLinearCallback:
    """Tests for the Linear OAuth callback route."""

    def test_state_mismatch_redirects_with_error(self):
        """State mismatch redirects back with error=state_mismatch."""
        mini = _make_mini_app()
        with TestClient(mini) as tc:
            resp = tc.get(
                "/auth/integrations/linear/callback?code=test-code&state=wrong-state",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert "error=state_mismatch" in resp.headers["location"]

    @patch("canon.auth.oauth_integrations.register_linear_webhook", new_callable=AsyncMock)
    def test_successful_callback_stores_integration(self, mock_register_webhook):
        """Successful Linear callback exchanges code, fetches workspace, and upserts integration."""
        import httpx
        import respx

        mock_register_webhook.return_value = {"webhook_id": "wh-456", "webhook_secret": "ws-secret"}

        mini = _make_mini_app()

        mock_integration_store = AsyncMock()
        mock_integration_store.upsert_integration = AsyncMock()
        mini.state.integration_store = mock_integration_store
        mini.state.settings.canon_base_url = "https://canonhq.co"

        mock_user_store = AsyncMock()
        mock_user_store.get_user_by_sub = AsyncMock(return_value={"id": 1})
        mini.state.user_store = mock_user_store

        with respx.mock:
            # Mock token exchange
            respx.post("https://api.linear.app/oauth/token").mock(
                return_value=httpx.Response(
                    200,
                    json={"access_token": "linear-access-token"},
                )
            )
            # Mock GraphQL workspace query
            respx.post("https://api.linear.app/graphql").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "data": {
                            "viewer": {
                                "organization": {
                                    "id": "ws-123",
                                    "name": "My Linear Workspace",
                                }
                            }
                        }
                    },
                )
            )

            with TestClient(mini) as tc:
                with patch(
                    "canon.auth.deps.get_current_user",
                    AsyncMock(return_value=_admin_user()),
                ):
                    resp = tc.get(
                        "/app/test-org/api/settings/integrations/linear/connect",
                        follow_redirects=False,
                    )
                    assert resp.status_code == 302

                from urllib.parse import parse_qs, urlparse

                location = resp.headers["location"]
                parsed = urlparse(location)
                params = parse_qs(parsed.query)
                state = params.get("state", [""])[0]

                resp = tc.get(
                    f"/auth/integrations/linear/callback?code=test-code&state={state}",
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                assert "connected=linear" in resp.headers["location"]

        mock_integration_store.upsert_integration.assert_awaited_once()
        call_kwargs = mock_integration_store.upsert_integration.call_args.kwargs
        assert call_kwargs["org_login"] == "test-org"
        assert call_kwargs["provider"] == "linear"
        assert call_kwargs["display_name"] == "My Linear Workspace"
        assert call_kwargs["config"]["access_token"] == "linear-access-token"
        assert call_kwargs["config"]["workspace_id"] == "ws-123"
        assert call_kwargs["config"]["webhook_secret"] == "ws-secret"

    def test_callback_no_integration_store_redirects_with_error(self):
        """When integration_store is not available, redirect with db error."""
        import httpx
        import respx

        mini = _make_mini_app()
        mini.state.integration_store = None

        with respx.mock:
            respx.post("https://api.linear.app/oauth/token").mock(
                return_value=httpx.Response(200, json={"access_token": "linear-token"})
            )
            respx.post("https://api.linear.app/graphql").mock(
                return_value=httpx.Response(
                    200,
                    json={"data": {"viewer": {"organization": {"id": "ws-1", "name": "WS"}}}},
                )
            )

            with TestClient(mini) as tc:
                with patch(
                    "canon.auth.deps.get_current_user",
                    AsyncMock(return_value=_admin_user()),
                ):
                    resp = tc.get(
                        "/app/test-org/api/settings/integrations/linear/connect",
                        follow_redirects=False,
                    )

                from urllib.parse import parse_qs, urlparse

                location = resp.headers["location"]
                parsed = urlparse(location)
                params = parse_qs(parsed.query)
                state = params.get("state", [""])[0]

                resp = tc.get(
                    f"/auth/integrations/linear/callback?code=test-code&state={state}",
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                assert "error=db_not_configured" in resp.headers["location"]

    def test_callback_token_exchange_failure(self):
        """When token exchange fails, redirect with oauth_failed error."""
        import httpx
        import respx

        mini = _make_mini_app()

        with respx.mock:
            respx.post("https://api.linear.app/oauth/token").mock(
                return_value=httpx.Response(400, json={"error": "invalid_grant"})
            )

            with TestClient(mini) as tc:
                with patch(
                    "canon.auth.deps.get_current_user",
                    AsyncMock(return_value=_admin_user()),
                ):
                    resp = tc.get(
                        "/app/test-org/api/settings/integrations/linear/connect",
                        follow_redirects=False,
                    )

                from urllib.parse import parse_qs, urlparse

                location = resp.headers["location"]
                parsed = urlparse(location)
                params = parse_qs(parsed.query)
                state = params.get("state", [""])[0]

                resp = tc.get(
                    f"/auth/integrations/linear/callback?code=test-code&state={state}",
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                assert "error=linear_oauth_failed" in resp.headers["location"]

    @patch("canon.auth.oauth_integrations.register_linear_webhook", new_callable=AsyncMock)
    def test_callback_webhook_failure_non_fatal(self, mock_register_webhook):
        """Webhook registration failure should not break the callback."""
        import httpx
        import respx

        mock_register_webhook.side_effect = Exception("webhook registration failed")

        mini = _make_mini_app()

        mock_integration_store = AsyncMock()
        mock_integration_store.upsert_integration = AsyncMock()
        mini.state.integration_store = mock_integration_store
        mini.state.settings.canon_base_url = "https://canonhq.co"

        with respx.mock:
            respx.post("https://api.linear.app/oauth/token").mock(
                return_value=httpx.Response(200, json={"access_token": "linear-token"})
            )
            respx.post("https://api.linear.app/graphql").mock(
                return_value=httpx.Response(
                    200,
                    json={"data": {"viewer": {"organization": {"id": "ws-1", "name": "WS"}}}},
                )
            )

            with TestClient(mini) as tc:
                with patch(
                    "canon.auth.deps.get_current_user",
                    AsyncMock(return_value=_admin_user()),
                ):
                    resp = tc.get(
                        "/app/test-org/api/settings/integrations/linear/connect",
                        follow_redirects=False,
                    )

                from urllib.parse import parse_qs, urlparse

                location = resp.headers["location"]
                parsed = urlparse(location)
                params = parse_qs(parsed.query)
                state = params.get("state", [""])[0]

                resp = tc.get(
                    f"/auth/integrations/linear/callback?code=test-code&state={state}",
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                # Should still succeed despite webhook failure
                assert "connected=linear" in resp.headers["location"]

        # Integration should still be stored
        mock_integration_store.upsert_integration.assert_awaited_once()
        # webhook_secret should NOT be in config since webhook failed
        call_kwargs = mock_integration_store.upsert_integration.call_args.kwargs
        assert "webhook_secret" not in call_kwargs["config"]
