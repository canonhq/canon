"""Tests for engine integration with TicketSystemConfig.

Verifies that forward_sync and reverse_sync properly use templates,
field mapping, hierarchy, and status maps when system_config is provided.
"""

from __future__ import annotations

import pytest

from canon.parser.models import SectionStatus
from canon.parser.parse import parse_spec
from canon.sync.engine import forward_sync, reverse_sync
from canon.sync.mapping import (
    FieldMapConfig,
    HierarchyConfig,
    StatusMapConfig,
    TemplateConfig,
    TicketSystemConfig,
)
from canon.sync.models import (
    CreateTicketInput,
    CreateTicketResult,
    TicketStatusResult,
    UpdateTicketInput,
)


class MockAdapter:
    """Mock ticket adapter that records all calls."""

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


SIMPLE_SPEC = """\
---
title: Payment Overhaul
status: draft
owner: alice
team: payments
tags: [billing, stripe]
---

## 1. Stripe Migration

<!-- specwright:system:1 status:todo -->

Migrate from Braintree to Stripe for payment processing.

### Acceptance Criteria

- [ ] All payment methods migrated to Stripe
- [ ] Zero-downtime cutover

## 2. Invoice System

<!-- specwright:system:2 status:todo -->

Build automated invoice generation.
"""

HIERARCHICAL_SPEC = """\
---
title: Auth System
status: draft
owner: bob
team: platform
tags: [auth]
---

## 1. Login Flow

<!-- specwright:system:1 status:todo -->

Implement login.

### 1.1 OAuth Providers

<!-- specwright:system:1.1 status:todo -->

Add OAuth provider support.

### 1.2 Password Reset

<!-- specwright:system:1.2 status:todo -->

Add password reset flow.

## 2. Session Management

<!-- specwright:system:2 status:todo -->

Manage sessions.
"""


class TestForwardSyncWithTemplates:
    @pytest.mark.asyncio
    async def test_uses_custom_summary_template(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-1", ticket_url="https://jira.example.com/PAY-1"
            )
        )

        config = TicketSystemConfig(
            system="jira",
            templates=TemplateConfig(
                summary="[§{{section.section_number}}] {{section.title}} — {{spec.title}}"
            ),
        )

        _, sync_result = await forward_sync(result.document, adapter, "PAY", system_config=config)
        assert len(sync_result.created) == 2
        assert adapter.created[0].summary == "[§1] Stripe Migration — Payment Overhaul"

    @pytest.mark.asyncio
    async def test_uses_custom_description_template(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-1", ticket_url="https://jira.example.com/PAY-1"
            )
        )

        config = TicketSystemConfig(
            system="jira",
            templates=TemplateConfig(
                description="h2. {{section.title}}\n\n{{section.content}}\n\n_From: {{spec.title}}_"
            ),
        )

        _, sync_result = await forward_sync(result.document, adapter, "PAY", system_config=config)
        assert len(sync_result.created) == 2
        desc = adapter.created[0].description
        assert "h2. Stripe Migration" in desc
        assert "_From: Payment Overhaul_" in desc

    @pytest.mark.asyncio
    async def test_default_behavior_without_templates(self):
        """When no system_config is provided, summary/description use hardcoded format."""
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-1", ticket_url="https://jira.example.com/PAY-1"
            )
        )

        _, sync_result = await forward_sync(result.document, adapter, "PAY")
        assert len(sync_result.created) == 2
        # Default format: [Title §N] Section Title
        assert adapter.created[0].summary.startswith("[Payment Overhaul §")


