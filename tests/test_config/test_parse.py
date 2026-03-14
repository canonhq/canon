"""Port of src/config/__tests__/parse.test.ts — config parser tests."""

from __future__ import annotations

from canon.config import DEFAULT_CONFIG, parse_canon_yaml


class TestParseCanonYaml:
    def test_parses_valid_full_config(self):
        raw = """
team: platform
ticket_system: jira
project_key: PLAT
slack_channel: "#platform-eng"
specs:
  auto_tickets: false
  require_review: true
agents:
  doc_updates: true
  pr_analysis: false
  stale_detection: "7d"
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        assert result.config.team == "platform"
        assert result.config.ticket_system == "jira"
        assert result.config.project_key == "PLAT"
        assert result.config.slack_channel == "#platform-eng"
        assert result.config.specs.auto_tickets is False
        assert result.config.specs.require_review is True
        assert result.config.agents.doc_updates is True
        assert result.config.agents.pr_analysis is False
        assert result.config.agents.stale_detection == "7d"

    def test_fills_defaults_for_missing_optional_fields(self):
        raw = """
team: backend
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        assert result.config.team == "backend"
        assert result.config.ticket_system is None
        assert result.config.project_key is None
        assert result.config.slack_channel is None
        assert result.config.specs == DEFAULT_CONFIG.specs
        assert result.config.agents == DEFAULT_CONFIG.agents

    def test_returns_defaults_with_warning_for_empty_file(self):
        result = parse_canon_yaml("")
        assert result.config == DEFAULT_CONFIG
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].severity == "warning"
        assert "empty" in result.diagnostics[0].message

    def test_returns_defaults_with_warning_for_whitespace_only(self):
        result = parse_canon_yaml("   \n  \n  ")
        assert result.config == DEFAULT_CONFIG
        assert result.diagnostics[0].severity == "warning"

    def test_returns_error_for_malformed_yaml(self):
        result = parse_canon_yaml("team: [unclosed")
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].severity == "error"
        assert "Invalid YAML" in result.diagnostics[0].message
        assert result.config == DEFAULT_CONFIG

    def test_returns_error_for_non_mapping_yaml(self):
        result = parse_canon_yaml("- item1\n- item2")
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].severity == "error"
        assert "mapping" in result.diagnostics[0].message

    def test_warns_on_unknown_top_level_keys(self):
        raw = """
team: frontend
unknown_key: value
another_bad: true
"""
        result = parse_canon_yaml(raw)
        assert result.config.team == "frontend"
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert len(warnings) == 2
        assert "unknown_key" in warnings[0].message
        assert "another_bad" in warnings[1].message

    def test_errors_on_invalid_ticket_system_value(self):
        raw = """
ticket_system: asana
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].severity == "error"
        assert "asana" in result.diagnostics[0].message
        assert result.config.ticket_system is None

    def test_accepts_all_valid_ticket_system_values(self):
        for system in ("jira", "linear", "github"):
            result = parse_canon_yaml(f"ticket_system: {system}")
            assert len(result.diagnostics) == 0
            assert result.config.ticket_system == system

    def test_errors_on_invalid_stale_detection_duration(self):
        raw = """
agents:
  stale_detection: "two weeks"
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].severity == "error"
        assert "stale_detection" in result.diagnostics[0].message
        assert result.config.agents.stale_detection == "30d"

    def test_accepts_stale_detection_false(self):
        raw = """
agents:
  stale_detection: false
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        assert result.config.agents.stale_detection is False

    def test_errors_on_non_boolean_specs_fields(self):
        raw = """
specs:
  auto_tickets: "yes"
  require_review: 1
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 2
        assert result.config.specs == DEFAULT_CONFIG.specs

    def test_warns_on_unknown_specs_keys(self):
        raw = """
specs:
  auto_tickets: true
  unknown_spec_key: true
"""
        result = parse_canon_yaml(raw)
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert len(warnings) == 1
        assert "unknown_spec_key" in warnings[0].message

    def test_warns_on_unknown_agents_keys(self):
        raw = """
agents:
  pr_analysis: true
  magic_feature: true
"""
        result = parse_canon_yaml(raw)
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert len(warnings) == 1
        assert "magic_feature" in warnings[0].message

    def test_errors_when_specs_is_not_mapping(self):
        raw = """
specs: true
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].severity == "error"
        assert "specs" in result.diagnostics[0].message
        assert "mapping" in result.diagnostics[0].message

    def test_errors_when_agents_is_not_mapping(self):
        raw = """
agents: "all"
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].severity == "error"
        assert "agents" in result.diagnostics[0].message
        assert "mapping" in result.diagnostics[0].message

    def test_errors_on_non_string_team_field(self):
        raw = """
team: 42
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].severity == "error"
        assert "team" in result.diagnostics[0].message
        assert "string" in result.diagnostics[0].message
        assert result.config.team is None

    def test_parses_doc_paths(self):
        raw = """
specs:
  doc_paths:
    - "docs/specs/*.md"
    - "docs/rfcs/**/*.md"
    - "design/*.md"
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        assert result.config.specs.doc_paths == [
            "docs/specs/*.md",
            "docs/rfcs/**/*.md",
            "design/*.md",
        ]

    def test_doc_paths_defaults_to_specs_glob(self):
        raw = """
specs:
  auto_tickets: true
"""
        result = parse_canon_yaml(raw)
        assert result.config.specs.doc_paths == ["docs/specs/*.md"]

    def test_errors_on_non_list_doc_paths(self):
        raw = """
specs:
  doc_paths: "docs/specs/*.md"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "doc_paths" in errors[0].message
        assert "list" in errors[0].message
        assert result.config.specs.doc_paths == ["docs/specs/*.md"]

    def test_errors_on_empty_doc_paths(self):
        raw = """
specs:
  doc_paths: []
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "empty" in errors[0].message
        assert result.config.specs.doc_paths == ["docs/specs/*.md"]

    def test_errors_on_non_string_items_in_doc_paths(self):
        raw = """
specs:
  doc_paths:
    - 42
    - true
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "doc_paths" in errors[0].message
        assert result.config.specs.doc_paths == ["docs/specs/*.md"]


class TestRealizationCheckConfig:
    def test_defaults_to_true(self):
        raw = """
team: test
"""
        result = parse_canon_yaml(raw)
        assert result.config.agents.realization_check is True

    def test_can_be_set_false(self):
        raw = """
agents:
  realization_check: false
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        assert result.config.agents.realization_check is False

    def test_can_be_set_true(self):
        raw = """
agents:
  realization_check: true
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        assert result.config.agents.realization_check is True

    def test_errors_on_non_boolean(self):
        raw = """
agents:
  realization_check: "yes"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "realization_check" in errors[0].message
        assert "boolean" in errors[0].message
        # Should fall back to default
        assert result.config.agents.realization_check is True

    def test_full_agents_config_with_realization_check(self):
        raw = """
agents:
  doc_updates: true
  pr_analysis: false
  realization_check: false
  stale_detection: "14d"
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        assert result.config.agents.doc_updates is True
        assert result.config.agents.pr_analysis is False
        assert result.config.agents.realization_check is False
        assert result.config.agents.stale_detection == "14d"
