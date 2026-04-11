"""Tests for ticket proxy routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.main import app
from canon.parser.models import SectionStatus
from canon.sync.models import CreateTicketResult, SearchResult, TicketStatusResult
from canon.web.cache import TTLCache

ORG = "test-org"


def _mock_client() -> AsyncMock:
    client = AsyncMock()
    client.list_installation_repos = AsyncMock(return_value=[])
    client.list_directory = AsyncMock(return_value=[])
    client.get_file_content = AsyncMock(side_effect=Exception("not found"))
    client._get = AsyncMock(side_effect=Exception("not found"))
    client.get_installation_token = AsyncMock(return_value="inst-token-abc")
    client.for_installation = lambda _: client
    client.installation_id = "12345"
    return client


def _mock_jira_adapter() -> AsyncMock:
    adapter = AsyncMock()
    adapter.create_ticket = AsyncMock(
        return_value=CreateTicketResult(
            ticket_id="CAN-1",
            ticket_url="https://jira.example.com/browse/CAN-1",
        )
    )
    adapter.get_ticket_status = AsyncMock(
        return_value=TicketStatusResult(
            ticket_id="CAN-1",
            status=SectionStatus(state="in_progress"),
            raw_status="In Progress",
        )
    )
    adapter.update_ticket = AsyncMock(return_value=None)
    adapter.link_pr = AsyncMock(return_value=None)
    adapter.search_tickets = AsyncMock(
        return_value=[
            SearchResult(
                ticket_id="CAN-10",
                title="Auth login flow",
                ticket_url="https://jira.example.com/browse/CAN-10",
                state="open",
            )
        ]
    )
    return adapter


def _mock_integration_store(*, has_jira: bool = True) -> AsyncMock:
    store = AsyncMock()
    if has_jira:
        store.get_integration_config = AsyncMock(
            return_value={
                "access_token": "jira-oauth-tok",
                "refresh_token": "jira-refresh",
                "cloud_id": "cloud-123",
            }
        )
    else:
        store.get_integration_config = AsyncMock(return_value=None)
    return store


@pytest.fixture(autouse=True)
def _setup_app_state():
    from canon.settings import Settings

    app.state.settings = Settings(web_org=ORG)
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.github_client = _mock_client()
    app.state.registry = None
    app.state.integration_store = None
    with patch("canon.web.routes._get_spa_html", return_value=None):
        yield


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


class TestCreateTicket:
    @pytest.mark.asyncio
    async def test_creates_ticket_via_adapter(self, client: AsyncClient, respx_mock):
        respx_mock.post(f"https://api.github.com/repos/{ORG}/widgets/issues").respond(
            json={"number": 42, "html_url": f"https://github.com/{ORG}/widgets/issues/42"}
        )

        resp = await client.post(
            f"/app/{ORG}/api/tickets/create",
            json={
                "owner": ORG,
                "repo": "widgets",
                "input": {
                    "project_key": "AW",
                    "summary": "Test ticket",
                    "description": "Body text",
                    "status": {"state": "todo"},
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticket_id"] == "42"
        assert "issues/42" in data["ticket_url"]

    @pytest.mark.asyncio
    async def test_rejects_owner_mismatch(self, client: AsyncClient):
        resp = await client.post(
            f"/app/{ORG}/api/tickets/create",
            json={
                "owner": "other-org",
                "repo": "widgets",
                "input": {
                    "project_key": "AW",
                    "summary": "Test",
                    "description": "",
                    "status": {"state": "todo"},
                },
            },
        )
        assert resp.status_code == 400
        assert "does not match" in resp.json()["detail"]


class TestGetTicketStatus:
    @pytest.mark.asyncio
    async def test_returns_status(self, client: AsyncClient, respx_mock):
        respx_mock.get(f"https://api.github.com/repos/{ORG}/widgets/issues/7").respond(
            json={
                "state": "open",
                "labels": [{"name": "specwright:in-progress"}],
            }
        )

        resp = await client.post(
            f"/app/{ORG}/api/tickets/status",
            json={"owner": ORG, "repo": "widgets", "ticket_id": "7"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticket_id"] == "7"
        assert data["status"]["state"] == "in_progress"


class TestBatchTicketStatus:
    @pytest.mark.asyncio
    async def test_returns_batch_results(self, client: AsyncClient, respx_mock):
        respx_mock.get(f"https://api.github.com/repos/{ORG}/widgets/issues/1").respond(
            json={"state": "open", "labels": [{"name": "specwright:todo"}]}
        )
        respx_mock.get(f"https://api.github.com/repos/{ORG}/widgets/issues/2").respond(
            json={"state": "closed", "labels": []}
        )

        resp = await client.post(
            f"/app/{ORG}/api/tickets/batch-status",
            json={"owner": ORG, "repo": "widgets", "ticket_ids": ["1", "2"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_collects_errors_without_leaking_details(self, client: AsyncClient, respx_mock):
        respx_mock.get(f"https://api.github.com/repos/{ORG}/widgets/issues/99").respond(
            status_code=404
        )

        resp = await client.post(
            f"/app/{ORG}/api/tickets/batch-status",
            json={"owner": ORG, "repo": "widgets", "ticket_ids": ["99"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["errors"]) == 1
        assert data["errors"][0]["ticket_id"] == "99"
        assert data["errors"][0]["error"] == "Failed to fetch ticket status"


class TestUpdateTicket:
    @pytest.mark.asyncio
    async def test_updates_ticket(self, client: AsyncClient, respx_mock):
        respx_mock.get(f"https://api.github.com/repos/{ORG}/widgets/issues/5").respond(
            json={"state": "open", "labels": [{"name": "specwright:todo"}]}
        )
        respx_mock.patch(f"https://api.github.com/repos/{ORG}/widgets/issues/5").respond(
            json={"number": 5}
        )

        resp = await client.post(
            f"/app/{ORG}/api/tickets/update",
            json={
                "owner": ORG,
                "repo": "widgets",
                "input": {
                    "ticket_id": "5",
                    "status": {"state": "in_progress"},
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestLinkPR:
    @pytest.mark.asyncio
    async def test_links_pr(self, client: AsyncClient, respx_mock):
        respx_mock.post(f"https://api.github.com/repos/{ORG}/widgets/issues/5/comments").respond(
            json={"id": 1}
        )

        resp = await client.post(
            f"/app/{ORG}/api/tickets/link-pr",
            json={
                "owner": ORG,
                "repo": "widgets",
                "ticket_id": "5",
                "pr_url": f"https://github.com/{ORG}/widgets/pull/10",
                "pr_title": "Fix thing",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


# ── Jira proxy tests ────────────────────────────────────────


class TestJiraCreateTicket:
    @pytest.mark.asyncio
    async def test_creates_jira_ticket_via_proxy(self, client: AsyncClient):
        mock_adapter = _mock_jira_adapter()
        app.state.integration_store = _mock_integration_store(has_jira=True)

        with patch("canon.web.ticket_routes.from_org", return_value=mock_adapter):
            resp = await client.post(
                f"/app/{ORG}/api/tickets/create",
                json={
                    "ticket_system": "jira",
                    "input": {
                        "project_key": "CAN",
                        "summary": "Test Jira ticket",
                        "description": "Created via proxy",
                        "status": {"state": "todo"},
                    },
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticket_id"] == "CAN-1"
        assert "jira.example.com" in data["ticket_url"]

    @pytest.mark.asyncio
    async def test_jira_not_connected_returns_404(self, client: AsyncClient):
        app.state.integration_store = _mock_integration_store(has_jira=False)

        with patch(
            "canon.web.ticket_routes.from_org",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(
                f"/app/{ORG}/api/tickets/create",
                json={
                    "ticket_system": "jira",
                    "input": {
                        "project_key": "CAN",
                        "summary": "Should fail",
                        "description": "",
                        "status": {"state": "todo"},
                    },
                },
            )
        assert resp.status_code == 422
        assert "not connected" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_no_integration_store_returns_503(self, client: AsyncClient):
        app.state.integration_store = None

        resp = await client.post(
            f"/app/{ORG}/api/tickets/create",
            json={
                "ticket_system": "jira",
                "input": {
                    "project_key": "CAN",
                    "summary": "Should fail",
                    "description": "",
                    "status": {"state": "todo"},
                },
            },
        )
        assert resp.status_code == 503


class TestJiraGetStatus:
    @pytest.mark.asyncio
    async def test_returns_jira_status(self, client: AsyncClient):
        mock_adapter = _mock_jira_adapter()
        app.state.integration_store = _mock_integration_store()

        with patch("canon.web.ticket_routes.from_org", return_value=mock_adapter):
            resp = await client.post(
                f"/app/{ORG}/api/tickets/status",
                json={"ticket_system": "jira", "ticket_id": "CAN-1"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticket_id"] == "CAN-1"
        assert data["status"]["state"] == "in_progress"


class TestJiraUpdate:
    @pytest.mark.asyncio
    async def test_updates_jira_ticket(self, client: AsyncClient):
        mock_adapter = _mock_jira_adapter()
        app.state.integration_store = _mock_integration_store()

        with patch("canon.web.ticket_routes.from_org", return_value=mock_adapter):
            resp = await client.post(
                f"/app/{ORG}/api/tickets/update",
                json={
                    "ticket_system": "jira",
                    "input": {"ticket_id": "CAN-1", "status": {"state": "done"}},
                },
            )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestSearchTickets:
    @pytest.mark.asyncio
    async def test_search_jira_tickets(self, client: AsyncClient):
        mock_adapter = _mock_jira_adapter()
        app.state.integration_store = _mock_integration_store()

        with patch("canon.web.ticket_routes.from_org", return_value=mock_adapter):
            resp = await client.post(
                f"/app/{ORG}/api/tickets/search",
                json={
                    "ticket_system": "jira",
                    "project_key": "CAN",
                    "title_pattern": "Auth",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["ticket_id"] == "CAN-10"

    @pytest.mark.asyncio
    async def test_search_github_tickets(self, client: AsyncClient, respx_mock):
        respx_mock.get("https://api.github.com/search/issues").respond(
            json={
                "items": [
                    {
                        "number": 5,
                        "title": "Auth bug",
                        "html_url": f"https://github.com/{ORG}/widgets/issues/5",
                        "state": "open",
                    }
                ]
            }
        )

        resp = await client.post(
            f"/app/{ORG}/api/tickets/search",
            json={
                "owner": ORG,
                "repo": "widgets",
                "project_key": f"{ORG}/widgets",
                "title_pattern": "Auth",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["ticket_id"] == "5"


class TestGitHubBackwardsCompat:
    @pytest.mark.asyncio
    async def test_no_ticket_system_defaults_to_github(self, client: AsyncClient, respx_mock):
        """Requests without ticket_system field use GitHub (backwards compat)."""
        respx_mock.post(f"https://api.github.com/repos/{ORG}/widgets/issues").respond(
            json={"number": 99, "html_url": f"https://github.com/{ORG}/widgets/issues/99"}
        )

        resp = await client.post(
            f"/app/{ORG}/api/tickets/create",
            json={
                "owner": ORG,
                "repo": "widgets",
                "input": {
                    "project_key": "AW",
                    "summary": "Compat test",
                    "description": "",
                    "status": {"state": "todo"},
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ticket_id"] == "99"

    @pytest.mark.asyncio
    async def test_github_without_owner_repo_returns_400(self, client: AsyncClient):
        resp = await client.post(
            f"/app/{ORG}/api/tickets/create",
            json={
                "ticket_system": "github",
                "input": {
                    "project_key": "AW",
                    "summary": "Missing owner",
                    "description": "",
                    "status": {"state": "todo"},
                },
            },
        )
        assert resp.status_code == 400
        assert "owner and repo are required" in resp.json()["detail"]
