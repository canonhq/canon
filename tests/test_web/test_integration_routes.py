"""Tests for integration CRUD routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from canon.auth.models import CurrentUser
from canon.auth.permissions import Permission
from canon.main import app
from canon.settings import Settings
from canon.web.cache import TTLCache

ORG = "test-org"
VALID_UUID = "00000000-0000-4000-8000-000000000001"


def _make_user(
    org_login: str = ORG,
    permissions: frozenset[Permission] | None = None,
) -> CurrentUser:
    if permissions is None:
        permissions = frozenset(Permission)
    return CurrentUser(
        sub="user|123",
        email="user@example.com",
        name="Test User",
        org_login=org_login,
        permissions=permissions,
        auth_method="session",
    )


def _mock_connection_store() -> AsyncMock:
    store = AsyncMock()
    store.list_connections = AsyncMock(return_value=[])
    store.delete_connection = AsyncMock(return_value=True)
    return store


def _mock_user_store(*, has_user: bool = True) -> AsyncMock:
    store = AsyncMock()
    if has_user:
        store.get_user_by_sub = AsyncMock(return_value={"id": 42, "oidc_sub": "user|123"})
    else:
        store.get_user_by_sub = AsyncMock(return_value=None)
    return store


def _mock_integration_store() -> AsyncMock:
    store = AsyncMock()
    store.list_integrations = AsyncMock(return_value=[])
    store.get_integration = AsyncMock(return_value=None)
    store.get_integration_config = AsyncMock(return_value=None)
    store.delete_integration = AsyncMock(return_value=True)
    store.get_summary = AsyncMock(return_value={"total": 2, "connected": 1, "needs_attention": 1})
    store.update_status = AsyncMock()
    store.update_config = AsyncMock()
    return store


@pytest.fixture(autouse=True)
def _setup_app_state():
    """Set up minimal app state for integration route tests.

    Patches get_current_user at the module level so that require_permission's
    inner _check function (which calls get_current_user directly) returns a
    user whose org_login matches ORG, allowing _check_org_ownership to pass.
    """
    user = _make_user()

    async def _fake_user(request):
        return user

    app.state.settings = Settings(web_org=ORG)
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.db_pool = MagicMock()
    app.state.github_client = AsyncMock()
    app.state.registry = None
    app.state.connection_store = None
    app.state.integration_store = None
    app.state.user_store = None

    # Reset the in-memory rate limiter between tests
    from canon.web.integration_routes import _test_rate_limit

    _test_rate_limit.clear()

    with (
        patch("canon.auth.deps.get_current_user", _fake_user),
        patch("canon.web.routes._get_spa_html", return_value=None),
    ):
        yield user


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    )


# ─── User Connections ─────────────────────────────────────


class TestListConnections:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_store(self, client: AsyncClient):
        """When connection_store is None, returns empty list."""
        resp = await client.get(f"/app/{ORG}/api/settings/connections")
        assert resp.status_code == 200
        assert resp.json() == {"connections": []}

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_user_store(self, client: AsyncClient):
        """When user_store is None, returns empty list."""
        app.state.connection_store = _mock_connection_store()
        resp = await client.get(f"/app/{ORG}/api/settings/connections")
        assert resp.status_code == 200
        assert resp.json() == {"connections": []}

    @pytest.mark.asyncio
    async def test_returns_empty_when_user_not_found(self, client: AsyncClient):
        """When user doesn't exist in DB, returns empty list."""
        app.state.connection_store = _mock_connection_store()
        app.state.user_store = _mock_user_store(has_user=False)
        resp = await client.get(f"/app/{ORG}/api/settings/connections")
        assert resp.status_code == 200
        assert resp.json() == {"connections": []}

    @pytest.mark.asyncio
    async def test_returns_connections(self, client: AsyncClient):
        """Returns serialized connections with ISO datetimes and string UUIDs."""
        now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
        conn_id = UUID(VALID_UUID)
        conn_store = _mock_connection_store()
        conn_store.list_connections = AsyncMock(
            return_value=[
                {
                    "id": conn_id,
                    "provider": "github",
                    "connected_at": now,
                    "updated_at": now,
                    "token_expires_at": None,
                }
            ]
        )
        app.state.connection_store = conn_store
        app.state.user_store = _mock_user_store()

        resp = await client.get(f"/app/{ORG}/api/settings/connections")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["connections"]) == 1
        conn = data["connections"][0]
        assert conn["provider"] == "github"
        assert conn["connected_at"] == now.isoformat()
        assert conn["updated_at"] == now.isoformat()
        assert conn["token_expires_at"] is None
        assert conn["id"] == str(conn_id)

    @pytest.mark.asyncio
    async def test_cross_org_returns_403(self, client: AsyncClient):
        """Accessing connections for another org returns 403."""
        resp = await client.get("/app/other-org/api/settings/connections")
        assert resp.status_code == 403
        assert "another org" in resp.json()["detail"]


