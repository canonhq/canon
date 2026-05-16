"""Port of src/spec-parser/__tests__/parse.test.ts — 32 tests."""

from __future__ import annotations

from canon.parser import (
    ParseOptions,
    RealizationRef,
    SpecFrontmatter,
    extract_comments_from_content,
    extract_delta_comment,
    parse_acceptance_criteria,
    parse_frontmatter,
    parse_spec,
    parse_status_comment,
    parse_ticket_comment,
)
from canon.parser.parse import REALIZATION_RE

# ─── Frontmatter ────────────────────────────────────────


class TestParseFrontmatter:
    def test_extracts_all_frontmatter_fields(self):
        raw = """---
title: "Test Spec"
status: in_progress
owner: alice
team: platform
ticket_project: PLAT
created: 2026-01-01
updated: 2026-01-15
tags: [auth, security]
---

# Content here"""

        fm, _content, diagnostics = parse_frontmatter(raw)
        assert fm.title == "Test Spec"
        assert fm.status == "in_progress"
        assert fm.owner == "alice"
        assert fm.team == "platform"
        assert fm.ticket_project == "PLAT"
        assert fm.tags == ["auth", "security"]
        assert len(diagnostics) == 0

    def test_provides_defaults_for_missing_fields(self):
        raw = """---
status: draft
---

# Minimal"""

        fm, _content, diagnostics = parse_frontmatter(raw)
        assert fm.title == "Untitled Spec"
        assert fm.owner == ""
        assert fm.tags == []
        assert len(diagnostics) == 1
        assert diagnostics[0].severity == "warning"

    def test_warns_on_unknown_status(self):
        raw = """---
title: "Test"
status: banana
---
"""
        _fm, _content, diagnostics = parse_frontmatter(raw)
        assert any("banana" in d.message for d in diagnostics)

    def test_parses_ai_exposure_full(self):
        raw = """---
title: "Test"
status: draft
owner: alice
team: platform
ai_exposure: full
---
"""
        fm, _content, diagnostics = parse_frontmatter(raw)
        assert fm.ai_exposure == "full"
        assert len(diagnostics) == 0

    def test_parses_ai_exposure_metadata(self):
        raw = """---
title: "Test"
status: draft
owner: alice
team: platform
ai_exposure: metadata
---
"""
        fm, _content, diagnostics = parse_frontmatter(raw)
        assert fm.ai_exposure == "metadata"
        assert len(diagnostics) == 0

    def test_parses_ai_exposure_none(self):
        raw = """---
title: "Test"
status: draft
owner: alice
team: platform
ai_exposure: none
---
"""
        fm, _content, diagnostics = parse_frontmatter(raw)
        assert fm.ai_exposure == "none"
        assert len(diagnostics) == 0

    def test_ai_exposure_defaults_to_none_when_absent(self):
        raw = """---
title: "Test"
status: draft
owner: alice
team: platform
---
"""
        fm, _content, _diagnostics = parse_frontmatter(raw)
        assert fm.ai_exposure is None

    def test_warns_on_invalid_ai_exposure(self):
        raw = """---
title: "Test"
status: draft
owner: alice
team: platform
ai_exposure: partial
---
"""
        fm, _content, diagnostics = parse_frontmatter(raw)
        assert fm.ai_exposure is None
        assert any("ai_exposure" in d.message for d in diagnostics)


