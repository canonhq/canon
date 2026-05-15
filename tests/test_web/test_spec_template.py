"""Tests for the default spec template generator."""

from __future__ import annotations

from datetime import date

from canon.web.spec_template import new_spec_template


class TestNewSpecTemplate:
    def test_default_arguments(self):
        result = new_spec_template()
        assert "title: Untitled Spec" in result
        assert "owner: " in result
        assert "team: " in result
        assert "status: draft" in result
        assert "review_status: draft" in result
        assert "tags: []" in result

    def test_custom_title(self):
        result = new_spec_template(title="Auth System")
        assert "title: Auth System" in result

    def test_custom_owner(self):
        result = new_spec_template(owner="alice")
        assert "owner: alice" in result

    def test_custom_team(self):
        result = new_spec_template(team="platform")
        assert "team: platform" in result

    def test_all_custom_fields(self):
        result = new_spec_template(title="Billing", owner="bob", team="payments")
        assert "title: Billing" in result
        assert "owner: bob" in result
        assert "team: payments" in result

    def test_includes_today_date(self):
        today = date.today().isoformat()
        result = new_spec_template()
        assert f'created: "{today}"' in result

    def test_date_is_today(self):
        result = new_spec_template()
        today = date.today().isoformat()
        assert f'created: "{today}"' in result

    def test_contains_frontmatter_delimiters(self):
        result = new_spec_template()
        assert result.startswith("---\n")
        assert "\n---\n" in result

    def test_contains_default_sections(self):
        result = new_spec_template()
        assert "## 1. Overview" in result
        assert "## 2. Requirements" in result
        assert "## 3. Design" in result
        assert "## 4. Rollout Plan" in result

    def test_contains_acceptance_criteria_section(self):
        result = new_spec_template()
        assert "### Acceptance Criteria" in result
        assert "- [ ] First acceptance criterion" in result
        assert "- [ ] Second acceptance criterion" in result

    def test_return_type_is_string(self):
        result = new_spec_template()
        assert isinstance(result, str)

    def test_special_characters_in_title(self):
        result = new_spec_template(title="Auth & Billing: Phase 1")
        assert "title: Auth & Billing: Phase 1" in result
