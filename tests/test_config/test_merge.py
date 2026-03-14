"""Tests for deep merge logic."""

from __future__ import annotations

from canon.config.merge import deep_merge


class TestDeepMerge:
    def test_empty_base_returns_overlay(self) -> None:
        assert deep_merge({}, {"a": 1}) == {"a": 1}

    def test_empty_overlay_returns_base(self) -> None:
        assert deep_merge({"a": 1}, {}) == {"a": 1}

    def test_both_empty(self) -> None:
        assert deep_merge({}, {}) == {}

    def test_scalar_override(self) -> None:
        result = deep_merge({"a": 1, "b": 2}, {"a": 10})
        assert result == {"a": 10, "b": 2}

    def test_list_replace(self) -> None:
        result = deep_merge(
            {"tags": ["a", "b", "c"]},
            {"tags": ["x"]},
        )
        assert result == {"tags": ["x"]}

    def test_nested_dict_merge(self) -> None:
        result = deep_merge(
            {"status_map": {"forward": {"draft": "Backlog", "todo": "Open"}}},
            {"status_map": {"forward": {"todo": "To Do"}}},
        )
        assert result == {"status_map": {"forward": {"draft": "Backlog", "todo": "To Do"}}}

    def test_explicit_none_deletes_key(self) -> None:
        result = deep_merge(
            {"a": 1, "b": 2, "c": 3},
            {"b": None},
        )
        assert result == {"a": 1, "c": 3}

    def test_explicit_none_in_nested_dict(self) -> None:
        result = deep_merge(
            {"field_map": {"standard": {"team": "component"}, "custom": {"f1": "v1"}}},
            {"field_map": {"custom": None}},
        )
        assert result == {"field_map": {"standard": {"team": "component"}}}

    def test_new_keys_in_overlay_added(self) -> None:
        result = deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_deep_nested_merge(self) -> None:
        base = {
            "ticket_systems": {
                "primary": {
                    "system": "jira",
                    "project": "ORG",
                    "status_map": {
                        "forward": {
                            "draft": "Backlog",
                            "todo": "To Do",
                            "done": "Done",
                        }
                    },
                    "hierarchy": {
                        "depth_to_type": {2: "Epic", 3: "Story"},
                        "auto_parent": True,
                    },
                }
            }
        }
        overlay = {
            "ticket_systems": {
                "primary": {
                    "project": "TEAM",
                    "status_map": {
                        "forward": {
                            "todo": "Open",
                        }
                    },
                }
            }
        }
        result = deep_merge(base, overlay)
        primary = result["ticket_systems"]["primary"]
        assert primary["system"] == "jira"  # from base
        assert primary["project"] == "TEAM"  # overridden
        assert primary["status_map"]["forward"]["draft"] == "Backlog"  # from base
        assert primary["status_map"]["forward"]["todo"] == "Open"  # overridden
        assert primary["status_map"]["forward"]["done"] == "Done"  # from base
        assert primary["hierarchy"]["depth_to_type"] == {2: "Epic", 3: "Story"}  # from base

    def test_overlay_dict_over_scalar(self) -> None:
        result = deep_merge({"a": "string"}, {"a": {"nested": True}})
        assert result == {"a": {"nested": True}}

    def test_overlay_scalar_over_dict(self) -> None:
        result = deep_merge({"a": {"nested": True}}, {"a": "string"})
        assert result == {"a": "string"}