class TestResolveAiExposure:
    def test_frontmatter_none_takes_precedence(self):
        from canon.parser.models import resolve_ai_exposure

        fm = SpecFrontmatter(title="Test", status="draft", owner="a", team="t", ai_exposure="none")
        assert (
            resolve_ai_exposure(fm, restricted_tags=["security"], config_default="full") == "none"
        )

    def test_frontmatter_metadata_takes_precedence(self):
        from canon.parser.models import resolve_ai_exposure

        fm = SpecFrontmatter(
            title="Test", status="draft", owner="a", team="t", ai_exposure="metadata"
        )
        assert resolve_ai_exposure(fm, restricted_tags=[], config_default="full") == "metadata"

    def test_explicit_full_overrides_restricted_tags(self):
        """Frontmatter ai_exposure: full explicitly set should win over restricted_tags."""
        from canon.parser.models import resolve_ai_exposure

        fm = SpecFrontmatter(
            title="Test",
            status="draft",
            owner="a",
            team="t",
            tags=["security"],
            ai_exposure="full",
        )
        assert (
            resolve_ai_exposure(fm, restricted_tags=["security"], config_default="full") == "full"
        )

    def test_restricted_tags_apply_when_not_set(self):
        """When ai_exposure is not set in frontmatter, restricted_tags apply."""
        from canon.parser.models import resolve_ai_exposure

        fm = SpecFrontmatter(
            title="Test",
            status="draft",
            owner="a",
            team="t",
            tags=["security"],
        )
        assert (
            resolve_ai_exposure(fm, restricted_tags=["security"], config_default="full")
            == "metadata"
        )

    def test_config_default_applies_when_not_set(self):
        """When ai_exposure is not set in frontmatter, config default applies."""
        from canon.parser.models import resolve_ai_exposure

        fm = SpecFrontmatter(title="Test", status="draft", owner="a", team="t")
        assert resolve_ai_exposure(fm, restricted_tags=[], config_default="metadata") == "metadata"

    def test_explicit_full_overrides_config_default(self):
        """Frontmatter ai_exposure: full explicitly set should win over config default."""
        from canon.parser.models import resolve_ai_exposure

        fm = SpecFrontmatter(title="Test", status="draft", owner="a", team="t", ai_exposure="full")
        assert resolve_ai_exposure(fm, restricted_tags=[], config_default="metadata") == "full"

    def test_fallback_to_full(self):
        from canon.parser.models import resolve_ai_exposure

        fm = SpecFrontmatter(title="Test", status="draft", owner="a", team="t")
        assert resolve_ai_exposure(fm) == "full"

    def test_resolution_order_frontmatter_over_tags(self):
        from canon.parser.models import resolve_ai_exposure

        fm = SpecFrontmatter(
            title="Test",
            status="draft",
            owner="a",
            team="t",
            tags=["security"],
            ai_exposure="none",
        )
        # Frontmatter "none" beats restricted_tags "metadata"
        assert (
            resolve_ai_exposure(fm, restricted_tags=["security"], config_default="full") == "none"
        )

    def test_no_restricted_tag_match_falls_to_config(self):
        """Tags don't match restricted_tags, so config default applies."""
        from canon.parser.models import resolve_ai_exposure

        fm = SpecFrontmatter(
            title="Test",
            status="draft",
            owner="a",
            team="t",
            tags=["backend"],
        )
        assert (
            resolve_ai_exposure(fm, restricted_tags=["security"], config_default="none") == "none"
        )


# ─── Comments ───────────────────────────────────────────


class TestParseStatusComment:
    def test_parses_basic_status_comment(self):
        result = parse_status_comment("<!-- specwright:system:3 status:in_progress -->")
        assert result is not None
        assert result.state == "in_progress"

    def test_parses_blocked_status_with_ticket_id(self):
        result = parse_status_comment("<!-- specwright:system:3 status:blocked:PAY-200 -->")
        assert result is not None
        assert result.state == "blocked"
        assert result.blocked_by == "PAY-200"

    def test_returns_none_for_non_matching_text(self):
        assert parse_status_comment("just regular text") is None