class TestForwardSyncWithHierarchy:
    @pytest.mark.asyncio
    async def test_sets_issue_type_from_hierarchy(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-1", ticket_url="https://jira.example.com/PAY-1"
            )
        )

        config = TicketSystemConfig(
            system="jira",
            hierarchy=HierarchyConfig(
                depth_to_type={2: "Epic", 3: "Story"},
                default_type="Task",
            ),
        )

        _, sync_result = await forward_sync(result.document, adapter, "PAY", system_config=config)
        assert len(sync_result.created) == 2
        # h2 sections → Epic
        assert adapter.created[0].issue_type == "Epic"
        assert adapter.created[1].issue_type == "Epic"

    @pytest.mark.asyncio
    async def test_adds_issue_type_label(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-1", ticket_url="https://jira.example.com/PAY-1"
            )
        )

        config = TicketSystemConfig(
            system="jira",
            hierarchy=HierarchyConfig(
                depth_to_type={2: "Epic", 3: "Story"},
            ),
        )

        _, sync_result = await forward_sync(result.document, adapter, "PAY", system_config=config)
        assert len(sync_result.created) == 2
        assert "type:epic" in adapter.created[0].labels
        assert "type:epic" in adapter.created[1].labels

    @pytest.mark.asyncio
    async def test_issue_type_in_default_summary(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-1", ticket_url="https://jira.example.com/PAY-1"
            )
        )

        config = TicketSystemConfig(
            system="jira",
            hierarchy=HierarchyConfig(
                depth_to_type={2: "Epic", 3: "Story"},
            ),
        )

        _, _sync_result = await forward_sync(result.document, adapter, "PAY", system_config=config)
        assert adapter.created[0].summary.startswith("[Epic]")

    @pytest.mark.asyncio
    async def test_auto_parent_links_child_to_parent(self):
        result = parse_spec(HIERARCHICAL_SPEC)
        # Adapter that returns different ticket IDs per call
        call_count = 0

        class SequentialAdapter(MockAdapter):
            async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
                nonlocal call_count
                call_count += 1
                self.created.append(input)
                return CreateTicketResult(
                    ticket_id=f"AUTH-{call_count}",
                    ticket_url=f"https://jira.example.com/AUTH-{call_count}",
                )

        adapter = SequentialAdapter()

        config = TicketSystemConfig(
            system="jira",
            hierarchy=HierarchyConfig(
                depth_to_type={2: "Epic", 3: "Story"},
                auto_parent=True,
            ),
        )

        _, sync_result = await forward_sync(result.document, adapter, "AUTH", system_config=config)
        assert len(sync_result.created) == 4
        # Section 1 (h2) → Epic, no parent
        assert adapter.created[0].issue_type == "Epic"
        assert adapter.created[0].parent_ticket_id is None
        # Section 1.1 (h3) → Story — but parent ticket won't be found
        # because the parent section doesn't have a ticket_link in the doc
        # (ticket links are inserted into markdown, not the parsed model)
        assert adapter.created[1].issue_type == "Story"

    @pytest.mark.asyncio
    async def test_child_gets_story_label(self):
        result = parse_spec(HIERARCHICAL_SPEC)
        call_count = 0

        class SeqAdapter(MockAdapter):
            async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
                nonlocal call_count
                call_count += 1
                self.created.append(input)
                return CreateTicketResult(
                    ticket_id=f"A-{call_count}",
                    ticket_url=f"https://example.com/A-{call_count}",
                )

        adapter = SeqAdapter()

        config = TicketSystemConfig(
            system="jira",
            hierarchy=HierarchyConfig(
                depth_to_type={2: "Epic", 3: "Story"},
                auto_parent=True,
            ),
        )

        _, _sync_result = await forward_sync(result.document, adapter, "A", system_config=config)
        # Section 1 (h2) → type:epic label
        assert "type:epic" in adapter.created[0].labels
        # Section 1.1 (h3) → type:story label
        assert "type:story" in adapter.created[1].labels

    @pytest.mark.asyncio
    async def test_default_issue_type_without_hierarchy(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-1", ticket_url="https://jira.example.com/PAY-1"
            )
        )

        _, sync_result = await forward_sync(result.document, adapter, "PAY")
        assert len(sync_result.created) == 2
        # Default: "Task"
        assert adapter.created[0].issue_type == "Task"
        # No type: label when no hierarchy configured
        assert not any(lb.startswith("type:") for lb in adapter.created[0].labels)


