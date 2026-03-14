"""Tests for configurable status map resolution (resolve_forward / resolve_reverse)."""

from __future__ import annotations

from canon.sync.mapping import StatusMapConfig
from canon.sync.status_map import (
    resolve_forward,
    resolve_forward_github,
    resolve_reverse,
    resolve_reverse_github,
)


class TestResolveForward:
    def test_default_jira_mappings(self) -> None:
        assert resolve_forward("jira", "todo") == "To Do"
        assert resolve_forward("jira", "in_progress") == "In Progress"
        assert resolve_forward("jira", "done") == "Done"

    def test_default_linear_mappings(self) -> None:
        assert resolve_forward("linear", "todo") == "Todo"
        assert resolve_forward("linear", "done") == "Done"

    def test_custom_config_overrides_defaults(self) -> None:
        custom = StatusMapConfig(
            forward={"todo": "Open", "in_progress": "In Dev", "done": "Closed"}
        )
        assert resolve_forward("jira", "todo", custom) == "Open"
        assert resolve_forward("jira", "in_progress", custom) == "In Dev"

    def test_custom_config_falls_back_for_unmapped_states(self) -> None:
        custom = StatusMapConfig(forward={"todo": "Open"})
        # "done" not in custom forward → falls back to system default
        assert resolve_forward("jira", "done", custom) == "Done"

    def test_none_config_uses_defaults(self) -> None:
        assert resolve_forward("jira", "draft", None) == "Backlog"

    def test_unknown_system_returns_backlog(self) -> None:
        assert resolve_forward("azure", "todo") == "Backlog"


class TestResolveReverse:
    def test_default_jira_reverse(self) -> None:
        result = resolve_reverse("jira", "new")
        assert result.state == "todo"

    def test_default_linear_reverse(self) -> None:
        result = resolve_reverse("linear", "started")
        assert result.state == "in_progress"

    def test_custom_reverse_takes_precedence(self) -> None:
        custom = StatusMapConfig(reverse={"On Hold": "blocked"})
        result = resolve_reverse("jira", "On Hold", custom)
        assert result.state == "blocked"

    def test_custom_reverse_falls_back_to_default(self) -> None:
        custom = StatusMapConfig(reverse={"On Hold": "blocked"})
        # "new" not in custom → falls back to jira default
        result = resolve_reverse("jira", "new", custom)
        assert result.state == "todo"

    def test_unmapped_status_uses_fallback(self) -> None:
        custom = StatusMapConfig(fallback="todo")
        result = resolve_reverse("jira", "completely_unknown", custom)
        assert result.state == "todo"

    def test_default_fallback_is_draft(self) -> None:
        result = resolve_reverse("jira", "completely_unknown")
        assert result.state == "draft"


class TestResolveForwardGitHub:
    def test_default_github_mappings(self) -> None:
        result = resolve_forward_github("todo")
        assert result.state == "open"
        assert result.label == "canon:todo"

    def test_done_is_closed(self) -> None:
        result = resolve_forward_github("done")
        assert result.state == "closed"
        assert result.label == "canon:done"

    def test_custom_github_forward(self) -> None:
        custom = StatusMapConfig(forward={"todo": "open|needs-triage", "done": "closed|completed"})
        result = resolve_forward_github("todo", custom)
        assert result.state == "open"
        assert result.label == "needs-triage"


class TestResolveReverseGitHub:
    def test_label_takes_priority(self) -> None:
        result = resolve_reverse_github("open", ["specwright:in-progress", "bug"])
        assert result.state == "in_progress"

    def test_fallback_open_is_todo(self) -> None:
        result = resolve_reverse_github("open", [])
        assert result.state == "todo"

    def test_fallback_closed_is_done(self) -> None:
        result = resolve_reverse_github("closed", [])
        assert result.state == "done"

    def test_custom_reverse_label(self) -> None:
        custom = StatusMapConfig(reverse={"needs-triage": "todo"})
        result = resolve_reverse_github("open", ["needs-triage"], custom)
        assert result.state == "todo"