class TestParseTicketComment:
    def test_parses_jira_ticket(self):
        result = parse_ticket_comment("<!-- specwright:ticket:jira:PAY-142 -->")
        assert result is not None
        assert result.system == "jira"
        assert result.ticket_id == "PAY-142"

    def test_parses_linear_ticket(self):
        result = parse_ticket_comment("<!-- specwright:ticket:linear:ID-301 -->")
        assert result is not None
        assert result.system == "linear"
        assert result.ticket_id == "ID-301"

    def test_returns_none_for_unknown_system(self):
        assert parse_ticket_comment("<!-- specwright:ticket:notion:PAGE-1 -->") is None

    def test_parses_github_ticket_bare_number(self):
        result = parse_ticket_comment("<!-- specwright:ticket:github:7 -->")
        assert result is not None
        assert result.system == "github"
        assert result.ticket_id == "7"

    def test_parses_github_ticket_repo_number(self):
        result = parse_ticket_comment("<!-- specwright:ticket:github:my-repo#7 -->")
        assert result is not None
        assert result.system == "github"
        assert result.ticket_id == "my-repo#7"

    def test_parses_github_ticket_owner_repo_number(self):
        result = parse_ticket_comment("<!-- specwright:ticket:github:acme/widgets#7 -->")
        assert result is not None
        assert result.system == "github"
        assert result.ticket_id == "acme/widgets#7"

    def test_old_format_has_no_url(self):
        result = parse_ticket_comment("<!-- canon:ticket:jira:PAY-142 -->")
        assert result is not None
        assert result.ticket_id == "PAY-142"
        assert result.url is None

    def test_parses_jira_ticket_with_url(self):
        comment = "<!-- canon:ticket:jira:PAY-142 url:https://acme.atlassian.net/browse/PAY-142 -->"
        result = parse_ticket_comment(comment)
        assert result is not None
        assert result.system == "jira"
        assert result.ticket_id == "PAY-142"
        assert result.url == "https://acme.atlassian.net/browse/PAY-142"

    def test_parses_linear_ticket_with_url(self):
        comment = "<!-- canon:ticket:linear:ENG-42 url:https://linear.app/team/issue/ENG-42 -->"
        result = parse_ticket_comment(comment)
        assert result is not None
        assert result.ticket_id == "ENG-42"
        assert result.url == "https://linear.app/team/issue/ENG-42"

    def test_parses_url_with_query_params(self):
        comment = (
            "<!-- canon:ticket:jira:X-1 url:https://x.atlassian.net/browse/X-1?foo=1&bar=2 -->"
        )
        result = parse_ticket_comment(comment)
        assert result is not None
        assert result.url == "https://x.atlassian.net/browse/X-1?foo=1&bar=2"


class TestExtractCommentsFromContent:
    def test_extracts_status_and_ticket(self):
        content = """<!-- specwright:system:2 status:in_progress -->
<!-- specwright:ticket:jira:PAY-142 -->

Core payment processing migration."""

        status, ticket_link = extract_comments_from_content(content, "2")
        assert status.state == "in_progress"
        assert ticket_link is not None
        assert ticket_link.system == "jira"
        assert ticket_link.ticket_id == "PAY-142"

    def test_defaults_to_draft_when_no_comment(self):
        status, ticket_link = extract_comments_from_content("Just some text.", None)
        assert status.state == "draft"
        assert ticket_link is None

    def test_extracts_delta_comment(self):
        content = """<!-- specwright:system:1 status:done -->
<!-- specwright:delta:modified -->

Updated section."""

        status, _ticket_link = extract_comments_from_content(content, "1")
        assert status.state == "done"
        assert extract_delta_comment(content) == "modified"


# ─── Acceptance Criteria ────────────────────────────────


class TestParseAcceptanceCriteria:
    def test_parses_checked_and_unchecked_items(self):
        content = """### Acceptance Criteria

- [ ] First unchecked item
- [x] Second checked item
- [X] Third also checked
- Regular list item"""

        criteria = parse_acceptance_criteria(content, 10)
        assert len(criteria) == 3
        assert criteria[0].text == "First unchecked item"
        assert criteria[0].checked is False
        assert criteria[0].line == 12
        assert criteria[1].text == "Second checked item"
        assert criteria[1].checked is True
        assert criteria[1].line == 13
        assert criteria[2].text == "Third also checked"
        assert criteria[2].checked is True
        assert criteria[2].line == 14

    def test_returns_empty_for_content_without_checkboxes(self):
        assert parse_acceptance_criteria("No checkboxes here.", 1) == []


# ─── REALIZATION_RE ────────────────────────────────────


class TestRealizationRegex:
    def test_matches_basic_realization_comment(self):
        text = "<!-- specwright:realized-in:PR#42 file:src/auth.py:10-20 -->"
        m = REALIZATION_RE.search(text)
        assert m is not None
        assert m.group(1) == "42"
        assert m.group(2) is None  # audit group
        assert m.group(3) == "src/auth.py"
        assert m.group(4) == "10-20"

    def test_matches_without_lines(self):
        text = "<!-- specwright:realized-in:PR#7 file:README.md -->"
        m = REALIZATION_RE.search(text)
        assert m is not None
        assert m.group(1) == "7"
        assert m.group(3) == "README.md"
        assert m.group(4) is None

    def test_no_match_on_unrelated_comment(self):
        text = "<!-- specwright:system:3 status:done -->"
        assert REALIZATION_RE.search(text) is None

    def test_matches_nested_path(self):
        text = "<!-- specwright:realized-in:PR#100 file:src/payments/retry.py:42-60 -->"
        m = REALIZATION_RE.search(text)
        assert m is not None
        assert m.group(3) == "src/payments/retry.py"
        assert m.group(4) == "42-60"

    def test_matches_audit_variant(self):
        text = "<!-- specwright:realized-in:audit file:src/auth.py:10 -->"
        m = REALIZATION_RE.search(text)
        assert m is not None
        assert m.group(1) is None  # no PR number
        assert m.group(2) == "audit"
        assert m.group(3) == "src/auth.py"
        assert m.group(4) == "10"

    def test_matches_audit_variant_without_lines(self):
        text = "<!-- specwright:realized-in:audit file:src/feature.py -->"
        m = REALIZATION_RE.search(text)
        assert m is not None
        assert m.group(1) is None
        assert m.group(2) == "audit"
        assert m.group(3) == "src/feature.py"
        assert m.group(4) is None