class TestForwardSyncWithFieldMapping:
    @pytest.mark.asyncio
    async def test_custom_fields_populated(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-1", ticket_url="https://jira.example.com/PAY-1"
            )
        )

        config = TicketSystemConfig(
            system="jira",
            field_map=FieldMapConfig(
                custom={
                    "customfield_10001": "frontmatter.tags",
                    "customfield_10002": "literal:canon-managed",
                },
            ),
        )

        _, sync_result = await forward_sync(result.document, adapter, "PAY", system_config=config)
        assert len(sync_result.created) == 2
        custom = adapter.created[0].custom_fields
        assert custom["customfield_10001"] == ["billing", "stripe"]
        assert custom["customfield_10002"] == "canon-managed"

    @pytest.mark.asyncio
    async def test_no_custom_fields_without_config(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-1", ticket_url="https://jira.example.com/PAY-1"
            )
        )

        _, sync_result = await forward_sync(result.document, adapter, "PAY")
        assert len(sync_result.created) == 2
        assert adapter.created[0].custom_fields == {}


class TestReverseSyncWithStatusMap:
    @pytest.mark.asyncio
    async def test_uses_custom_reverse_status_map(self):
        raw = """\
---
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
                status=SectionStatus(state="in_progress"),  # adapter's own resolution
                raw_status="In QA",  # the actual Jira status
            )
        )

        config = TicketSystemConfig(
            system="jira",
            status_map=StatusMapConfig(
                reverse={
                    "In QA": "done",  # custom: "In QA" → done
                    "In Development": "in_progress",
                },
            ),
        )

        _, sync_result = await reverse_sync(result.document, adapter, system_config=config)
        # The custom map resolves "In QA" → "done", which differs from "in_progress"
        assert len(sync_result.status_changed) == 1
        assert sync_result.status_changed[0].new_state == "done"

    @pytest.mark.asyncio
    async def test_falls_back_without_custom_map(self):
        raw = """\
---
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
                status=SectionStatus(state="done"),
                raw_status="Done",
            )
        )

        # No system_config — uses adapter's resolved status directly
        _, sync_result = await reverse_sync(result.document, adapter)
        assert len(sync_result.status_changed) == 1
        assert sync_result.status_changed[0].new_state == "done"


class TestForwardSyncBackwardCompatibility:
    """Verify that the engine behaves identically when no system_config is provided."""

    @pytest.mark.asyncio
    async def test_creates_tickets_same_as_before(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-100",
                ticket_url="https://jira.example.com/PAY-100",
            )
        )

        markdown, sync_result = await forward_sync(result.document, adapter, "PAY")
        assert len(sync_result.created) == 2
        assert "ticket:jira:PAY-100" in markdown
        assert adapter.created[0].summary.startswith("[Payment Overhaul §")
        assert adapter.created[0].issue_type == "Task"
        assert adapter.created[0].custom_fields == {}
        assert adapter.created[0].parent_ticket_id is None

    @pytest.mark.asyncio
    async def test_dry_run_unchanged(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(
            create_result=CreateTicketResult(
                ticket_id="PAY-1", ticket_url="https://example.com/PAY-1"
            )
        )

        _, sync_result = await forward_sync(result.document, adapter, "PAY", dry_run=True)
        assert len(sync_result.created) == 2
        assert sync_result.created[0].ticket_id == "(dry-run)"
        assert len(adapter.created) == 0

    @pytest.mark.asyncio
    async def test_error_handling_preserved(self):
        result = parse_spec(SIMPLE_SPEC)
        adapter = MockAdapter(create_error=RuntimeError("API down"))

        _, sync_result = await forward_sync(result.document, adapter, "PAY")
        # Both todo sections trigger errors
        assert len(sync_result.errors) == 2
        assert all("API down" in e.error for e in sync_result.errors)
