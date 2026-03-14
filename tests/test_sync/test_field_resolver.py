"""Tests for field mapping resolution."""

from __future__ import annotations

from canon.parser.models import (
    AcceptanceCriterion,
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
)
from canon.sync.field_resolver import resolve_fields
from canon.sync.mapping import FieldMapConfig


def _make_doc(
    team: str = "platform",
    owner: str = "nick",
    tags: list[str] | None = None,
) -> SpecDocument:
    return SpecDocument(
        file_path="docs/specs/test.md",
        frontmatter=SpecFrontmatter(
            title="Test Spec",
            status="draft",
            owner=owner,
            team=team,
            tags=tags or ["backend", "api"],
        ),
        sections=[],
        raw="",
    )


def _make_section(
    title: str = "API Integration",
    section_number: str = "2.1",
    depth: int = 3,
    acs: list[str] | None = None,
) -> SpecSection:
    criteria = [AcceptanceCriterion(text=t, checked=False, line=i) for i, t in enumerate(acs or [])]
    return SpecSection(
        id="2.1-api-integration",
        section_number=section_number,
        title=title,
        depth=depth,
        content="Some content here.",
        status=SectionStatus(state="todo"),
        acceptance_criteria=criteria,
        start_line=10,
        end_line=20,
    )


class TestResolveFields:
    def test_empty_field_map(self) -> None:
        standard, custom = resolve_fields(_make_section(), _make_doc(), None)
        assert standard == {}
        assert custom == {}

    def test_standard_frontmatter_fields(self) -> None:
        fm = FieldMapConfig(
            standard={
                "frontmatter.team": "component",
                "frontmatter.owner": "assignee",
                "frontmatter.tags": "labels",
            }
        )
        standard, _custom = resolve_fields(_make_section(), _make_doc(), fm)
        assert standard["component"] == "platform"
        assert standard["assignee"] == "nick"
        assert standard["labels"] == ["backend", "api"]

    def test_standard_section_fields(self) -> None:
        fm = FieldMapConfig(
            standard={
                "section.title": "summary",
                "section.section_number": "key_prefix",
                "section.depth": "level",
            }
        )
        standard, _ = resolve_fields(_make_section(), _make_doc(), fm)
        assert standard["summary"] == "API Integration"
        assert standard["key_prefix"] == "2.1"
        assert standard["level"] == 3

    def test_acceptance_criteria_as_list(self) -> None:
        fm = FieldMapConfig(standard={"section.acceptance_criteria": "checklist"})
        section = _make_section(acs=["AC one", "AC two"])
        standard, _ = resolve_fields(section, _make_doc(), fm)
        assert standard["checklist"] == ["AC one", "AC two"]

    def test_custom_field_literal(self) -> None:
        fm = FieldMapConfig(custom={"customfield_10001": "literal:canon-managed"})
        _, custom = resolve_fields(_make_section(), _make_doc(), fm)
        assert custom["customfield_10001"] == "canon-managed"

    def test_custom_field_indexed(self) -> None:
        fm = FieldMapConfig(custom={"customfield_10002": "frontmatter.tags[0]"})
        _, custom = resolve_fields(_make_section(), _make_doc(), fm)
        assert custom["customfield_10002"] == "backend"

    def test_indexed_out_of_bounds_returns_nothing(self) -> None:
        fm = FieldMapConfig(custom={"customfield_10002": "frontmatter.tags[99]"})
        _, custom = resolve_fields(_make_section(), _make_doc(tags=[]), fm)
        assert "customfield_10002" not in custom

    def test_nonexistent_field_skipped(self) -> None:
        fm = FieldMapConfig(standard={"frontmatter.title": "summary"})
        standard, _ = resolve_fields(_make_section(), _make_doc(), fm)
        assert standard["summary"] == "Test Spec"
