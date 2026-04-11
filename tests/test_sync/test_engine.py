"""Port of sync-engine tests — forward and reverse sync."""

from __future__ import annotations

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


class TestForwardSync:
    @pytest.mark.asyncio
    async def test_creates_tickets_for_todo_sections(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- specwright:system:1 status:todo -->

Content.

## 2. Section Two

<!-- specwright:system:2 status:todo -->

More content."""

        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-100",
                ticket_url="https://jira.example.com/browse/PAY-100",
            )
        )

        markdown, sync_result = await forward_sync(result.document, adapter, "PAY")
        assert len(sync_result.created) == 2
        assert len(adapter.created) == 2
        assert "ticket:jira:PAY-100" in markdown
        # Verify spec title is included in the summary
        assert adapter.created[0].summary.startswith("[Test §")

    @pytest.mark.asyncio
    async def test_forward_sync_output_is_reparseable_with_correct_links(self):
        """Regression: forward_sync output must be re-parseable with each
        section linked to the correct ticket. This guards the full
        parse → write-back → re-parse cycle that was broken by the
        start_line off-by-one (fixed in PR #497)."""

        class _SequentialAdapter(MockAdapter):
            """Mock adapter that assigns a different ticket ID per create call."""

            def __init__(self, ids: list[str]) -> None:
                super().__init__()
                self._ids = list(ids)
                self._index = 0

            async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
                self.created.append(input)
                ticket_id = self._ids[self._index]
                self._index += 1
                return CreateTicketResult(
                    ticket_id=ticket_id,
                    ticket_url=f"https://jira.example.com/browse/{ticket_id}",
                )

        raw = """---
title: Roundtrip Test
status: draft
owner: test
team: test
---

# Roundtrip Test

Intro paragraph.

## 1. First section

<!-- canon:system:1 status:todo -->

First content.

## 2. Second section

<!-- canon:system:2 status:todo -->

Second content.
"""

        result = parse_spec(raw)
        adapter = _SequentialAdapter(["CAN-1", "CAN-2"])

        markdown, sync_result = await forward_sync(result.document, adapter, "CAN")
        assert len(sync_result.created) == 2

        # Re-parse the markdown returned by forward_sync and verify each
        # section is linked to the correct ticket. Before the PR #497 parser
        # fix, this failed: section 1 would link to CAN-2 (or None) and
        # section 2 would have no link at all, breaking idempotency.
        reparsed = parse_spec(markdown)
        assert reparsed.document.sections[0].ticket_link is not None, (
            "section 1 should have a ticket link after forward_sync"
        )
        assert reparsed.document.sections[0].ticket_link.ticket_id == "CAN-1"
        assert reparsed.document.sections[1].ticket_link is not None, (
            "section 2 should have a ticket link after forward_sync"
        )
        assert reparsed.document.sections[1].ticket_link.ticket_id == "CAN-2"

        # Idempotency: re-running forward_sync on the re-parsed doc should
        # link to existing tickets, not create new ones.
        dedup_adapter = _SequentialAdapter(["CAN-99", "CAN-100"])
        _, second_result = await forward_sync(reparsed.document, dedup_adapter, "CAN")
        assert len(second_result.created) == 0, (
            "re-running forward_sync should not create new tickets"
        )
        assert len(dedup_adapter.created) == 0

    @pytest.mark.asyncio
    async def test_skips_sections_with_existing_tickets(self, payments_spec: str):
        result = parse_spec(payments_spec)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-200", ticket_url="https://example.com/PAY-200"
            )
        )

        _markdown, sync_result = await forward_sync(result.document, adapter, "PAY")
        # Some sections already have tickets (PAY-142 etc)
        assert len(sync_result.updated) > 0

    @pytest.mark.asyncio
    async def test_skips_unnumbered_sections(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## Background

Just context.

## 1. Real Section

<!-- specwright:system:1 status:todo -->

Content."""

        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(ticket_id="T-1", ticket_url="https://example.com/T-1")
        )

        _markdown, sync_result = await forward_sync(result.document, adapter, "T")
        # Only "1. Real Section" should get a ticket, not "Background"
        assert len(sync_result.created) == 1

    @pytest.mark.asyncio
    async def test_skips_draft_sections(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Draft Section

<!-- specwright:system:1 status:draft -->

Not ready for work.

## 2. Todo Section

<!-- specwright:system:2 status:todo -->

Ready for work.

## 3. Done Section

<!-- specwright:system:3 status:done -->

Already done."""

        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(ticket_id="T-1", ticket_url="https://example.com/T-1")
        )

        _markdown, sync_result = await forward_sync(result.document, adapter, "T")
        # Only section 2 (todo) should get a ticket
        assert len(sync_result.created) == 1
        assert len(sync_result.skipped) == 2  # draft + done
        assert len(adapter.created) == 1

    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_adapter(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section

<!-- specwright:system:1 status:todo -->

Content."""

        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(ticket_id="T-1", ticket_url="https://example.com/T-1")
        )

        _markdown, sync_result = await forward_sync(result.document, adapter, "T", dry_run=True)
        assert len(sync_result.created) == 1
        assert sync_result.created[0].ticket_id == "(dry-run)"
        # Adapter should NOT have been called
        assert len(adapter.created) == 0

    @pytest.mark.asyncio
    async def test_collects_errors_on_failure(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section

<!-- specwright:system:1 status:todo -->

Content."""

        result = parse_spec(raw)
        adapter = MockAdapter(create_error=RuntimeError("API down"))

        _markdown, sync_result = await forward_sync(result.document, adapter, "T")
        assert len(sync_result.errors) == 1
        assert "API down" in sync_result.errors[0].error


class TestReverseSync:
    @pytest.mark.asyncio
    async def test_updates_status_when_ticket_differs(self, payments_spec: str):
        result = parse_spec(payments_spec)
        # Section 2 (Stripe Migration) is in_progress, mock ticket as done
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="PAY-142",
                status=SectionStatus(state="done"),
                raw_status="Done",
            )
        )

        _markdown, sync_result = await reverse_sync(result.document, adapter)
        assert len(sync_result.status_changed) > 0

    @pytest.mark.asyncio
    async def test_no_change_when_statuses_match(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section

<!-- specwright:system:1 status:in_progress -->
<!-- specwright:ticket:jira:T-1 -->

Content."""

        result = parse_spec(raw)
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="T-1",
                status=SectionStatus(state="in_progress"),
                raw_status="In Progress",
            )
        )

        _markdown, sync_result = await reverse_sync(result.document, adapter)
        assert len(sync_result.status_changed) == 0
        assert _markdown == result.document.raw

    @pytest.mark.asyncio
    async def test_collects_errors(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section

<!-- specwright:system:1 status:draft -->
<!-- specwright:ticket:jira:T-1 -->

Content."""

        result = parse_spec(raw)
        adapter = MockAdapter(status_error=RuntimeError("Network error"))

        _markdown, sync_result = await reverse_sync(result.document, adapter)
        assert len(sync_result.errors) == 1
        assert "Network error" in sync_result.errors[0].error
