"""Tests for ticket description template rendering."""

from __future__ import annotations

from canon.parser.models import (
    AcceptanceCriterion,
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
)
from canon.sync.mapping import TemplateConfig
from canon.sync.templates import render_description, render_summary


def _make_doc() -> SpecDocument:
    return SpecDocument(
        file_path="docs/specs/test.md",
        frontmatter=SpecFrontmatter(
            title="Test Spec",
            status="draft",
            owner="nick",
            team="platform",
            tags=["backend", "api"],
        ),
        sections=[],
        raw="",
    )


def _make_section(
    content: str = "Some content here.",
    acs: list[str] | None = None,
) -> SpecSection:
    criteria = [AcceptanceCriterion(text=t, checked=False, line=i) for i, t in enumerate(acs or [])]
    return SpecSection(
        id="2.1-api-integration",
        section_number="2.1",
        title="API Integration",
        depth=3,
        content=content,
        status=SectionStatus(state="todo"),
        acceptance_criteria=criteria,
        start_line=10,
        end_line=20,
    )


class TestRenderSummary:
    def test_default_template(self) -> None:
        result = render_summary(_make_section(), _make_doc())
        assert result == "[Test Spec §2.1] API Integration"

    def test_custom_template(self) -> None:
        config = TemplateConfig(summary="{{spec.title}} — {{section.title}}")
        result = render_summary(_make_section(), _make_doc(), config)
        assert result == "Test Spec — API Integration"

    def test_none_config_uses_default(self) -> None:
        result = render_summary(_make_section(), _make_doc(), None)
        assert result == "[Test Spec §2.1] API Integration"


class TestRenderDescription:
    def test_default_includes_structured_template(self) -> None:
        result = render_description(_make_section(), _make_doc())
        assert "> **Spec:**" in result
        assert "**Section:** 2.1" in result
        assert "Some content here." in result
        assert "Canon</a>" in result
        assert "Team:</b> platform" in result
        assert "Owner:</b> nick" in result

    def test_default_uses_clean_content(self) -> None:
        content = "Real content.\n<!-- specwright:system:1 status:todo -->\nMore content."
        result = render_description(_make_section(content=content), _make_doc())
        assert "Real content." in result
        assert "More content." in result
        assert "specwright:system" not in result

    def test_custom_template(self) -> None:
        config = TemplateConfig(
            description="h2. {{section.title}}\n\n{{section.content}}\n\n_Managed by Canon_"
        )
        result = render_description(_make_section(), _make_doc(), config)
        assert "h2. API Integration" in result
        assert "Some content here." in result
        assert "_Managed by Canon_" in result

    def test_each_block_for_acceptance_criteria(self) -> None:
        config = TemplateConfig(
            description="ACs:\n{{#each section.acceptance_criteria}}* {{this}}\n{{/each}}"
        )
        section = _make_section(acs=["AC one", "AC two", "AC three"])
        result = render_description(section, _make_doc(), config)
        assert "* AC one" in result
        assert "* AC two" in result
        assert "* AC three" in result

    def test_spec_url_in_template(self) -> None:
        config = TemplateConfig(description="{{section.content}}\n\nSource: {{spec_url}}")
        result = render_description(
            _make_section(),
            _make_doc(),
            config,
            spec_url="https://canonhq.co/specs/test",
        )
        assert "Source: https://canonhq.co/specs/test" in result

    def test_list_variable_as_comma_separated(self) -> None:
        config = TemplateConfig(description="Tags: {{spec.tags}}")
        result = render_description(_make_section(), _make_doc(), config)
        assert result.startswith("Tags: backend, api")
        assert "canon:section:docs/specs/test:2.1" in result

    def test_empty_each_block(self) -> None:
        config = TemplateConfig(
            description="ACs:\n{{#each section.acceptance_criteria}}* {{this}}\n{{/each}}Done."
        )
        section = _make_section(acs=[])
        result = render_description(section, _make_doc(), config)
        assert result.startswith("ACs:\nDone.")

    def test_content_with_template_syntax_not_expanded(self) -> None:
        """Content containing {{var}} must NOT be further expanded."""
        config = TemplateConfig(description="{{section.content}}")
        section = _make_section(content="See {{spec_url}} for details")
        result = render_description(section, _make_doc(), config, spec_url="https://real.url")
        # The {{spec_url}} in the content should be preserved literally,
        # NOT expanded to the real URL
        assert result.startswith("See {{spec_url}} for details")

    def test_content_with_template_syntax_in_each(self) -> None:
        """List items containing {{var}} must NOT be further expanded."""
        config = TemplateConfig(
            description="{{#each section.acceptance_criteria}}* {{this}}\n{{/each}}"
        )
        section = _make_section(acs=["Check {{spec_url}} link"])
        result = render_description(section, _make_doc(), config, spec_url="https://real.url")
        assert "{{spec_url}}" in result
        assert "https://real.url" not in result
