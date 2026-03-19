"""Tests for require_review gating in forward_sync."""

from __future__ import annotations

import pytest

from canon.parser.parse import parse_spec
from canon.sync.engine import forward_sync
from canon.sync.models import CreateTicketInput, CreateTicketResult


class MockAdapter:
    """Mock ticket adapter for review gate tests."""

    def __init__(self) -> None:
        self.created: list[CreateTicketInput] = []

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        self.created.append(input)
        return CreateTicketResult(ticket_id="T-1", ticket_url="https://example.com/T-1")

    async def get_ticket_status(self, ticket_id: str):
        pass

    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None:
        pass

    async def search_tickets(self, project_key: str, title_pattern: str) -> list:
        return []

    @property
    def system_name(self) -> str:
        return "jira"

    @property
    def capabilities(self):
        from canon.sync.adapters.base import AdapterCapabilities

        return AdapterCapabilities()


def _make_spec(review_status: str | None = None) -> str:
    frontmatter_lines = [
        "---",
        "title: Test",
        "status: draft",
        "owner: test",
        "team: test",
    ]
    if review_status is not None:
        frontmatter_lines.append(f"review_status: {review_status}")
    frontmatter_lines.append("---")
    frontmatter_lines.extend(
        [
            "",
            "## 1. Section One",
            "",
            "<!-- specwright:system:1 status:todo -->",
            "",
            "Content.",
        ]
    )
    return "\n".join(frontmatter_lines)


class TestRequireReviewGate:
    @pytest.mark.asyncio
    async def test_blocks_when_review_status_none(self):
        raw = _make_spec(review_status=None)
        result = parse_spec(raw)
        adapter = MockAdapter()

        _markdown, sync_result = await forward_sync(
            result.document, adapter, "T", require_review=True
        )
        assert len(sync_result.errors) == 1
        assert "review approval" in sync_result.errors[0].error
        assert len(adapter.created) == 0

    @pytest.mark.asyncio
    async def test_blocks_when_review_status_draft(self):
        raw = _make_spec(review_status="draft")
        result = parse_spec(raw)
        adapter = MockAdapter()

        _markdown, sync_result = await forward_sync(
            result.document, adapter, "T", require_review=True
        )
        assert len(sync_result.errors) == 1
        assert "review approval" in sync_result.errors[0].error
        assert len(adapter.created) == 0

    @pytest.mark.asyncio
    async def test_blocks_when_review_status_in_review(self):
        raw = _make_spec(review_status="in_review")
        result = parse_spec(raw)
        adapter = MockAdapter()

        _markdown, sync_result = await forward_sync(
            result.document, adapter, "T", require_review=True
        )
        assert len(sync_result.errors) == 1
        assert len(adapter.created) == 0

    @pytest.mark.asyncio
    async def test_allows_when_review_status_approved(self):
        raw = _make_spec(review_status="approved")
        result = parse_spec(raw)
        adapter = MockAdapter()

        _markdown, sync_result = await forward_sync(
            result.document, adapter, "T", require_review=True
        )
        assert len(sync_result.errors) == 0
        assert len(sync_result.created) == 1
        assert len(adapter.created) == 1

    @pytest.mark.asyncio
    async def test_allows_when_require_review_false_any_status(self):
        """When require_review=False, any review_status is allowed."""
        for status in [None, "draft", "in_review", "approved"]:
            raw = _make_spec(review_status=status)
            result = parse_spec(raw)
            adapter = MockAdapter()

            _markdown, sync_result = await forward_sync(
                result.document, adapter, "T", require_review=False
            )
            assert len(sync_result.errors) == 0, f"Failed for status={status}"
            assert len(sync_result.created) == 1, f"Failed for status={status}"

    @pytest.mark.asyncio
    async def test_default_require_review_is_false(self):
        """Without require_review kwarg, sync proceeds normally."""
        raw = _make_spec(review_status=None)
        result = parse_spec(raw)
        adapter = MockAdapter()

        _markdown, sync_result = await forward_sync(result.document, adapter, "T")
        assert len(sync_result.errors) == 0
        assert len(sync_result.created) == 1
