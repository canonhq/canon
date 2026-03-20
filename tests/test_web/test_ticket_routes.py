"""Tests for ticket proxy routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.main import app
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


@pytest.fixture(autouse=True)
def _setup_app_state():
    from canon.settings import Settings

    app.state.settings = Settings(web_org=ORG)
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.github_client = _mock_client()
    app.state.registry = None
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
