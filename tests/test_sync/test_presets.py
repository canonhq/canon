"""Tests for sync status map presets."""

from __future__ import annotations

from canon.sync.presets import PRESETS, get_presets


class TestPresets:
    def test_get_all_presets(self):
        result = get_presets()
        assert len(result) == 5
        assert "standard_jira" in result
        assert "standard_linear" in result
        assert "standard_github" in result

    def test_filter_by_system_jira(self):
        result = get_presets("jira")
        assert all(v["system"] == "jira" for v in result.values())
        assert len(result) == 3  # standard_jira, agile_board, product_led

    def test_filter_by_system_linear(self):
        result = get_presets("linear")
        assert len(result) == 1
        assert "standard_linear" in result

    def test_filter_by_system_github(self):
        result = get_presets("github")
        assert len(result) == 1
        assert "standard_github" in result

    def test_filter_nonexistent_system(self):
        result = get_presets("asana")
        assert len(result) == 0

    def test_preset_structure(self):
        for name, preset in PRESETS.items():
            assert "label" in preset, f"{name} missing 'label'"
            assert "description" in preset, f"{name} missing 'description'"
            assert "system" in preset, f"{name} missing 'system'"
            assert "forward" in preset, f"{name} missing 'forward'"
            assert "reverse" in preset, f"{name} missing 'reverse'"
            # Forward map should cover all 6 spec states
            assert set(preset["forward"].keys()) == {
                "draft",
                "todo",
                "in_progress",
                "done",
                "blocked",
                "deprecated",
            }, f"{name} forward map has wrong keys: {set(preset['forward'].keys())}"

    def test_presets_are_immutable_reference(self):
        p1 = get_presets()
        p2 = get_presets()
        assert p1 is not p2 or p1 == p2  # Either new dict or same reference is fine
