"""Tests for sync management API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.main import app
from canon.web.cache import TTLCache

ORG = "test-org"
VALID_UUID = "00000000-0000-4000-8000-000000000001"
VALID_UUID_2 = "00000000-0000-4000-8000-000000000002"


@pytest.fixture(autouse=True)
def _setup_app_state():
    """Set up minimal app state for sync route tests.

    Auth is disabled by default (no OIDC/Auth0 config), so all requests
    get ANONYMOUS_USER with full permissions — no auth mocking needed.
    """
    from canon.settings import Settings

    mock_store = AsyncMock()
    app.state.settings = Settings(web_org=ORG)
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.db_pool = MagicMock()
    app.state.sync_history_store = mock_store
    app.state.github_client = AsyncMock()
    app.state.registry = None

    # Reset the in-memory rate limiter between tests
    from canon.web.sync_routes import _trigger_rate_limit

    _trigger_rate_limit.clear()

    with patch("canon.web.routes._get_spa_html", return_value=None):
        yield mock_store


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    )


class TestSyncStats:
    @pytest.mark.asyncio
    async def test_returns_stats(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        mock_store.get_stats = AsyncMock(
            return_value={
                "total_runs": 42,
                "success_runs": 38,
                "failed_runs": 4,
                "total_events": 120,
            }
        )

        resp = await client.get(f"/app/{ORG}/api/sync/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_runs"] == 42
        assert data["success_runs"] == 38
        assert data["failed_runs"] == 4
        mock_store.get_stats.assert_awaited_once_with(ORG)


class TestSyncRunsList:
    @pytest.mark.asyncio
    async def test_returns_paginated_runs(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        now = datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC)
        mock_store.list_runs = AsyncMock(
            return_value=[
                {
                    "run_id": "run-1",
                    "org_login": ORG,
                    "repo": "owner/repo",
                    "status": "success",
                    "started_at": now,
                    "finished_at": now,
                },
            ]
        )

        resp = await client.get(f"/app/{ORG}/api/sync/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert len(data["runs"]) == 1
        assert data["runs"][0]["run_id"] == "run-1"
        assert data["runs"][0]["status"] == "success"
        # started_at should be serialized as ISO string
        assert data["runs"][0]["started_at"] == now.isoformat()

    @pytest.mark.asyncio
    async def test_filters_passed_to_store(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        mock_store.list_runs = AsyncMock(return_value=[])

        resp = await client.get(
            f"/app/{ORG}/api/sync/runs",
            params={
                "repo": "owner/widgets",
                "system": "jira",
                "direction": "forward",
                "status": "failed",
                "limit": "10",
            },
        )
        assert resp.status_code == 200
        mock_store.list_runs.assert_awaited_once()
        call_kwargs = mock_store.list_runs.call_args
        # First positional arg is org
        assert call_kwargs[0][0] == ORG
        # Keyword filters
        assert call_kwargs[1]["repo"] == "owner/widgets"
        assert call_kwargs[1]["system"] == "jira"
        assert call_kwargs[1]["direction"] == "forward"
        assert call_kwargs[1]["status"] == "failed"
        assert call_kwargs[1]["limit"] == 10

    @pytest.mark.asyncio
    async def test_empty_runs(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        mock_store.list_runs = AsyncMock(return_value=[])

        resp = await client.get(f"/app/{ORG}/api/sync/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["runs"] == []
        assert data["next_cursor"] is None


class TestSyncRunDetail:
    @pytest.mark.asyncio
    async def test_returns_run_with_events(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        now = datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC)
        mock_store.get_run = AsyncMock(
            return_value={
                "run_id": VALID_UUID,
                "org_login": ORG,
                "repo": "owner/repo",
                "status": "success",
                "started_at": now,
            }
        )
        mock_store.get_run_events = AsyncMock(
            return_value=[
                {
                    "event_id": "evt-1",
                    "event_type": "create_ticket",
                    "status": "success",
                    "created_at": now,
                },
                {
                    "event_id": "evt-2",
                    "event_type": "create_ticket",
                    "status": "failed",
                    "created_at": now,
                },
                {
                    "event_id": "evt-3",
                    "event_type": "update_status",
                    "status": "success",
                    "created_at": now,
                },
            ]
        )

        resp = await client.get(f"/app/{ORG}/api/sync/runs/{VALID_UUID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run"]["run_id"] == VALID_UUID
        # Events grouped by type
        assert "create_ticket" in data["events"]
        assert len(data["events"]["create_ticket"]) == 2
        assert "update_status" in data["events"]
        assert len(data["events"]["update_status"]) == 1
        # Event counts
        assert data["event_counts"]["create_ticket"] == 2
        assert data["event_counts"]["update_status"] == 1

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        mock_store.get_run = AsyncMock(return_value=None)

        resp = await client.get(f"/app/{ORG}/api/sync/runs/{VALID_UUID_2}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_400(self, client: AsyncClient, _setup_app_state):
        resp = await client.get(f"/app/{ORG}/api/sync/runs/not-a-uuid")
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]


class TestSyncTrigger:
    @pytest.mark.asyncio
    async def test_trigger_returns_run_id(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        mock_store.create_run = AsyncMock(return_value="run-new-123")

        with patch("canon.web.sync_routes._execute_manual_sync", new_callable=AsyncMock):
            resp = await client.post(
                f"/app/{ORG}/api/sync/trigger",
                json={"repo": "owner/repo", "direction": "forward"},
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["run_id"] == "run-new-123"
        assert data["status"] == "started"
        mock_store.create_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limit(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        mock_store.create_run = AsyncMock(return_value="run-1")

        with patch("canon.web.sync_routes._execute_manual_sync", new_callable=AsyncMock):
            # First trigger succeeds
            resp1 = await client.post(
                f"/app/{ORG}/api/sync/trigger",
                json={"repo": "owner/repo", "direction": "forward"},
            )
            assert resp1.status_code == 202

            # Second trigger for same repo within cooldown returns 429
            resp2 = await client.post(
                f"/app/{ORG}/api/sync/trigger",
                json={"repo": "owner/repo", "direction": "forward"},
            )
            assert resp2.status_code == 429
            assert "triggered recently" in resp2.json()["detail"]


class TestSyncRunDetailAccess:
    @pytest.mark.asyncio
    async def test_cross_org_returns_403(self, client: AsyncClient, _setup_app_state):
        """Run belonging to a different org should return 403."""
        mock_store = _setup_app_state
        mock_store.get_run = AsyncMock(
            return_value={
                "run_id": VALID_UUID_2,
                "org_login": "other-org",
                "repo": "other-org/repo",
                "status": "success",
                "started_at": datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC),
            }
        )

        resp = await client.get(f"/app/{ORG}/api/sync/runs/{VALID_UUID_2}")
        assert resp.status_code == 403
        assert "Access denied" in resp.json()["detail"]


class TestSyncRetry:
    @pytest.mark.asyncio
    async def test_retry_not_found(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        mock_store.get_run = AsyncMock(return_value=None)

        resp = await client.post(
            f"/app/{ORG}/api/sync/retry",
            json={"run_id": VALID_UUID_2},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_invalid_uuid_returns_400(self, client: AsyncClient, _setup_app_state):
        resp = await client.post(
            f"/app/{ORG}/api/sync/retry",
            json={"run_id": "not-a-uuid"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_retry_cross_org_returns_403(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        mock_store.get_run = AsyncMock(
            return_value={
                "run_id": VALID_UUID_2,
                "org_login": "other-org",
            }
        )

        resp = await client.post(
            f"/app/{ORG}/api/sync/retry",
            json={"run_id": VALID_UUID_2},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_retry_returns_queued(self, client: AsyncClient, _setup_app_state):
        mock_store = _setup_app_state
        mock_store.get_run = AsyncMock(
            return_value={
                "run_id": VALID_UUID,
                "org_login": ORG,
            }
        )

        resp = await client.post(
            f"/app/{ORG}/api/sync/retry",
            json={"run_id": VALID_UUID},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "retry_queued"


class TestSyncConfigPresets:
    @pytest.mark.asyncio
    async def test_returns_presets(self, client: AsyncClient, _setup_app_state):
        resp = await client.get(f"/app/{ORG}/api/sync/config/owner/repo/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert "presets" in data
        presets = data["presets"]
        assert "standard_jira" in presets
        assert "standard_linear" in presets
        assert "standard_github" in presets
        assert len(presets) == 5

    @pytest.mark.asyncio
    async def test_filter_presets_by_system(self, client: AsyncClient, _setup_app_state):
        resp = await client.get(
            f"/app/{ORG}/api/sync/config/owner/repo/presets",
            params={"system": "jira"},
        )
        assert resp.status_code == 200
        data = resp.json()
        presets = data["presets"]
        assert len(presets) == 3
        assert all(v["system"] == "jira" for v in presets.values())
