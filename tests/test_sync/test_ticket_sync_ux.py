"""Tests for ticket sync UX improvements.

Covers: system_name adapter property, clean_content, structured templates,
dedup search, dedup module, assignees/milestone, parent-child task lists.
"""

from __future__ import annotations

import pytest

from canon.parser.models import (
    AcceptanceCriterion,
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
)
from canon.parser.parse import parse_spec, parse_ticket_comment
from canon.sync.adapters.github_issues import GitHubAdapter
from canon.sync.dedup import rewrite_unknown_systems
from canon.sync.engine import _detect_system, forward_sync
from canon.sync.mapping import FieldMapConfig, HierarchyConfig, TicketSystemConfig
from canon.sync.models import (
    CreateTicketInput,
    CreateTicketResult,
    GitHubConfig,
    SearchResult,
    TicketStatusResult,
    UpdateTicketInput,
)
from canon.sync.templates import _clean_content, render_description, render_summary

# ─── Mock Adapter ────────────────────────────────────────


class MockAdapter:
    def __init__(
        self,
        *,
        create_result: CreateTicketResult | None = None,
        search_results: list[SearchResult] | None = None,
    ) -> None:
        self.create_result = create_result
        self.search_results = search_results or []
        self.created: list[CreateTicketInput] = []
        self.search_queries: list[tuple[str, str]] = []
        self.task_list_updates: list[tuple[str, list]] = []

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        self.created.append(input)
        assert self.create_result is not None
        return self.create_result

    async def update_ticket(self, input: UpdateTicketInput) -> None:
        pass

    async def get_ticket_status(self, ticket_id: str) -> TicketStatusResult:
        return TicketStatusResult(
            ticket_id=ticket_id,
            status=SectionStatus(state="todo"),
            raw_status="open",
        )

    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None:
        pass

    async def search_tickets(self, project_key: str, title_pattern: str) -> list[SearchResult]:
        self.search_queries.append((project_key, title_pattern))
        return self.search_results

    async def update_task_list(self, parent_ticket_id: str, children: list) -> None:
        self.task_list_updates.append((parent_ticket_id, children))

    @property
    def system_name(self) -> str:
        return "github"

    @property
    def capabilities(self):
        from canon.sync.adapters.base import AdapterCapabilities

        return AdapterCapabilities(supports_labels=True)


# ─── Helpers ─────────────────────────────────────────────


def _make_doc(file_path: str = "docs/specs/test.md") -> SpecDocument:
    return SpecDocument(
        file_path=file_path,
        frontmatter=SpecFrontmatter(
            title="Test Spec",
            status="draft",
            owner="nick",
            team="platform",
            tags=["backend"],
        ),
        sections=[],
        raw="",
    )


def _make_section(
    content: str = "Section content.",
    acs: list[str] | None = None,
) -> SpecSection:
    criteria = [AcceptanceCriterion(text=t, checked=False, line=i) for i, t in enumerate(acs or [])]
    return SpecSection(
        id="1-test-section",
        section_number="1",
        title="Test Section",
        depth=2,
        content=content,
        status=SectionStatus(state="todo"),
        acceptance_criteria=criteria,
        start_line=10,
        end_line=20,
    )


# ─── P0: system_name and _detect_system ─────────────────


class TestSystemName:
    def test_github_adapter_system_name(self):
        config = GitHubConfig(token="t", default_owner="o", default_repo="r")
        adapter = GitHubAdapter(config)
        assert adapter.system_name == "github"

    def test_detect_system_uses_adapter_system_name(self):
        adapter = MockAdapter()
        result = _detect_system(adapter, None)
        assert result == "github"

    def test_detect_system_prefers_config(self):
        adapter = MockAdapter()
        config = TicketSystemConfig(system="jira")
        result = _detect_system(adapter, config)
        assert result == "jira"

    def test_detect_system_never_returns_unknown(self):
        adapter = MockAdapter()
        result = _detect_system(adapter, None)
        assert result != "unknown"


# ─── P0: Parser warning for unrecognized ticket systems ──