class TestParseAcceptanceCriteriaWithRealizations:
    def test_parses_realization_ref_after_checkbox(self):
        content = """- [x] OAuth support
<!-- specwright:realized-in:PR#42 file:src/auth.py:10-20 -->
- [ ] Session management"""
        criteria = parse_acceptance_criteria(content, 1)
        assert len(criteria) == 2
        assert criteria[0].text == "OAuth support"
        assert len(criteria[0].realized_in) == 1
        assert criteria[0].realized_in[0].pr_number == 42
        assert criteria[0].realized_in[0].file_path == "src/auth.py"
        assert criteria[0].realized_in[0].lines == "10-20"
        assert criteria[1].realized_in == []

    def test_parses_multiple_realization_refs(self):
        content = """- [x] Retry logic
<!-- specwright:realized-in:PR#10 file:src/retry.py:5-15 -->
<!-- specwright:realized-in:PR#20 file:src/retry.py:20-30 -->
- [ ] Other"""
        criteria = parse_acceptance_criteria(content, 1)
        assert len(criteria[0].realized_in) == 2
        assert criteria[0].realized_in[0].pr_number == 10
        assert criteria[0].realized_in[1].pr_number == 20

    def test_skips_blank_lines_between_refs(self):
        content = """- [x] Feature A
<!-- specwright:realized-in:PR#5 file:f.py -->

<!-- specwright:realized-in:PR#6 file:g.py -->
Next content"""
        criteria = parse_acceptance_criteria(content, 1)
        assert len(criteria[0].realized_in) == 2

    def test_no_realized_in_when_no_comments(self):
        content = """- [ ] Simple item
Some text below"""
        criteria = parse_acceptance_criteria(content, 1)
        assert len(criteria) == 1
        assert criteria[0].realized_in == []

    def test_parses_audit_realization_ref(self):
        content = """- [x] Feature done
<!-- specwright:realized-in:audit file:src/feature.py:10 -->
- [ ] Other"""
        criteria = parse_acceptance_criteria(content, 1)
        assert len(criteria) == 2
        assert len(criteria[0].realized_in) == 1
        assert criteria[0].realized_in[0].pr_number is None
        assert criteria[0].realized_in[0].file_path == "src/feature.py"
        assert criteria[0].realized_in[0].lines == "10"


# ─── RealizationRef Model ─────────────────────────────


class TestRealizationRefModel:
    def test_basic_creation(self):
        ref = RealizationRef(pr_number=42, file_path="src/auth.py", lines="10-20")
        assert ref.pr_number == 42
        assert ref.file_path == "src/auth.py"
        assert ref.lines == "10-20"

    def test_defaults(self):
        ref = RealizationRef(pr_number=1)
        assert ref.file_path == ""
        assert ref.lines == ""

    def test_pr_number_optional(self):
        ref = RealizationRef(file_path="src/f.py")
        assert ref.pr_number is None
        assert ref.file_path == "src/f.py"


# ─── Full Parser Integration ────────────────────────────


