"""Tests for web render helpers (comment stripping, ticket links, scenarios, deltas)."""

from __future__ import annotations

from canon.parser.models import (
    Scenario,
    ScenarioStep,
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
    TicketLink,
)
from canon.web.render import (
    _delta_badge,
    _render_scenarios,
    _strip_canon_comments,
    _ticket_link_html,
    render_markdown_html,
    render_spec_html,
)

# ---------------------------------------------------------------------------
# Comment stripping
# ---------------------------------------------------------------------------


class TestStripSpecwrightComments:
    def test_specwright_comments_stripped(self):
        content = "Before <!-- specwright:system:1 status:done --> After"
        result = _strip_canon_comments(content)
        assert "specwright" not in result
        assert "Before" in result
        assert "After" in result

    def test_non_specwright_comments_preserved(self):
        content = "Before <!-- TODO: fix this --> After"
        result = _strip_canon_comments(content)
        assert "<!-- TODO: fix this -->" in result

    def test_ticket_comments_stripped(self):
        content = "Content <!-- specwright:ticket:github:#123 --> more"
        result = _strip_canon_comments(content)
        assert "specwright:ticket" not in result
        assert "Content" in result
        assert "more" in result

    def test_multiple_comments_stripped(self):
        content = (
            "Line 1 <!-- specwright:system:1 status:done -->\n"
            "Line 2 <!-- specwright:ticket:jira:PROJ-42 -->\n"
            "Line 3"
        )
        result = _strip_canon_comments(content)
        assert "specwright" not in result
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result


class TestSpecwrightCommentsInRendering:
    def test_comments_not_in_rendered_html(self):
        """Rendered spec HTML should not contain specwright comments."""
        doc = SpecDocument(
            file_path="docs/specs/test.md",
            frontmatter=SpecFrontmatter(title="Test", status="draft", owner="alice", team="eng"),
            sections=[
                SpecSection(
                    id="s1",
                    section_number="1",
                    title="Section",
                    depth=2,
                    content="Content <!-- specwright:system:1 status:done --> here.",
                    status=SectionStatus(state="done"),
                    children=[],
                    start_line=1,
                    end_line=5,
                ),
            ],
            raw="# Test\n...",
        )
        html = render_spec_html(doc)
        assert "specwright:system" not in html
        assert "Content" in html


# ---------------------------------------------------------------------------
# Ticket links
# ---------------------------------------------------------------------------


class TestTicketLinkHtml:
    def test_github_ticket_renders_as_link(self):
        ticket = TicketLink(system="github", ticket_id="#42")
        html = _ticket_link_html(ticket, repo_owner="org", repo_name="repo")
        assert 'href="https://github.com/org/repo/issues/42"' in html
        assert "<a " in html

    def test_github_ticket_with_repo_prefix(self):
        ticket = TicketLink(system="github", ticket_id="other/repo#42")
        html = _ticket_link_html(ticket, repo_owner="org", repo_name="main-repo")
        assert 'href="https://github.com/other/repo/issues/42"' in html
        assert "<a " in html

    def test_github_ticket_no_repo_context(self):
        ticket = TicketLink(system="github", ticket_id="#42")
        html = _ticket_link_html(ticket)
        assert "<span " in html
        assert "<a " not in html

    def test_jira_ticket_without_url(self):
        ticket = TicketLink(system="jira", ticket_id="PROJ-123")
        html = _ticket_link_html(ticket)
        assert "PROJ-123" in html
        assert "<a " not in html  # no link without URL

    def test_jira_ticket_with_url(self):
        ticket = TicketLink(
            system="jira", ticket_id="PROJ-123", url="https://acme.atlassian.net/browse/PROJ-123"
        )
        html = _ticket_link_html(ticket)
        assert 'href="https://acme.atlassian.net/browse/PROJ-123"' in html

    def test_linear_ticket_without_url(self):
        ticket = TicketLink(system="linear", ticket_id="ENG-456")
        html = _ticket_link_html(ticket)
        assert "ENG-456" in html
        assert "<a " not in html  # no link without URL

    def test_linear_ticket_with_url(self):
        ticket = TicketLink(
            system="linear", ticket_id="ENG-456", url="https://linear.app/team/issue/ENG-456"
        )
        html = _ticket_link_html(ticket)
        assert 'href="https://linear.app/team/issue/ENG-456"' in html

    def test_javascript_url_rejected(self):
        ticket = TicketLink(system="jira", ticket_id="PROJ-1", url="javascript:alert(1)")
        html = _ticket_link_html(ticket)
        assert "<a " not in html
        assert "PROJ-1" in html

    def test_data_url_rejected(self):
        ticket = TicketLink(system="jira", ticket_id="PROJ-1", url="data:text/html,<h1>x</h1>")
        html = _ticket_link_html(ticket)
        assert "<a " not in html

    def test_url_includes_rel_noopener(self):
        ticket = TicketLink(
            system="jira", ticket_id="PROJ-1", url="https://acme.atlassian.net/browse/PROJ-1"
        )
        html = _ticket_link_html(ticket)
        assert 'rel="noopener"' in html

    def test_github_ticket_with_stored_url_uses_it(self):
        ticket = TicketLink(
            system="github", ticket_id="#42", url="https://github.com/org/repo/issues/42"
        )
        html = _ticket_link_html(ticket)
        assert 'href="https://github.com/org/repo/issues/42"' in html

    def test_non_ticket_returns_empty(self):
        html = _ticket_link_html("not a ticket")
        assert html == ""


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


