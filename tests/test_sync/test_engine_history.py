"""Tests for sync history integration in forward_sync and reverse_sync."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from canon.parser.models import SectionStatus
from canon.parser.parse import parse_spec
from canon.sync.engine import forward_sync, reverse_sync
from canon.sync.models import (
    CreateTicketInput,
    CreateTicketResult,
    TicketStatusResult,
    UpdateTicketInput,
)


class MockAdapter:
    """Mock ticket adapter for sync engine tests."""

    def __init__(
        self,
        *,
        create_result: CreateTicketResult | None = None,
        status_result: TicketStatusResult | None = None,
        create_error: Exception | None = None,
        status_error: Exception | None = None,
    ) -> None:
        self.create_result = create_result
        self.status_result = status_result
        self.create_error = create_error
        self.status_error = status_error
        self.created: list[CreateTicketInput] = []
        self.updated: list[UpdateTicketInput] = []
        self.status_queries: list[str] = []

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        self.created.append(input)
        if self.create_error:
            raise self.create_error
        assert self.create_result is not None
        return self.create_result

    async def update_ticket(self, input: UpdateTicketInput) -> None:
        self.updated.append(input)

    async def get_ticket_status(self, ticket_id: str) -> TicketStatusResult:
        self.status_queries.append(ticket_id)
        if self.status_error:
            raise self.status_error
        assert self.status_result is not None
        return self.status_result

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


def _make_mock_store():
    store = AsyncMock()
    store.create_run = AsyncMock(return_value="test-run-id-123")
    store.complete_run = AsyncMock(return_value=True)
    store.add_events_batch = AsyncMock(return_value=0)
    return store


FORWARD_SPEC = """\
---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:todo -->

Content here.
"""

REVERSE_SPEC = """\
---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:todo -->
<!-- canon:ticket:jira:PAY-100 -->

Content here.
"""


class TestForwardSyncHistory:
    @pytest.mark.asyncio
    async def test_forward_sync_creates_run_when_store_provided(self):
        result = parse_spec(FORWARD_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-100",
                ticket_url="https://jira.example.com/browse/PAY-100",
            )
        )
        store = _make_mock_store()

        await forward_sync(
            result.document,
            adapter,
            "PAY",
            org="test-org",
            repo="test-repo",
            sync_store=store,
            sync_trigger="manual",
        )

        store.create_run.assert_called_once()
        call_kwargs = store.create_run.call_args[1]
        assert call_kwargs["org_login"] == "test-org"
        assert call_kwargs["repo"] == "test-repo"
        assert call_kwargs["system"] == "jira"
        assert call_kwargs["direction"] == "forward"
        assert call_kwargs["trigger"] == "manual"

    @pytest.mark.asyncio
    async def test_forward_sync_persists_created_events(self):
        result = parse_spec(FORWARD_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-100",
                ticket_url="https://jira.example.com/browse/PAY-100",
            )
        )
        store = _make_mock_store()

        await forward_sync(
            result.document,
            adapter,
            "PAY",
            sync_store=store,
        )

        store.add_events_batch.assert_called_once()
        _, events = store.add_events_batch.call_args[0]
        assert _ == "test-run-id-123"
        created_events = [e for e in events if e["event_type"] == "created"]
        assert len(created_events) >= 1
        assert created_events[0]["ticket_id"] == "PAY-100"

    @pytest.mark.asyncio
    async def test_forward_sync_completes_run_with_correct_counts(self):
        result = parse_spec(FORWARD_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-100",
                ticket_url="https://jira.example.com/browse/PAY-100",
            )
        )
        store = _make_mock_store()

        await forward_sync(
            result.document,
            adapter,
            "PAY",
            sync_store=store,
        )

        store.complete_run.assert_called_once()
        call_kwargs = store.complete_run.call_args[1]
        assert call_kwargs["status"] == "success"
        assert call_kwargs["created_count"] == 1

    @pytest.mark.asyncio
    async def test_forward_sync_records_errors(self):
        result = parse_spec(FORWARD_SPEC)
        adapter = MockAdapter(create_error=RuntimeError("API down"))
        store = _make_mock_store()

        await forward_sync(
            result.document,
            adapter,
            "PAY",
            sync_store=store,
        )

        store.add_events_batch.assert_called_once()
        _, events = store.add_events_batch.call_args[0]
        error_events = [e for e in events if e["event_type"] == "error"]
        assert len(error_events) >= 1
        assert "API down" in error_events[0]["detail"]["error"]

        call_kwargs = store.complete_run.call_args[1]
        assert call_kwargs["status"] in ("partial", "failed")

    @pytest.mark.asyncio
    async def test_forward_sync_no_persistence_without_store(self):
        result = parse_spec(FORWARD_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-100",
                ticket_url="https://jira.example.com/browse/PAY-100",
            )
        )

        _markdown, sync_result = await forward_sync(
            result.document,
            adapter,
            "PAY",
            sync_store=None,
        )

        # Engine should still work normally without a store
        assert len(sync_result.created) == 1

    @pytest.mark.asyncio
    async def test_forward_sync_skipped_spec_persists(self):
        raw = """\
