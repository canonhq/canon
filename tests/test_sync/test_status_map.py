"""Port of status-map tests — bidirectional status mapping."""

from __future__ import annotations

import pytest

from canon.parser.models import SectionStatus
from canon.sync.status_map import (
    github_to_spec_status,
    jira_category_to_spec_status,
    linear_type_to_spec_status,
    spec_status_to_github,
    spec_status_to_jira,
    spec_status_to_linear,
)


class TestSpecToJira:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("draft", "Backlog"),
            ("todo", "To Do"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("blocked", "Blocked"),
            ("deprecated", "Won't Do"),
        ],
    )
    def test_maps_spec_status_to_jira(self, state: str, expected: str):
        assert spec_status_to_jira(SectionStatus(state=state)) == expected  # type: ignore[arg-type]


class TestSpecToLinear:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("draft", "Backlog"),
            ("todo", "Todo"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("blocked", "In Progress"),
            ("deprecated", "Canceled"),
        ],
    )
    def test_maps_spec_status_to_linear(self, state: str, expected: str):
        assert spec_status_to_linear(SectionStatus(state=state)) == expected  # type: ignore[arg-type]


class TestJiraCategoryToSpec:
    @pytest.mark.parametrize(
        ("category", "expected"),
        [
            ("new", "todo"),
            ("indeterminate", "in_progress"),
            ("done", "done"),
        ],
    )
    def test_maps_jira_category_to_spec(self, category: str, expected: str):
        assert jira_category_to_spec_status(category).state == expected

    def test_unknown_category_defaults_to_draft(self):
        assert jira_category_to_spec_status("unknown").state == "draft"


class TestLinearTypeToSpec:
    @pytest.mark.parametrize(
        ("state_type", "expected"),
        [
            ("backlog", "draft"),
            ("unstarted", "todo"),
            ("started", "in_progress"),
            ("completed", "done"),
            ("canceled", "deprecated"),
        ],
    )
    def test_maps_linear_type_to_spec(self, state_type: str, expected: str):
        assert linear_type_to_spec_status(state_type).state == expected

    def test_unknown_type_defaults_to_draft(self):
        assert linear_type_to_spec_status("unknown").state == "draft"


class TestSpecToGitHub:
    def test_draft_is_open_with_draft_label(self):
        result = spec_status_to_github(SectionStatus(state="draft"))
        assert result.state == "open"
        assert result.label == "canon:draft"

    def test_done_is_closed_with_done_label(self):
        result = spec_status_to_github(SectionStatus(state="done"))
        assert result.state == "closed"
        assert result.label == "canon:done"

    def test_in_progress_is_open(self):
        result = spec_status_to_github(SectionStatus(state="in_progress"))
        assert result.state == "open"
        assert result.label == "canon:in-progress"


class TestGitHubToSpec:
    def test_canon_label_takes_priority(self):
        status = github_to_spec_status("open", ["canon:in-progress", "bug"])
        assert status.state == "in_progress"

    def test_done_label_on_closed_issue(self):
        status = github_to_spec_status("closed", ["canon:done"])
        assert status.state == "done"

    def test_deprecated_label(self):
        status = github_to_spec_status("closed", ["canon:deprecated"])
        assert status.state == "deprecated"

    def test_fallback_open_is_todo(self):
        status = github_to_spec_status("open", [])
        assert status.state == "todo"

    def test_fallback_closed_is_done(self):
        status = github_to_spec_status("closed", [])
        assert status.state == "done"