class TestDisconnectProvider:
    @pytest.mark.asyncio
    async def test_disconnect_succeeds(self, client: AsyncClient):
        """Successfully disconnects a provider."""
        app.state.connection_store = _mock_connection_store()
        app.state.user_store = _mock_user_store()

        resp = await client.delete(f"/app/{ORG}/api/settings/connections/github")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_disconnect_no_store_returns_500(self, client: AsyncClient):
        """Returns 500 when connection_store is None."""
        resp = await client.delete(f"/app/{ORG}/api/settings/connections/github")
        assert resp.status_code == 500
        assert "Database not configured" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_disconnect_no_user_store_returns_500(self, client: AsyncClient):
        """Returns 500 when user_store is None."""
        app.state.connection_store = _mock_connection_store()
        resp = await client.delete(f"/app/{ORG}/api/settings/connections/github")
        assert resp.status_code == 500
        assert "Database not configured" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_disconnect_user_not_found_returns_404(self, client: AsyncClient):
        """Returns 404 when user doesn't exist in DB."""
        app.state.connection_store = _mock_connection_store()
        app.state.user_store = _mock_user_store(has_user=False)
        resp = await client.delete(f"/app/{ORG}/api/settings/connections/github")
        assert resp.status_code == 404
        assert "User not found" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_disconnect_clears_github_session(self, client: AsyncClient):
        """Disconnecting github clears session data for backward compat."""
        conn_store = _mock_connection_store()
        app.state.connection_store = conn_store
        app.state.user_store = _mock_user_store()

        resp = await client.delete(f"/app/{ORG}/api/settings/connections/github")
        assert resp.status_code == 200
        conn_store.delete_connection.assert_awaited_once_with(42, "github")

    @pytest.mark.asyncio
    async def test_disconnect_cross_org_returns_403(self, client: AsyncClient):
        resp = await client.delete("/app/other-org/api/settings/connections/github")
        assert resp.status_code == 403


# ─── Org Integrations ─────────────────────────────────────