class TestParseSpec:
    def test_parses_minimal_spec(self):
        raw = """---
title: "Minimal"
status: draft
owner: test
team: test
---

# Minimal Spec

## 1. Section One

Some content.

## 2. Section Two

More content."""

        result = parse_spec(raw)
        doc = result.document
        assert doc.frontmatter.title == "Minimal"
        assert len(doc.sections) == 2
        assert doc.sections[0].id == "1-section-one"
        assert doc.sections[0].section_number == "1"
        assert doc.sections[0].title == "Section One"
        assert doc.sections[0].depth == 2
        assert doc.sections[1].id == "2-section-two"
        assert len(result.diagnostics) == 0

    def test_nests_h3_under_preceding_h2(self):
        raw = """---
title: "Nested"
status: draft
owner: test
team: test
---

# Nested

## 1. Parent

### 1.1 Child A

### 1.2 Child B

## 2. Another Parent
"""

        result = parse_spec(raw)
        doc = result.document
        assert len(doc.sections) == 2
        assert len(doc.sections[0].children) == 2
        assert doc.sections[0].children[0].id == "1.1-child-a"
        assert doc.sections[0].children[0].section_number == "1.1"
        assert doc.sections[0].children[1].id == "1.2-child-b"

    def test_handles_unnumbered_sections(self):
        raw = """---
title: "Unnumbered"
status: draft
owner: test
team: test
---

# Unnumbered

## Background

Just context.

## Open Questions

Stuff."""

        result = parse_spec(raw)
        doc = result.document
        assert len(doc.sections) == 2
        assert doc.sections[0].section_number is None
        assert doc.sections[0].id == "background"
        assert doc.sections[1].id == "open-questions"

    def test_strips_content_when_include_content_false(self):
        raw = """---
title: "Strip"
status: draft
owner: test
team: test
---

# Strip

## 1. Section

Lots of content here."""

        result = parse_spec(raw, ParseOptions(include_content=False))
        assert result.document.sections[0].content == ""


# ─── Example Spec Integration Tests ─────────────────────


class TestPaymentsOverhaul:
    def test_parses_frontmatter_correctly(self, payments_spec: str):
        result = parse_spec(
            payments_spec, ParseOptions(file_path="docs/specs/payments-overhaul.md")
        )
        doc = result.document
        assert doc.frontmatter.title == "Payments Overhaul"
        assert doc.frontmatter.status == "in_progress"
        assert doc.frontmatter.owner == "sarah-chen"
        assert doc.frontmatter.team == "payments"
        assert doc.frontmatter.ticket_project == "PAY"
        assert doc.frontmatter.tags == ["payments", "infrastructure", "q1-priority"]

    def test_extracts_all_top_level_sections(self, payments_spec: str):
        result = parse_spec(payments_spec)
        titles = [s.title for s in result.document.sections]
        assert titles == [
            "Background",
            "Stripe Migration",
            "Idempotency Layer",
            "Multi-Currency Support",
            "Monitoring & Alerts",
            "Rollout Plan",
        ]

    def test_extracts_section_numbers(self, payments_spec: str):
        result = parse_spec(payments_spec)
        numbers = [s.section_number for s in result.document.sections]
        assert numbers == ["1", "2", "3", "4", "5", "6"]

    def test_extracts_section_statuses(self, payments_spec: str):
        result = parse_spec(payments_spec)
        sections = result.document.sections
        assert sections[0].status.state == "done"
        assert sections[1].status.state == "in_progress"
        assert sections[2].status.state == "blocked"
        assert sections[2].status.blocked_by == "PAY-200"
        assert sections[3].status.state == "todo"
        assert sections[4].status.state == "deprecated"
        assert sections[5].status.state == "draft"

    def test_extracts_ticket_links(self, payments_spec: str):
        result = parse_spec(payments_spec)
        sections = result.document.sections
        assert sections[1].ticket_link is not None
        assert sections[1].ticket_link.system == "jira"
        assert sections[1].ticket_link.ticket_id == "PAY-142"
        assert sections[2].ticket_link is not None
        assert sections[2].ticket_link.system == "jira"
        assert sections[2].ticket_link.ticket_id == "PAY-150"

    def test_nests_h3_children_under_h2(self, payments_spec: str):
        result = parse_spec(payments_spec)
        stripe = result.document.sections[1]
        assert len(stripe.children) == 2
        assert stripe.children[0].title == "API Integration"
        assert stripe.children[0].section_number == "2.1"
        assert stripe.children[1].title == "Webhook Handler"
        assert stripe.children[1].section_number == "2.2"

    def test_extracts_child_section_statuses_and_tickets(self, payments_spec: str):
        result = parse_spec(payments_spec)
        api_integration = result.document.sections[1].children[0]
        assert api_integration.status.state == "in_progress"
        assert api_integration.ticket_link is not None
        assert api_integration.ticket_link.system == "jira"
        assert api_integration.ticket_link.ticket_id == "PAY-143"

        webhook_handler = result.document.sections[1].children[1]
        assert webhook_handler.status.state == "done"

    def test_extracts_acceptance_criteria_with_check_state(self, payments_spec: str):
        result = parse_spec(payments_spec)
        api_integration = result.document.sections[1].children[0]
        assert len(api_integration.acceptance_criteria) == 4
        assert api_integration.acceptance_criteria[0].checked is False
        assert api_integration.acceptance_criteria[1].checked is True
        assert (
            api_integration.acceptance_criteria[1].text
            == "Stripe webhook endpoint verified with signature checking"
        )

    def test_extracts_multi_currency_children(self, payments_spec: str):
        result = parse_spec(payments_spec)
        multi_currency = result.document.sections[3]
        assert len(multi_currency.children) == 2
        assert multi_currency.children[0].title == "Currency Conversion"
        assert multi_currency.children[0].status.state == "todo"
        assert multi_currency.children[1].title == "Display Formatting"
        assert multi_currency.children[1].status.state == "draft"

    def test_has_no_errors_in_diagnostics(self, payments_spec: str):
        result = parse_spec(
            payments_spec, ParseOptions(file_path="docs/specs/payments-overhaul.md")
        )
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0


