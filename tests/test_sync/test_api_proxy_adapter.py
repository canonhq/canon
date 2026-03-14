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
    def test_supports_labels(self, adapter: CanonApiAdapter):
        caps = adapter.capabilities
        assert caps.supports_labels is True
        assert caps.supports_custom_fields is False