class TestParserTicketWarning:
    def test_recognized_system_returns_link(self):
        result = parse_ticket_comment("<!-- specwright:ticket:github:123 -->")
        assert result is not None
        assert result.system == "github"

    def test_unknown_system_returns_none(self):
        result = parse_ticket_comment("<!-- specwright:ticket:unknown:123 -->")
        assert result is None

    def test_unknown_system_logs_warning(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            parse_ticket_comment("<!-- specwright:ticket:unknown:123 -->")
        assert "Unrecognized ticket system" in caplog.text


# ─── P1: clean_content ──────────────────────────────────


class TestCleanContent:
    def test_strips_ticket_comments(self):
        content = "Real content.\n<!-- specwright:ticket:github:123 -->\nMore."
        assert "specwright:ticket" not in _clean_content(content)
        assert "Real content." in _clean_content(content)

    def test_strips_status_comments(self):
        content = "Content.\n<!-- specwright:system:1 status:todo -->\nAfter."
        assert "specwright:system" not in _clean_content(content)

    def test_strips_delta_comments(self):
        content = "Content.\n<!-- specwright:delta:added -->\nMore."
        assert "specwright:delta" not in _clean_content(content)

    def test_strips_realization_comments(self):
        content = "Content.\n<!-- specwright:realized-in:PR#42 file:src/main.py -->\nMore."
        assert "specwright:realized-in" not in _clean_content(content)

    def test_preserves_regular_content(self):
        content = "Regular content with no comments."
        assert _clean_content(content) == content


# ─── P1: Structured default templates ───────────────────


class TestStructuredTemplates:
    def test_default_summary_includes_spec_title(self):
        result = render_summary(_make_section(), _make_doc())
        assert "Test Spec" in result
        assert "§1" in result
        assert "Test Section" in result

    def test_default_description_includes_spec_link(self):
        result = render_description(
            _make_section(),
            _make_doc(),
            spec_url="https://github.com/org/repo/blob/main/docs/specs/test.md",
        )
        assert "**Spec:**" in result
        assert "https://github.com/org/repo/blob/main/docs/specs/test.md" in result

    def test_default_description_includes_clean_content(self):
        content = "Real content.\n<!-- specwright:system:1 status:todo -->"
        result = render_description(_make_section(content=content), _make_doc())
        assert "Real content." in result
        assert "specwright:system" not in result

    def test_default_description_includes_acceptance_criteria(self):
        result = render_description(_make_section(acs=["AC one", "AC two"]), _make_doc())
        assert "- [ ] AC one" in result
        assert "- [ ] AC two" in result

    def test_default_description_includes_footer(self):
        result = render_description(_make_section(), _make_doc())
        assert "Canon" in result
        assert "platform" in result
        assert "nick" in result

    def test_clean_content_in_context(self):
        from canon.sync.templates import _build_context

        section = _make_section(content="Text\n<!-- specwright:ticket:github:1 -->\nMore")
        ctx = _build_context(section, _make_doc())
        assert "specwright:ticket" not in ctx["section.clean_content"]
        assert "Text" in ctx["section.clean_content"]

    def test_ac_count_in_context(self):
        from canon.sync.templates import _build_context

        section = _make_section(acs=["one", "two", "three"])
        ctx = _build_context(section, _make_doc())
        assert ctx["section.ac_count"] == "3"

    def test_spec_file_path_in_context(self):
        from canon.sync.templates import _build_context

        ctx = _build_context(_make_section(), _make_doc("docs/specs/auth.md"))
        assert ctx["spec.file_path"] == "docs/specs/auth.md"


# ─── P2: Dedup search before creation ───────────────────


class TestDedupSearch:
    @pytest.mark.asyncio
    async def test_links_existing_ticket_instead_of_creating(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Existing Feature

<!-- specwright:system:1 status:todo -->

Content."""
        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(ticket_id="99", ticket_url="https://example.com/99"),
            search_results=[
                SearchResult(
                    ticket_id="42",
                    title="Existing Feature",
                    ticket_url="https://example.com/42",
                    state="open",
                )
            ],
        )

        markdown, sync_result = await forward_sync(result.document, adapter, "TEST")
        # Should link to existing #42, not create a new one
        assert len(sync_result.updated) == 1
        assert sync_result.updated[0].ticket_id == "42"
        assert len(sync_result.created) == 0
        assert len(adapter.created) == 0
        assert "ticket:github:42" in markdown

    @pytest.mark.asyncio
    async def test_creates_when_no_search_results(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. New Feature

<!-- specwright:system:1 status:todo -->

Content."""
        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(ticket_id="99", ticket_url="https://example.com/99"),
            search_results=[],
        )

        _, sync_result = await forward_sync(result.document, adapter, "TEST")
        assert len(sync_result.created) == 1
        assert len(adapter.created) == 1

    @pytest.mark.asyncio
    async def test_dedup_disabled_skips_search(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Feature

<!-- specwright:system:1 status:todo -->

Content."""
        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(ticket_id="99", ticket_url="https://example.com/99"),
            search_results=[
                SearchResult(
                    ticket_id="42",
                    title="Feature",
                    ticket_url="https://example.com/42",
                    state="open",
                )
            ],
        )

        config = TicketSystemConfig(system="github", dedup_enabled=False)
        _, sync_result = await forward_sync(result.document, adapter, "TEST", system_config=config)
        # Should NOT search — creates directly
        assert len(sync_result.created) == 1
        assert len(adapter.search_queries) == 0


# ─── P3: Dedup module — rewrite_unknown_systems ─────────


class TestRewriteUnknownSystems:
    def test_rewrites_unknown_to_github(self):
        md = "<!-- specwright:ticket:unknown:283 -->\n<!-- specwright:ticket:unknown:284 -->"
        result, count = rewrite_unknown_systems(md)
        assert count == 2
        assert "ticket:github:283" in result
        assert "ticket:github:284" in result
        assert "ticket:unknown" not in result

    def test_preserves_known_systems(self):
        md = "<!-- specwright:ticket:github:1 -->\n<!-- specwright:ticket:jira:PAY-100 -->"
        result, count = rewrite_unknown_systems(md)
        assert count == 0
        assert result == md

    def test_mixed_content(self):
        md = "line 1\n<!-- specwright:ticket:unknown:42 -->\n<!-- specwright:ticket:github:7 -->\nline 4"
        result, count = rewrite_unknown_systems(md)
        assert count == 1
        assert "ticket:github:42" in result
        assert "ticket:github:7" in result


# ─── P4: Assignees and milestones ────────────────────────


class TestAssigneesAndMilestones:
    @pytest.mark.asyncio
    async def test_assignee_from_field_mapping(self):
        raw = """---
title: Test
status: draft
owner: alice
team: test
---

## 1. Feature

<!-- specwright:system:1 status:todo -->

Content."""
        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(ticket_id="1", ticket_url="https://example.com/1"),
        )

        config = TicketSystemConfig(
            system="github",
            field_map=FieldMapConfig(
                standard={"frontmatter.owner": "assignee"},
            ),
        )

        _, _sync_result = await forward_sync(result.document, adapter, "TEST", system_config=config)
        assert len(adapter.created) == 1
        assert adapter.created[0].assignees == ["alice"]

    @pytest.mark.asyncio
    async def test_no_assignees_without_field_map(self):
        raw = """---
title: Test
status: draft
owner: alice
team: test
---

## 1. Feature

<!-- specwright:system:1 status:todo -->

Content."""
        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(ticket_id="1", ticket_url="https://example.com/1"),
        )

        _, _sync_result = await forward_sync(result.document, adapter, "TEST")
        assert adapter.created[0].assignees == []
        assert adapter.created[0].milestone is None


# ─── P4: spec_url passthrough ────────────────────────────


class TestSpecUrlPassthrough:
    @pytest.mark.asyncio
    async def test_spec_url_appears_in_description(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Feature

<!-- specwright:system:1 status:todo -->

Content."""
        result = parse_spec(raw)
        adapter = MockAdapter(
            create_result=CreateTicketResult(ticket_id="1", ticket_url="https://example.com/1"),
        )

        _, _sync_result = await forward_sync(
            result.document,
            adapter,
            "TEST",
            spec_url="https://github.com/org/repo/blob/main/docs/specs/test.md",
        )
        assert len(adapter.created) == 1
        assert (
            "https://github.com/org/repo/blob/main/docs/specs/test.md"
            in adapter.created[0].description
        )


# ─── P5: Parent-child task lists ─────────────────────────


class TestParentChildTaskLists:
    @pytest.mark.asyncio
    async def test_parent_issue_gets_task_list(self):
        raw = """---
title: Auth
status: draft
owner: bob
team: platform
---

## 1. Login Flow

<!-- specwright:system:1 status:todo -->

Implement login.

### 1.1 OAuth Providers

<!-- specwright:system:1.1 status:todo -->

Add OAuth.

### 1.2 Password Reset

<!-- specwright:system:1.2 status:todo -->

Add reset."""
        result = parse_spec(raw)
        call_count = 0

        class SequentialAdapter(MockAdapter):
            async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
                nonlocal call_count
                call_count += 1
                self.created.append(input)
                return CreateTicketResult(
                    ticket_id=str(call_count),
                    ticket_url=f"https://example.com/{call_count}",
                )

        adapter = SequentialAdapter()

        config = TicketSystemConfig(
            system="github",
            hierarchy=HierarchyConfig(
                depth_to_type={2: "Epic", 3: "Story"},
                auto_parent=True,
            ),
        )

        _, sync_result = await forward_sync(result.document, adapter, "AUTH", system_config=config)
        assert len(sync_result.created) == 3
        # Parent should have had update_task_list called
        assert len(adapter.task_list_updates) == 1
        parent_id, children = adapter.task_list_updates[0]
        assert parent_id == "1"
        assert len(children) == 2