class TestAuthMigration:
    def test_parses_frontmatter(self, auth_spec: str):
        result = parse_spec(auth_spec, ParseOptions(file_path="docs/specs/auth-migration.md"))
        doc = result.document
        assert doc.frontmatter.title == "Auth Migration to OAuth 2.0 + PKCE"
        assert doc.frontmatter.status == "todo"
        assert doc.frontmatter.team == "identity"
        assert doc.frontmatter.ticket_project == "ID"

    def test_extracts_all_sections(self, auth_spec: str):
        result = parse_spec(auth_spec)
        assert len(result.document.sections) == 4
        assert [s.section_number for s in result.document.sections] == ["1", "2", "3", "4"]

    def test_extracts_linear_ticket_links(self, auth_spec: str):
        result = parse_spec(auth_spec)
        sections = result.document.sections
        assert sections[1].ticket_link is not None
        assert sections[1].ticket_link.system == "linear"
        assert sections[1].ticket_link.ticket_id == "ID-301"
        assert sections[2].ticket_link is not None
        assert sections[2].ticket_link.system == "linear"
        assert sections[2].ticket_link.ticket_id == "ID-302"

    def test_extracts_acceptance_criteria_from_each_section(self, auth_spec: str):
        result = parse_spec(auth_spec)
        sections = result.document.sections
        assert len(sections[1].acceptance_criteria) == 4
        assert len(sections[2].acceptance_criteria) == 4
        assert len(sections[3].acceptance_criteria) == 3
        # All unchecked
        assert all(not c.checked for c in sections[1].acceptance_criteria)

    def test_has_no_error_diagnostics(self, auth_spec: str):
        result = parse_spec(auth_spec)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0


# ─── Enhanced Frontmatter ──────────────────────────────


