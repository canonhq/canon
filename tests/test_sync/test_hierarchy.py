"""Tests for hierarchy template resolution."""

from __future__ import annotations

from canon.parser.models import SectionStatus, SpecSection, TicketLink
from canon.sync.hierarchy import find_parent_ticket_id, resolve_issue_type
from canon.sync.mapping import HierarchyConfig


def _section(
    depth: int = 2,
    section_number: str = "2",
    ticket_id: str | None = None,
) -> SpecSection:
    return SpecSection(
        id=f"{section_number}-test",
        section_number=section_number,
        title="Test",
        depth=depth,
        content="",
        status=SectionStatus(state="todo"),
        ticket_link=TicketLink(system="jira", ticket_id=ticket_id) if ticket_id else None,
        start_line=1,
        end_line=5,
    )


class TestResolveIssueType:
    def test_default_is_task(self) -> None:
        assert resolve_issue_type(_section(depth=2)) == "Task"

    def test_none_config_returns_task(self) -> None:
        assert resolve_issue_type(_section(depth=2), None) == "Task"

    def test_depth_mapping(self) -> None:
        config = HierarchyConfig(depth_to_type={2: "Epic", 3: "Story", 4: "Sub-task"})
        assert resolve_issue_type(_section(depth=2), config) == "Epic"
        assert resolve_issue_type(_section(depth=3), config) == "Story"
        assert resolve_issue_type(_section(depth=4), config) == "Sub-task"

    def test_unmapped_depth_falls_back_to_default(self) -> None:
        config = HierarchyConfig(
            depth_to_type={2: "Epic"},
            default_type="Story",
        )
        assert resolve_issue_type(_section(depth=3), config) == "Story"

    def test_empty_depth_map_uses_default(self) -> None:
        config = HierarchyConfig(default_type="Bug")
        assert resolve_issue_type(_section(depth=2), config) == "Bug"


class TestFindParentTicketId:
    def test_no_config_returns_none(self) -> None:
        parent = _section(depth=2, ticket_id="PAY-1")
        child = _section(depth=3, section_number="2.1")
        assert find_parent_ticket_id(child, [parent]) is None

    def test_auto_parent_false_returns_none(self) -> None:
        config = HierarchyConfig(auto_parent=False)
        parent = _section(depth=2, ticket_id="PAY-1")
        child = _section(depth=3, section_number="2.1")
        assert find_parent_ticket_id(child, [parent], config) is None

    def test_finds_parent_ticket(self) -> None:
        config = HierarchyConfig(auto_parent=True)
        parent = _section(depth=2, ticket_id="PAY-1")
        child = _section(depth=3, section_number="2.1")
        result = find_parent_ticket_id(child, [parent], config)
        assert result == "PAY-1"

    def test_finds_nearest_parent(self) -> None:
        config = HierarchyConfig(auto_parent=True)
        grandparent = _section(depth=2, section_number="1", ticket_id="PAY-1")
        parent = _section(depth=3, section_number="1.1", ticket_id="PAY-2")
        child = _section(depth=4, section_number="1.1.1")
        result = find_parent_ticket_id(child, [grandparent, parent], config)
        assert result == "PAY-2"

    def test_no_parent_with_ticket(self) -> None:
        config = HierarchyConfig(auto_parent=True)
        parent = _section(depth=2)  # no ticket
        child = _section(depth=3, section_number="2.1")
        result = find_parent_ticket_id(child, [parent], config)
        assert result is None

    def test_same_depth_not_matched(self) -> None:
        config = HierarchyConfig(auto_parent=True)
        sibling = _section(depth=3, section_number="2.1", ticket_id="PAY-1")
        section = _section(depth=3, section_number="2.2")
        result = find_parent_ticket_id(section, [sibling], config)
        assert result is None
