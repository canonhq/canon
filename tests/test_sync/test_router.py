"""Tests for multi-system routing."""

from __future__ import annotations

from canon.parser.models import (
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
)
from canon.sync.mapping import RoutingRule, TicketSystemConfig
from canon.sync.router import resolve_all_targets, resolve_target


def _make_doc(
    team: str = "platform",
    owner: str = "nick",
    tags: list[str] | None = None,
    file_path: str = "docs/specs/test.md",
) -> SpecDocument:
    return SpecDocument(
        file_path=file_path,
        frontmatter=SpecFrontmatter(
            title="Test Spec",
            status="draft",
            owner=owner,
            team=team,
            tags=tags or [],
        ),
        sections=[],
        raw="",
    )


def _make_section() -> SpecSection:
    return SpecSection(
        id="2-test",
        section_number="2",
        title="Test",
        depth=2,
        content="",
        status=SectionStatus(state="todo"),
        start_line=1,
        end_line=5,
    )


SYSTEMS = {
    "engineering": TicketSystemConfig(system="jira", project="ENG"),
    "operations": TicketSystemConfig(system="jira", project="OPS"),
    "oss": TicketSystemConfig(system="github", project="org/repo"),
}


class TestResolveTarget:
    def test_single_system_no_routing(self) -> None:
        systems = {"primary": TicketSystemConfig(system="jira", project="PAY")}
        result = resolve_target(_make_section(), _make_doc(), [], systems)
        assert result == "primary"

    def test_no_systems_returns_none(self) -> None:
        result = resolve_target(_make_section(), _make_doc(), [], {})
        assert result is None

    def test_multiple_systems_no_routing_returns_none(self) -> None:
        result = resolve_target(_make_section(), _make_doc(), [], SYSTEMS)
        assert result is None

    def test_tag_match(self) -> None:
        routing = [
            RoutingRule(match={"tags": ["infrastructure"]}, target="operations"),
            RoutingRule(match={"default": True}, target="engineering"),
        ]
        doc = _make_doc(tags=["infrastructure", "backend"])
        result = resolve_target(_make_section(), doc, routing, SYSTEMS)
        assert result == "operations"

    def test_tag_no_match_falls_through(self) -> None:
        routing = [
            RoutingRule(match={"tags": ["infrastructure"]}, target="operations"),
            RoutingRule(match={"default": True}, target="engineering"),
        ]
        doc = _make_doc(tags=["frontend"])
        result = resolve_target(_make_section(), doc, routing, SYSTEMS)
        assert result == "engineering"

    def test_team_match(self) -> None:
        routing = [
            RoutingRule(match={"team": "ops"}, target="operations"),
            RoutingRule(match={"default": True}, target="engineering"),
        ]
        doc = _make_doc(team="ops")
        result = resolve_target(_make_section(), doc, routing, SYSTEMS)
        assert result == "operations"

    def test_owner_match(self) -> None:
        routing = [
            RoutingRule(match={"owner": "alice"}, target="oss"),
            RoutingRule(match={"default": True}, target="engineering"),
        ]
        doc = _make_doc(owner="alice")
        result = resolve_target(_make_section(), doc, routing, SYSTEMS)
        assert result == "oss"

    def test_path_glob_match(self) -> None:
        routing = [
            RoutingRule(match={"path": "docs/rfcs/*"}, target="oss"),
            RoutingRule(match={"default": True}, target="engineering"),
        ]
        doc = _make_doc(file_path="docs/rfcs/rfc-001.md")
        result = resolve_target(_make_section(), doc, routing, SYSTEMS)
        assert result == "oss"

    def test_default_match(self) -> None:
        routing = [RoutingRule(match={"default": True}, target="engineering")]
        result = resolve_target(_make_section(), _make_doc(), routing, SYSTEMS)
        assert result == "engineering"

    def test_first_match_wins(self) -> None:
        routing = [
            RoutingRule(match={"tags": ["api"]}, target="oss"),
            RoutingRule(match={"tags": ["api"]}, target="operations"),
            RoutingRule(match={"default": True}, target="engineering"),
        ]
        doc = _make_doc(tags=["api"])
        result = resolve_target(_make_section(), doc, routing, SYSTEMS)
        assert result == "oss"

    def test_no_match_returns_none(self) -> None:
        routing = [
            RoutingRule(match={"tags": ["nonexistent"]}, target="oss"),
        ]
        result = resolve_target(_make_section(), _make_doc(), routing, SYSTEMS)
        assert result is None

    def test_multi_criteria_and_semantics_all_match(self) -> None:
        """Multiple criteria use AND semantics — all must match."""
        routing = [
            RoutingRule(match={"tags": ["api"], "team": "platform"}, target="engineering"),
            RoutingRule(match={"default": True}, target="oss"),
        ]
        doc = _make_doc(tags=["api"], team="platform")
        result = resolve_target(_make_section(), doc, routing, SYSTEMS)
        assert result == "engineering"

    def test_multi_criteria_and_semantics_partial_match_fails(self) -> None:
        """If only one of multiple criteria matches, the rule does NOT match."""
        routing = [
            RoutingRule(match={"tags": ["api"], "team": "ops"}, target="operations"),
            RoutingRule(match={"default": True}, target="engineering"),
        ]
        # Tags match but team does not
        doc = _make_doc(tags=["api"], team="platform")
        result = resolve_target(_make_section(), doc, routing, SYSTEMS)
        assert result == "engineering"  # falls through to default

    def test_multi_criteria_team_and_owner(self) -> None:
        routing = [
            RoutingRule(match={"team": "ops", "owner": "alice"}, target="operations"),
            RoutingRule(match={"default": True}, target="engineering"),
        ]
        # Only team matches, not owner
        doc = _make_doc(team="ops", owner="bob")
        result = resolve_target(_make_section(), doc, routing, SYSTEMS)
        assert result == "engineering"

        # Both match
        doc2 = _make_doc(team="ops", owner="alice")
        result2 = resolve_target(_make_section(), doc2, routing, SYSTEMS)
        assert result2 == "operations"


class TestResolveAllTargets:
    def test_returns_primary_and_shadows(self) -> None:
        systems = {
            "linear": TicketSystemConfig(system="linear", project="CANON"),
            "jira": TicketSystemConfig(system="jira", project="CAN"),
            "github": TicketSystemConfig(system="github", project="canonhq/canon"),
        }
        routing = [
            RoutingRule(
                match={"tags": ["product"]},
                target="linear",
                shadow_targets=["jira", "github"],
            ),
            RoutingRule(match={"default": True}, target="linear"),
        ]
        doc = _make_doc(tags=["product"])
        primary, shadows = resolve_all_targets(None, doc, routing, systems)
        assert primary == "linear"
        assert shadows == ["jira", "github"]

    def test_no_routing_single_system_no_shadows(self) -> None:
        systems = {"primary": TicketSystemConfig(system="jira", project="PAY")}
        primary, shadows = resolve_all_targets(_make_section(), _make_doc(), [], systems)
        assert primary == "primary"
        assert shadows == []

    def test_no_match_returns_none(self) -> None:
        systems = {
            "linear": TicketSystemConfig(system="linear", project="CANON"),
        }
        routing = [RoutingRule(match={"tags": ["nonexistent"]}, target="linear")]
        primary, shadows = resolve_all_targets(_make_section(), _make_doc(), routing, systems)
        assert primary is None
        assert shadows == []