class TestEnhancedFrontmatter:
    def test_parses_doc_type(self):
        raw = """---
title: "My ADR"
type: adr
status: draft
owner: alice
team: platform
---

# ADR"""
        fm, _content, diagnostics = parse_frontmatter(raw)
        assert fm.doc_type == "adr"
        assert len(diagnostics) == 0

    def test_defaults_type_to_spec(self):
        raw = """---
title: "No Type"
status: draft
---

# No Type"""
        fm, _content, _diags = parse_frontmatter(raw)
        assert fm.doc_type == "spec"

    def test_warns_on_invalid_type(self):
        raw = """---
title: "Bad Type"
type: whitepaper
status: draft
---
"""
        fm, _content, diagnostics = parse_frontmatter(raw)
        assert fm.doc_type == "spec"
        assert any("whitepaper" in d.message for d in diagnostics)

    def test_parses_depends_on_list(self):
        raw = """---
title: "Depends"
status: draft
depends_on:
  - docs/specs/auth.md
  - docs/specs/payments.md
---
"""
        fm, _content, _diags = parse_frontmatter(raw)
        assert fm.depends_on == ["docs/specs/auth.md", "docs/specs/payments.md"]

    def test_parses_depends_on_csv(self):
        raw = """---
title: "Depends CSV"
status: draft
depends_on: "auth.md, payments.md"
---
"""
        fm, _content, _diags = parse_frontmatter(raw)
        assert fm.depends_on == ["auth.md", "payments.md"]

    def test_defaults_depends_on_to_empty(self):
        raw = """---
title: "No Deps"
status: draft
---
"""
        fm, _content, _diags = parse_frontmatter(raw)
        assert fm.depends_on == []

    def test_parses_supersedes(self):
        raw = """---
title: "New"
status: draft
supersedes: docs/specs/old-auth.md
---
"""
        fm, _content, _diags = parse_frontmatter(raw)
        assert fm.supersedes == "docs/specs/old-auth.md"

    def test_supersedes_empty_string_normalized_to_none(self):
        raw = """---
title: "Empty Supersedes"
status: draft
supersedes: ""
---
"""
        fm, _content, _diags = parse_frontmatter(raw)
        assert fm.supersedes is None

    def test_doc_type_serialization_alias(self):
        """model_dump(by_alias=True) should emit 'type', not 'doc_type'."""
        fm = SpecFrontmatter(title="X", status="draft", owner="", team="", doc_type="adr")
        dumped = fm.model_dump(by_alias=True)
        assert dumped["type"] == "adr"
        assert "doc_type" not in dumped

    def test_parses_review_status(self):
        raw = """---
title: "Review"
status: draft
review_status: in_review
---
"""
        fm, _content, diagnostics = parse_frontmatter(raw)
        assert fm.review_status == "in_review"
        assert not any("review_status" in d.message for d in diagnostics)

    def test_warns_on_invalid_review_status(self):
        raw = """---
title: "Bad Review"
status: draft
review_status: rejected
---
"""
        fm, _content, diagnostics = parse_frontmatter(raw)
        assert fm.review_status is None
        assert any("rejected" in d.message for d in diagnostics)


# ─── Acceptance Criteria Strength ──────────────────────


class TestAcceptanceCriteriaStrength:
    def test_detects_must(self):
        content = "- [ ] System MUST validate input"
        criteria = parse_acceptance_criteria(content, 1)
        assert criteria[0].strength == "MUST"

    def test_detects_should(self):
        content = "- [ ] API SHOULD return 200"
        criteria = parse_acceptance_criteria(content, 1)
        assert criteria[0].strength == "SHOULD"

    def test_detects_may(self):
        content = "- [ ] Response MAY include metadata"
        criteria = parse_acceptance_criteria(content, 1)
        assert criteria[0].strength == "MAY"

    def test_detects_must_not(self):
        content = "- [ ] System MUST NOT leak secrets"
        criteria = parse_acceptance_criteria(content, 1)
        assert criteria[0].strength == "MUST_NOT"

    def test_no_strength_when_absent(self):
        content = "- [ ] Regular requirement with no RFC keywords"
        criteria = parse_acceptance_criteria(content, 1)
        assert criteria[0].strength is None


class TestAcceptanceCriteriaAndScenarios:
    def test_section_with_both_ac_and_scenarios(self):
        """AC and scenarios should both be populated independently."""
        raw = """---
title: "Combined"
status: draft
owner: test
team: test
---

## 1. Feature

- [x] System MUST validate input
- [ ] API SHOULD return 200

#### Scenario: Happy path

- GIVEN valid input
- WHEN submitted
- THEN output MUST be correct"""

        result = parse_spec(raw)
        section = result.document.sections[0]
        assert len(section.acceptance_criteria) == 2
        assert section.acceptance_criteria[0].text == "System MUST validate input"
        assert section.acceptance_criteria[0].strength == "MUST"
        assert len(section.scenarios) == 1
        assert section.scenarios[0].name == "Happy path"
        assert len(section.scenarios[0].steps) == 3