class TestRenderMarkdownHtml:
    def test_renders_basic_markdown(self):
        html = render_markdown_html("# Hello\n\nSome **bold** text.")
        assert "<h1>" in html
        assert "<strong>bold</strong>" in html
        assert "markdown-content" in html

    def test_strips_specwright_comments(self):
        html = render_markdown_html("Before <!-- specwright:system:1 status:done --> After")
        assert "specwright" not in html
        assert "Before" in html
        assert "After" in html

    def test_empty_content(self):
        html = render_markdown_html("")
        assert "markdown-content" in html


# ---------------------------------------------------------------------------
# Delta badges
# ---------------------------------------------------------------------------


class TestDeltaBadge:
    def test_added_badge(self):
        html = _delta_badge("added")
        assert "Added" in html
        assert "bg-green" in html

    def test_modified_badge(self):
        html = _delta_badge("modified")
        assert "Modified" in html
        assert "bg-amber" in html

    def test_removed_badge(self):
        html = _delta_badge("removed")
        assert "Removed" in html
        assert "bg-red" in html

    def test_delta_in_rendered_section(self):
        doc = SpecDocument(
            file_path="test.md",
            frontmatter=SpecFrontmatter(title="Test", status="draft", owner="", team=""),
            sections=[
                SpecSection(
                    id="s1",
                    section_number="1",
                    title="New Feature",
                    depth=2,
                    content="Content.",
                    status=SectionStatus(state="draft"),
                    delta="added",
                    children=[],
                    start_line=1,
                    end_line=5,
                ),
            ],
            raw="",
        )
        html = render_spec_html(doc)
        assert "Added" in html
        assert "bg-green" in html


# ---------------------------------------------------------------------------
# BDD Scenario rendering
# ---------------------------------------------------------------------------


class TestRenderScenarios:
    def test_renders_scenario_with_steps(self):
        scenarios = [
            Scenario(
                name="User logs in",
                steps=[
                    ScenarioStep(keyword="GIVEN", text="a registered user", line=1),
                    ScenarioStep(keyword="WHEN", text="they submit credentials", line=2),
                    ScenarioStep(keyword="THEN", text="they get a token", line=3),
                ],
                start_line=1,
                end_line=3,
            )
        ]
        html = _render_scenarios(scenarios)
        assert "Scenario: User logs in" in html
        assert "GIVEN" in html
        assert "WHEN" in html
        assert "THEN" in html
        assert "a registered user" in html

    def test_renders_strength_tag(self):
        scenarios = [
            Scenario(
                name="Auth check",
                steps=[
                    ScenarioStep(keyword="THEN", text="return 401", strength="MUST", line=1),
                ],
                start_line=1,
                end_line=1,
            )
        ]
        html = _render_scenarios(scenarios)
        assert "[MUST]" in html

    def test_empty_scenarios_returns_empty(self):
        assert _render_scenarios([]) == ""

    def test_escapes_html_in_scenario_name(self):
        scenarios = [
            Scenario(
                name='<script>alert("xss")</script>',
                steps=[ScenarioStep(keyword="GIVEN", text="a condition", line=1)],
                start_line=1,
                end_line=1,
            )
        ]
        html = _render_scenarios(scenarios)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_escapes_html_in_step_text(self):
        scenarios = [
            Scenario(
                name="Safe",
                steps=[
                    ScenarioStep(keyword="GIVEN", text='<img src=x onerror="alert(1)">', line=1),
                ],
                start_line=1,
                end_line=1,
            )
        ]
        html = _render_scenarios(scenarios)
        assert "<img " not in html
        assert "&lt;img" in html
