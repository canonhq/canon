"""Tests for CanonApiAdapter — CLI-side proxy adapter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from canon.parser.models import SectionStatus
from canon.sync.adapters.api_proxy import CanonApiAdapter
from canon.sync.models import CreateTicketInput, UpdateTicketInput


def _mock_platform_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def adapter() -> CanonApiAdapter:
    client = _mock_platform_client()
    return CanonApiAdapter(client, org="acme", owner="acme", repo="widgets")


@pytest.fixture
def jira_adapter() -> CanonApiAdapter:
    client = _mock_platform_client()
    return CanonApiAdapter(
        client,
        org="acme",
        owner="",
        repo="",
        ticket_system="jira",
        project_key="CAN",
    )


# ── GitHub mode (backwards compat) ──────────────────────


class TestCreateTicket:
    @pytest.mark.asyncio
    async def test_posts_to_correct_endpoint(self, adapter: CanonApiAdapter):
        resp = MagicMock()
        resp.json.return_value = {
            "ticket_id": "42",
            "ticket_url": "https://github.com/acme/widgets/issues/42",
        }
        resp.raise_for_status = MagicMock()
        adapter._client.post.return_value = resp

        result = await adapter.create_ticket(
            CreateTicketInput(
                project_key="AW",
                summary="Test",
                description="Body",
                status=SectionStatus(state="todo"),
            )
        )
        assert result.ticket_id == "42"
        assert "issues/42" in result.ticket_url

        call_args = adapter._client.post.call_args
        assert call_args[0][0] == "/app/acme/api/tickets/create"
        body = call_args[1]["json"]
        assert body["owner"] == "acme"
        assert body["repo"] == "widgets"
        assert body["ticket_system"] == "github"
        assert body["input"]["summary"] == "Test"


class TestGetTicketStatus:
    @pytest.mark.asyncio
    async def test_posts_to_status_endpoint(self, adapter: CanonApiAdapter):
        resp = MagicMock()
        resp.json.return_value = {
            "ticket_id": "7",
            "status": {"state": "in_progress"},
            "raw_status": "open",
        }
        resp.raise_for_status = MagicMock()
        adapter._client.post.return_value = resp

        result = await adapter.get_ticket_status("7")
        assert result.ticket_id == "7"
        assert result.status.state == "in_progress"

        call_args = adapter._client.post.call_args
        assert call_args[0][0] == "/app/acme/api/tickets/status"


class TestUpdateTicket:
    @pytest.mark.asyncio
    async def test_posts_to_update_endpoint(self, adapter: CanonApiAdapter):
        resp = MagicMock()
        resp.json.return_value = {"ok": True}
        resp.raise_for_status = MagicMock()
        adapter._client.post.return_value = resp

        await adapter.update_ticket(
            UpdateTicketInput(
                ticket_id="5",
                status=SectionStatus(state="done"),
            )
        )

        call_args = adapter._client.post.call_args
        assert call_args[0][0] == "/app/acme/api/tickets/update"
        body = call_args[1]["json"]
        assert body["input"]["ticket_id"] == "5"


class TestLinkPR:
    @pytest.mark.asyncio
    async def test_posts_to_link_pr_endpoint(self, adapter: CanonApiAdapter):
        resp = MagicMock()
        resp.json.return_value = {"ok": True}
        resp.raise_for_status = MagicMock()
        adapter._client.post.return_value = resp

        await adapter.link_pr("5", "https://github.com/acme/widgets/pull/10", "Fix thing")

        call_args = adapter._client.post.call_args
        assert call_args[0][0] == "/app/acme/api/tickets/link-pr"
        body = call_args[1]["json"]
        assert body["ticket_id"] == "5"
        assert body["pr_url"] == "https://github.com/acme/widgets/pull/10"
        assert body["pr_title"] == "Fix thing"


class TestCapabilities:
    def test_github_supports_labels(self, adapter: CanonApiAdapter):
        caps = adapter.capabilities
        assert caps.supports_labels is True
        assert caps.supports_custom_fields is False

    def test_jira_capabilities(self, jira_adapter: CanonApiAdapter):
        caps = jira_adapter.capabilities
        assert caps.supports_custom_fields is True
        assert caps.supports_hierarchy is True
        assert caps.supports_subtasks is True
        assert caps.supports_labels is True
        assert caps.supports_issue_types is True

    def test_unknown_system_returns_defaults(self):
        client = _mock_platform_client()
        adapter = CanonApiAdapter(client, org="x", owner="", repo="", ticket_system="asana")
        caps = adapter.capabilities
        assert caps.supports_labels is False


class TestSystemName:
    def test_github_default(self, adapter: CanonApiAdapter):
        assert adapter.system_name == "github"

    def test_jira(self, jira_adapter: CanonApiAdapter):
        assert jira_adapter.system_name == "jira"


# ── Jira mode ────────────────────────────────────────────


class TestJiraMode:
    @pytest.mark.asyncio
    async def test_sends_ticket_system_in_body(self, jira_adapter: CanonApiAdapter):
        resp = MagicMock()
        resp.json.return_value = {
            "ticket_id": "CAN-1",
            "ticket_url": "https://jira.example.com/browse/CAN-1",
        }
        resp.raise_for_status = MagicMock()
        jira_adapter._client.post.return_value = resp

        await jira_adapter.create_ticket(
            CreateTicketInput(
                project_key="CAN",
                summary="Jira test",
                description="Body",
                status=SectionStatus(state="todo"),
            )
        )

        body = jira_adapter._client.post.call_args[1]["json"]
        assert body["ticket_system"] == "jira"
        assert body["project_key"] == "CAN"
        assert "owner" not in body  # Empty strings are not included

    @pytest.mark.asyncio
    async def test_search_tickets(self, jira_adapter: CanonApiAdapter):
        resp = MagicMock()
        resp.json.return_value = [
            {
                "ticket_id": "CAN-10",
                "title": "Auth flow",
                "ticket_url": "https://jira.example.com/browse/CAN-10",
                "state": "open",
            }
        ]
        resp.raise_for_status = MagicMock()
        jira_adapter._client.post.return_value = resp

        results = await jira_adapter.search_tickets("CAN", "Auth")
        assert len(results) == 1
        assert results[0].ticket_id == "CAN-10"

        call_args = jira_adapter._client.post.call_args
        assert call_args[0][0] == "/app/acme/api/tickets/search"
        body = call_args[1]["json"]
        assert body["project_key"] == "CAN"
        assert body["title_pattern"] == "Auth"

    @pytest.mark.asyncio
    async def test_get_status_includes_system(self, jira_adapter: CanonApiAdapter):
        resp = MagicMock()
        resp.json.return_value = {
            "ticket_id": "CAN-1",
            "status": {"state": "done"},
            "raw_status": "Done",
        }
        resp.raise_for_status = MagicMock()
        jira_adapter._client.post.return_value = resp

        await jira_adapter.get_ticket_status("CAN-1")

        body = jira_adapter._client.post.call_args[1]["json"]
        assert body["ticket_system"] == "jira"
        assert body["ticket_id"] == "CAN-1"