class TestSectionStartLineAlignment:
    """Regression tests for start_line alignment with the raw markdown.

    python-frontmatter does not preserve 1:1 line alignment with the source —
    it consumes whitespace after the closing ``---`` delimiter. The parser
    must compensate so that ``section.start_line`` always points at the
    actual heading line in the original raw text — this is critical for
    ``insert_ticket_links`` to place ticket comments in the right spot
    (and thus for idempotent forward sync).

    Guards against the regression fixed in PR #497: ticket comments were
    inserted one line above the heading, causing forward sync to re-create
    duplicate tickets on every run.
    """

    def test_start_line_matches_heading_with_blank_after_frontmatter(self):
        raw = """---
title: Test
---

# Document Title

Intro paragraph.

## 1. First section

<!-- canon:system:1 status:todo -->

Content here.

## 2. Second section

More content.
"""
        result = parse_spec(raw)
        raw_lines = raw.split("\n")
        for section in result.document.sections:
            heading_line = raw_lines[section.start_line - 1]
            assert heading_line.lstrip().startswith("## "), (
                f"start_line={section.start_line} points to {heading_line!r}, not a heading"
            )

    def test_start_line_matches_heading_without_blank_after_frontmatter(self):
        raw = """---
title: Test
---
# Document Title

## 1. Only section

Content.
"""
        result = parse_spec(raw)
        raw_lines = raw.split("\n")
        for section in result.document.sections:
            heading_line = raw_lines[section.start_line - 1]
            assert heading_line.lstrip().startswith("## ")

    def test_ticket_link_insertion_roundtrip(self):
        """A ticket comment inserted via the writer must be parseable back
        into the correct section's ``ticket_link`` field."""
        from canon.parser.writer import TicketLinkInsertion, insert_ticket_links

        raw = """---
title: Test
ticket_project: CAN
---

# Test Doc

## 1. Section one

<!-- canon:system:1 status:todo -->

Content.

## 2. Section two

<!-- canon:system:2 status:todo -->

More content.
"""
        result = parse_spec(raw)
        doc = result.document

        insertions = [
            TicketLinkInsertion(
                heading_line=doc.sections[0].start_line,
                system="jira",
                ticket_id="CAN-1",
            ),
            TicketLinkInsertion(
                heading_line=doc.sections[1].start_line,
                system="jira",
                ticket_id="CAN-2",
            ),
        ]
        updated = insert_ticket_links(doc, insertions)

        # Re-parse and verify each section is linked to the correct ticket
        result2 = parse_spec(updated)
        assert result2.document.sections[0].ticket_link is not None
        assert result2.document.sections[0].ticket_link.ticket_id == "CAN-1"
        assert result2.document.sections[1].ticket_link is not None
        assert result2.document.sections[1].ticket_link.ticket_id == "CAN-2"


# ─── prose_content computed field ──────────────────────────


class TestProseContent:
    """Tests for SpecSection.prose_content which strips ACs and system comments."""

    def _section(self, content: str) -> object:
        """Parse a minimal spec and return the first section."""
        raw = f"""---
title: Test
status: draft
owner: x
team: x
---

## 1. Section

{content}
"""
        result = parse_spec(raw)
        return result.document.sections[0]

    def test_strips_ac_heading_and_checklist(self):
        s = self._section("Some prose.\n\n### Acceptance Criteria\n\n- [x] Done\n- [ ] Todo")
        assert "Some prose." in s.prose_content
        assert "Acceptance Criteria" not in s.prose_content
        assert "- [x]" not in s.prose_content
        assert "- [ ]" not in s.prose_content

    def test_strips_status_comments(self):
        s = self._section("Prose here.\n<!-- canon:system:github status:done -->")
        assert "Prose here." in s.prose_content
        assert "canon:system" not in s.prose_content

    def test_strips_ticket_comments(self):
        s = self._section("Prose here.\n<!-- canon:ticket:jira:PAY-142 -->")
        assert "Prose here." in s.prose_content
        assert "canon:ticket" not in s.prose_content

    def test_strips_ticket_comments_with_url(self):
        s = self._section(
            "Prose here.\n<!-- canon:ticket:github:456 url:https://github.com/o/r/issues/456 -->"
        )
        assert "Prose here." in s.prose_content
        assert "canon:ticket" not in s.prose_content

    def test_strips_specwright_comments(self):
        s = self._section("Prose.\n<!-- specwright:ticket:github:PROJ-101 -->")
        assert "Prose." in s.prose_content
        assert "specwright:ticket" not in s.prose_content

    def test_empty_content(self):
        s = self._section("")
        assert s.prose_content == ""

    def test_ac_only_returns_empty(self):
        s = self._section("### Acceptance Criteria\n\n- [x] Done")
        assert s.prose_content == ""

    def test_no_ac_heading_preserves_all_prose(self):
        s = self._section("Line one.\n\nLine two.")
        assert "Line one." in s.prose_content
        assert "Line two." in s.prose_content

    def test_trims_trailing_blank_lines(self):
        s = self._section("Prose.\n\n\n")
        assert s.prose_content == "Prose."