class TestListIntegrations:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_store(self, client: AsyncClient):
        resp = await client.get(f"/app/{ORG}/api/settings/integrations")
        assert resp.status_code == 200
        assert resp.json() == {"integrations": []}

    @pytest.mark.asyncio
    async def test_returns_integrations(self, client: AsyncClient):
        now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
        integ_id = UUID(VALID_UUID)
        store = _mock_integration_store()
        store.list_integrations = AsyncMock(
            return_value=[
                {
                    "id": integ_id,
                    "provider": "jira",
                    "status": "active",
                    "connected_at": now,
                    "updated_at": now,
                }
            ]
        )
        app.state.integration_store = store

        resp = await client.get(f"/app/{ORG}/api/settings/integrations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["integrations"]) == 1
        integ = data["integrations"][0]
        assert integ["provider"] == "jira"
        assert integ["connected_at"] == now.isoformat()
        assert integ["id"] == str(integ_id)
        store.list_integrations.assert_awaited_once_with(ORG)

    @pytest.mark.asyncio
    async def test_cross_org_returns_403(self, client: AsyncClient):
        resp = await client.get("/app/other-org/api/settings/integrations")
        assert resp.status_code == 403


class TestDisconnectIntegration:
    @pytest.mark.asyncio
    async def test_disconnect_no_store_returns_500(self, client: AsyncClient):
        resp = await client.delete(f"/app/{ORG}/api/settings/integrations/jira")
        assert resp.status_code == 500
        assert "Database not configured" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_disconnect_succeeds_no_webhook(self, client: AsyncClient):
        """Disconnect works when integration has no webhook_id."""
        store = _mock_integration_store()
        store.get_integration = AsyncMock(return_value={"provider_metadata": {}})
        app.state.integration_store = store

        resp = await client.delete(f"/app/{ORG}/api/settings/integrations/jira")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        store.delete_integration.assert_awaited_once_with(ORG, "jira")

    @pytest.mark.asyncio
    async def test_disconnect_deregisters_jira_webhook(self, client: AsyncClient):
        """Disconnect attempts to deregister a Jira webhook before deleting."""
        store = _mock_integration_store()
        store.get_integration = AsyncMock(
            return_value={"provider_metadata": {"webhook_id": "wh-123"}}
        )
        store.get_integration_config = AsyncMock(
            return_value={"access_token": "tok", "cloud_id": "cloud-1"}
        )
        app.state.integration_store = store

        with patch(
            "canon.web.integration_routes._deregister_webhook", new_callable=AsyncMock
        ) as mock_dereg:
            resp = await client.delete(f"/app/{ORG}/api/settings/integrations/jira")

        assert resp.status_code == 200
        mock_dereg.assert_awaited_once_with(
            "jira",
            {"access_token": "tok", "cloud_id": "cloud-1"},
            "wh-123",
        )

    @pytest.mark.asyncio
    async def test_disconnect_deregisters_linear_webhook(self, client: AsyncClient):
        """Disconnect attempts to deregister a Linear webhook before deleting."""
        store = _mock_integration_store()
        store.get_integration = AsyncMock(
            return_value={"provider_metadata": {"webhook_id": "wh-456"}}
        )
        store.get_integration_config = AsyncMock(return_value={"access_token": "lin-tok"})
        app.state.integration_store = store

        with patch(
            "canon.web.integration_routes._deregister_webhook", new_callable=AsyncMock
        ) as mock_dereg:
            resp = await client.delete(f"/app/{ORG}/api/settings/integrations/linear")

        assert resp.status_code == 200
        mock_dereg.assert_awaited_once_with(
            "linear",
            {"access_token": "lin-tok"},
            "wh-456",
        )

    @pytest.mark.asyncio
    async def test_disconnect_with_jsonb_string_metadata(self, client: AsyncClient):
        """Provider metadata stored as JSON string (JSONB) is parsed correctly."""
        import json

        store = _mock_integration_store()
        store.get_integration = AsyncMock(
            return_value={"provider_metadata": json.dumps({"webhook_id": "wh-json"})}
        )
        store.get_integration_config = AsyncMock(
            return_value={"access_token": "tok", "cloud_id": "c1"}
        )
        app.state.integration_store = store

        with patch(
            "canon.web.integration_routes._deregister_webhook", new_callable=AsyncMock
        ) as mock_dereg:
            resp = await client.delete(f"/app/{ORG}/api/settings/integrations/jira")

        assert resp.status_code == 200
        mock_dereg.assert_awaited_once_with(
            "jira", {"access_token": "tok", "cloud_id": "c1"}, "wh-json"
        )

    @pytest.mark.asyncio
    async def test_disconnect_no_integration_found(self, client: AsyncClient):
        """When no integration exists, delete still runs (returns store result)."""
        store = _mock_integration_store()
        store.get_integration = AsyncMock(return_value=None)
        store.delete_integration = AsyncMock(return_value=False)
        app.state.integration_store = store

        resp = await client.delete(f"/app/{ORG}/api/settings/integrations/jira")
        assert resp.status_code == 200
        assert resp.json() == {"ok": False}

    @pytest.mark.asyncio
    async def test_disconnect_cross_org_returns_403(self, client: AsyncClient):
        resp = await client.delete("/app/other-org/api/settings/integrations/jira")
        assert resp.status_code == 403


class TestIntegrationSummary:
    @pytest.mark.asyncio
    async def test_returns_zeros_when_no_store(self, client: AsyncClient):
        resp = await client.get(f"/app/{ORG}/api/settings/integrations/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"total": 0, "connected": 0, "needs_attention": 0}

    @pytest.mark.asyncio
    async def test_returns_summary(self, client: AsyncClient):
        store = _mock_integration_store()
        app.state.integration_store = store

        resp = await client.get(f"/app/{ORG}/api/settings/integrations/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["connected"] == 1
        assert data["needs_attention"] == 1
        store.get_summary.assert_awaited_once_with(ORG)

    @pytest.mark.asyncio
    async def test_cross_org_returns_403(self, client: AsyncClient):
        resp = await client.get("/app/other-org/api/settings/integrations/summary")
        assert resp.status_code == 403


# ─── Health Checks ─────────────────────────────────────────


class TestTestIntegration:
    @pytest.mark.asyncio
    async def test_no_store_returns_500(self, client: AsyncClient):
        resp = await client.post(f"/app/{ORG}/api/settings/integrations/jira/test")
        assert resp.status_code == 500
        assert resp.json()["message"] == "Database not configured"

    @pytest.mark.asyncio
    async def test_no_config_returns_404(self, client: AsyncClient):
        store = _mock_integration_store()
        store.get_integration_config = AsyncMock(return_value=None)
        app.state.integration_store = store

        resp = await client.post(f"/app/{ORG}/api/settings/integrations/jira/test")
        assert resp.status_code == 404
        assert "No jira integration configured" in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_rate_limit(self, client: AsyncClient):
        """Second test within 60s for same provider returns 429."""
        store = _mock_integration_store()
        store.get_integration_config = AsyncMock(
            return_value={"access_token": "tok", "cloud_id": "c1"}
        )
        store.get_integration = AsyncMock(return_value={"status": "active"})
        app.state.integration_store = store

        with patch(
            "canon.web.integration_routes._test_jira",
            new_callable=AsyncMock,
            return_value=(True, "Connected as Test User"),
        ):
            resp1 = await client.post(f"/app/{ORG}/api/settings/integrations/jira/test")
            assert resp1.status_code == 200

            resp2 = await client.post(f"/app/{ORG}/api/settings/integrations/jira/test")
            assert resp2.status_code == 429
            assert "Rate limited" in resp2.json()["message"]

    @pytest.mark.asyncio
    async def test_jira_success(self, client: AsyncClient):
        store = _mock_integration_store()
        store.get_integration_config = AsyncMock(
            return_value={"access_token": "tok", "cloud_id": "c1"}
        )
        store.get_integration = AsyncMock(return_value={"status": "active"})
        app.state.integration_store = store

        with patch(
            "canon.web.integration_routes._test_jira",
            new_callable=AsyncMock,
            return_value=(True, "Connected as Test User"),
        ):
            resp = await client.post(f"/app/{ORG}/api/settings/integrations/jira/test")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["message"] == "Connected as Test User"
        assert "latency_ms" in data

    @pytest.mark.asyncio
    async def test_linear_success(self, client: AsyncClient):
        store = _mock_integration_store()
        store.get_integration_config = AsyncMock(return_value={"access_token": "lin-tok"})
        store.get_integration = AsyncMock(return_value={"status": "active"})
        app.state.integration_store = store

        with patch(
            "canon.web.integration_routes._test_linear",
            new_callable=AsyncMock,
            return_value=(True, "Connected as Lin User"),
        ):
            resp = await client.post(f"/app/{ORG}/api/settings/integrations/linear/test")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["message"] == "Connected as Lin User"

    @pytest.mark.asyncio
    async def test_unsupported_provider(self, client: AsyncClient):
        store = _mock_integration_store()
        store.get_integration_config = AsyncMock(return_value={"access_token": "tok"})
        store.get_integration = AsyncMock(return_value={"status": "active"})
        app.state.integration_store = store

        resp = await client.post(f"/app/{ORG}/api/settings/integrations/slack/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "not implemented" in data["message"]

    @pytest.mark.asyncio
    async def test_failure_updates_status_to_error(self, client: AsyncClient):
        store = _mock_integration_store()
        store.get_integration_config = AsyncMock(
            return_value={"access_token": "tok", "cloud_id": "c1"}
        )
        app.state.integration_store = store

        with patch(
            "canon.web.integration_routes._test_jira",
            new_callable=AsyncMock,
            return_value=(False, "Authentication failed"),
        ):
            resp = await client.post(f"/app/{ORG}/api/settings/integrations/jira/test")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        store.update_status.assert_awaited_once_with(
            ORG, "jira", "error", error="Authentication failed"
        )

    @pytest.mark.asyncio
    async def test_success_activates_non_active_integration(self, client: AsyncClient):
        """When test succeeds and status is not 'active', updates to 'active'."""
        store = _mock_integration_store()
        store.get_integration_config = AsyncMock(
            return_value={"access_token": "tok", "cloud_id": "c1"}
        )
        store.get_integration = AsyncMock(return_value={"status": "error"})
        app.state.integration_store = store

        with patch(
            "canon.web.integration_routes._test_jira",
            new_callable=AsyncMock,
            return_value=(True, "Connected as User"),
        ):
            resp = await client.post(f"/app/{ORG}/api/settings/integrations/jira/test")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        store.update_status.assert_awaited_once_with(ORG, "jira", "active")

    @pytest.mark.asyncio
    async def test_exception_returns_failure(self, client: AsyncClient):
        """When the test function raises, the route catches it and returns ok=False."""
        store = _mock_integration_store()
        store.get_integration_config = AsyncMock(
            return_value={"access_token": "tok", "cloud_id": "c1"}
        )
        app.state.integration_store = store

        with patch(
            "canon.web.integration_routes._test_jira",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Connection refused"),
        ):
            resp = await client.post(f"/app/{ORG}/api/settings/integrations/jira/test")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "Connection refused" in data["message"]

    @pytest.mark.asyncio
    async def test_cross_org_returns_403(self, client: AsyncClient):
        resp = await client.post("/app/other-org/api/settings/integrations/jira/test")
        assert resp.status_code == 403


# ─── Permission checks ─────────────────────────────────────


class TestPermissionChecks:
    """Verify that disconnect/test routes require ORG_MANAGE permission."""

    @pytest.mark.asyncio
    async def test_disconnect_integration_requires_org_manage(self, client: AsyncClient):
        """Disconnect integration requires ORG_MANAGE, not just SPECS_READ."""
        read_only_user = _make_user(permissions=frozenset({Permission.SPECS_READ}))

        async def _fake_user(request):
            return read_only_user

        app.state.integration_store = _mock_integration_store()
        with patch("canon.auth.deps.get_current_user", _fake_user):
            resp = await client.delete(f"/app/{ORG}/api/settings/integrations/jira")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_test_integration_requires_org_manage(self, client: AsyncClient):
        """Test integration requires ORG_MANAGE permission."""
        read_only_user = _make_user(permissions=frozenset({Permission.SPECS_READ}))

        async def _fake_user(request):
            return read_only_user

        app.state.integration_store = _mock_integration_store()
        with patch("canon.auth.deps.get_current_user", _fake_user):
            resp = await client.post(f"/app/{ORG}/api/settings/integrations/jira/test")
        assert resp.status_code == 403


# ─── Unit tests for internal helpers ─────────────────────────


class TestParseMetadata:
    def test_dict_passthrough(self):
        from canon.web.integration_routes import _parse_metadata

        assert _parse_metadata({"key": "val"}) == {"key": "val"}

    def test_json_string(self):
        from canon.web.integration_routes import _parse_metadata

        assert _parse_metadata('{"key": "val"}') == {"key": "val"}

    def test_none_returns_empty_dict(self):
        from canon.web.integration_routes import _parse_metadata

        assert _parse_metadata(None) == {}

    def test_non_dict_non_string_returns_empty_dict(self):
        from canon.web.integration_routes import _parse_metadata

        assert _parse_metadata(42) == {}


class TestCheckOrgOwnership:
    def test_matching_org_passes(self):
        from canon.web.integration_routes import _check_org_ownership

        user = _make_user(org_login="my-org")
        # Should not raise
        _check_org_ownership(user, "my-org")

    def test_mismatched_org_raises_403(self):
        from canon.web.integration_routes import _check_org_ownership

        user = _make_user(org_login="my-org")
        with pytest.raises(Exception) as exc_info:
            _check_org_ownership(user, "other-org")
        assert exc_info.value.status_code == 403


# ─── _test_jira / _test_linear unit tests ─────────────────


class TestTestJiraUnit:
    @pytest.mark.asyncio
    async def test_missing_cloud_id(self):
        from canon.web.integration_routes import _test_jira

        ok, msg = await _test_jira({"access_token": "tok"})
        assert ok is False
        assert "Missing cloud_id" in msg

    @pytest.mark.asyncio
    async def test_missing_access_token(self):
        from canon.web.integration_routes import _test_jira

        ok, msg = await _test_jira({"cloud_id": "c1"})
        assert ok is False
        assert "Missing" in msg

    @pytest.mark.asyncio
    async def test_success(self):
        from canon.web.integration_routes import _test_jira

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"displayName": "Test User"}
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "canon.web.integration_routes._jira_myself",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            ok, msg = await _test_jira({"cloud_id": "c1", "access_token": "tok"})

        assert ok is True
        assert "Test User" in msg

    @pytest.mark.asyncio
    async def test_401_with_cron_refreshed_token(self):
        """When initial call returns 401, retry with cron-refreshed token."""
        from canon.web.integration_routes import _test_jira

        first_resp = MagicMock()
        first_resp.status_code = 401

        second_resp = MagicMock()
        second_resp.status_code = 200
        second_resp.json.return_value = {"displayName": "Refreshed User"}
        second_resp.raise_for_status = MagicMock()

        mock_store = AsyncMock()
        mock_store.get_integration_config = AsyncMock(
            return_value={"access_token": "new-tok", "cloud_id": "c1"}
        )

        with patch(
            "canon.web.integration_routes._jira_myself",
            new_callable=AsyncMock,
            side_effect=[first_resp, second_resp],
        ):
            ok, msg = await _test_jira(
                {"cloud_id": "c1", "access_token": "old-tok"},
                store=mock_store,
                org="test-org",
            )

        assert ok is True
        assert "Refreshed User" in msg

    @pytest.mark.asyncio
    async def test_401_no_refresh_token(self):
        """When 401 and no refresh token, returns failure."""
        from canon.web.integration_routes import _test_jira

        resp_401 = MagicMock()
        resp_401.status_code = 401

        mock_store = AsyncMock()
        mock_store.get_integration_config = AsyncMock(
            return_value={"access_token": "same-tok", "cloud_id": "c1"}
        )

        with (
            patch(
                "canon.web.integration_routes._jira_myself",
                new_callable=AsyncMock,
                return_value=resp_401,
            ),
            patch("canon.web.integration_routes.Settings") as mock_settings_cls,
        ):
            mock_settings_cls.return_value = MagicMock(
                jira_oauth_client_id="", jira_oauth_client_secret=""
            )
            ok, msg = await _test_jira(
                {"cloud_id": "c1", "access_token": "same-tok"},
                store=mock_store,
                org="test-org",
            )

        assert ok is False
        assert "expired" in msg.lower()


class TestTestLinearUnit:
    @pytest.mark.asyncio
    async def test_missing_access_token(self):
        from canon.web.integration_routes import _test_linear

        ok, msg = await _test_linear({})
        assert ok is False
        assert "Missing access_token" in msg

    @pytest.mark.asyncio
    async def test_success(self):
        from canon.web.integration_routes import _test_linear

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"viewer": {"id": "1", "name": "Lin User"}}}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            ok, msg = await _test_linear({"access_token": "lin-tok"})

        assert ok is True
        assert "Lin User" in msg

    @pytest.mark.asyncio
    async def test_401_returns_auth_failure(self):
        from canon.web.integration_routes import _test_linear

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            ok, msg = await _test_linear({"access_token": "bad-tok"})

        assert ok is False
        assert "Authentication failed" in msg


# ─── Webhook deregistration ─────────────────────────────────


class TestDeregisterWebhook:
    @pytest.mark.asyncio
    async def test_jira_deregister(self):
        from canon.web.integration_routes import _deregister_webhook

        with patch(
            "canon.sync.webhook_registration.deregister_jira_webhook",
            new_callable=AsyncMock,
        ) as mock_dereg:
            await _deregister_webhook("jira", {"cloud_id": "c1", "access_token": "tok"}, "wh-1")
        mock_dereg.assert_awaited_once_with(cloud_id="c1", access_token="tok", webhook_id="wh-1")

    @pytest.mark.asyncio
    async def test_linear_deregister(self):
        from canon.web.integration_routes import _deregister_webhook

        with patch(
            "canon.sync.webhook_registration.deregister_linear_webhook",
            new_callable=AsyncMock,
        ) as mock_dereg:
            await _deregister_webhook("linear", {"access_token": "tok"}, "wh-2")
        mock_dereg.assert_awaited_once_with(access_token="tok", webhook_id="wh-2")

    @pytest.mark.asyncio
    async def test_deregister_failure_is_nonfatal(self):
        """Webhook deregistration failures are logged but don't raise."""
        from canon.web.integration_routes import _deregister_webhook

        with patch(
            "canon.sync.webhook_registration.deregister_jira_webhook",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Network error"),
        ):
            # Should not raise
            await _deregister_webhook("jira", {"cloud_id": "c1", "access_token": "t"}, "wh-x")

    @pytest.mark.asyncio
    async def test_unknown_provider_is_noop(self):
        """Unknown providers do nothing (no exception)."""
        from canon.web.integration_routes import _deregister_webhook

        # Should not raise
        await _deregister_webhook("slack", {"access_token": "tok"}, "wh-3")