---
title: Test
status: draft
owner: test
team: test
sync: "false"
---

## 1. Section One

<!-- canon:system:1 status:todo -->

Content here.
"""
        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-100",
                ticket_url="https://jira.example.com/browse/PAY-100",
            )
        )
        store = _make_mock_store()

        await forward_sync(
            result.document,
            adapter,
            "PAY",
            sync_store=store,
        )

        store.add_events_batch.assert_called_once()
        _, events = store.add_events_batch.call_args[0]
        skipped_events = [e for e in events if e["event_type"] == "skipped"]
        assert len(skipped_events) >= 1

        store.complete_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_forward_sync_custom_trigger(self):
        result = parse_spec(FORWARD_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-100",
                ticket_url="https://jira.example.com/browse/PAY-100",
            )
        )
        store = _make_mock_store()

        await forward_sync(
            result.document,
            adapter,
            "PAY",
            sync_store=store,
            sync_trigger="cron",
        )

        call_kwargs = store.create_run.call_args[1]
        assert call_kwargs["trigger"] == "cron"


class TestReverseSyncHistory:
    @pytest.mark.asyncio
    async def test_reverse_sync_creates_run_when_store_provided(self):
        result = parse_spec(REVERSE_SPEC)
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="PAY-100",
                status=SectionStatus(state="in_progress"),
                raw_status="In Progress",
            )
        )
        store = _make_mock_store()

        await reverse_sync(
            result.document,
            adapter,
            org="test-org",
            repo="test-repo",
            sync_store=store,
            sync_trigger="manual",
        )

        store.create_run.assert_called_once()
        call_kwargs = store.create_run.call_args[1]
        assert call_kwargs["direction"] == "reverse"
        assert call_kwargs["org_login"] == "test-org"
        assert call_kwargs["repo"] == "test-repo"
        assert call_kwargs["system"] == "jira"

    @pytest.mark.asyncio
    async def test_reverse_sync_persists_status_changes(self):
        result = parse_spec(REVERSE_SPEC)
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="PAY-100",
                status=SectionStatus(state="done"),
                raw_status="Done",
            )
        )
        store = _make_mock_store()

        await reverse_sync(
            result.document,
            adapter,
            sync_store=store,
        )

        store.add_events_batch.assert_called_once()
        _, events = store.add_events_batch.call_args[0]
        status_events = [e for e in events if e["event_type"] == "status_changed"]
        assert len(status_events) >= 1
        assert status_events[0]["ticket_id"] == "PAY-100"
        assert status_events[0]["detail"]["old_state"] == "todo"
        assert status_events[0]["detail"]["new_state"] == "done"

        store.complete_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_reverse_sync_no_persistence_without_store(self):
        result = parse_spec(REVERSE_SPEC)
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="PAY-100",
                status=SectionStatus(state="done"),
                raw_status="Done",
            )
        )

        _markdown, sync_result = await reverse_sync(
            result.document,
            adapter,
            sync_store=None,
        )

        # Engine should still work normally without a store
        assert len(sync_result.status_changed) == 1
