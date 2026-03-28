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


class TestIdeConfig:
    def test_parses_full_ide_config(self):
        raw = """
ide:
  auto_context:
    enabled: true
    on_session_start: true
    on_prompt: false
    max_specs: 3
  auto_verify:
    enabled: true
    on_stop: true
    on_commit: true
    confidence: "high"
  ai_exposure:
    default: "metadata"
    restricted_tags: ["security", "legal"]
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        ide = result.config.ide
        assert ide.auto_context.enabled is True
        assert ide.auto_context.on_prompt is False
        assert ide.auto_context.max_specs == 3
        assert ide.auto_verify.on_commit is True
        assert ide.auto_verify.confidence == "high"
        assert ide.ai_exposure.default == "metadata"
        assert ide.ai_exposure.restricted_tags == ["security", "legal"]

    def test_missing_ide_section_returns_defaults(self):
        raw = """
team: backend
"""
        result = parse_canon_yaml(raw)
        ide = result.config.ide
        assert ide.auto_context.enabled is True
        assert ide.auto_context.on_session_start is True
        assert ide.auto_context.on_prompt is True
        assert ide.auto_context.max_specs == 5
        assert ide.auto_verify.enabled is True
        assert ide.auto_verify.on_stop is True
        assert ide.auto_verify.on_commit is False
        assert ide.auto_verify.confidence == "medium"
        assert ide.ai_exposure.default == "full"
        assert ide.ai_exposure.restricted_tags == []

    def test_partial_ide_section_fills_defaults(self):
        raw = """
ide:
  auto_context:
    enabled: false
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        ide = result.config.ide
        assert ide.auto_context.enabled is False
        assert ide.auto_context.on_session_start is True
        assert ide.auto_verify.enabled is True
        assert ide.ai_exposure.default == "full"

    def test_warns_on_unknown_ide_keys(self):
        raw = """
ide:
  auto_context:
    enabled: true
  unknown_ide_key: true
"""
        result = parse_canon_yaml(raw)
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert len(warnings) == 1
        assert "unknown_ide_key" in warnings[0].message

    def test_warns_on_unknown_auto_context_keys(self):
        raw = """
ide:
  auto_context:
    enabled: true
    magic_field: true
"""
        result = parse_canon_yaml(raw)
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert len(warnings) == 1
        assert "magic_field" in warnings[0].message

    def test_errors_on_invalid_confidence_value(self):
        raw = """
ide:
  auto_verify:
    confidence: "low"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "confidence" in errors[0].message
        assert result.config.ide.auto_verify.confidence == "medium"

    def test_accepts_valid_confidence_values(self):
        for level in ("medium", "high"):
            raw = f"""
ide:
  auto_verify:
    confidence: "{level}"
"""
            result = parse_canon_yaml(raw)
            assert len(result.diagnostics) == 0
            assert result.config.ide.auto_verify.confidence == level

    def test_errors_on_invalid_ai_exposure_default(self):
        raw = """
ide:
  ai_exposure:
    default: "partial"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "ai_exposure.default" in errors[0].message
        assert result.config.ide.ai_exposure.default == "full"

    def test_accepts_valid_ai_exposure_defaults(self):
        for level in ("full", "metadata", "none"):
            raw = f"""
ide:
  ai_exposure:
    default: "{level}"
"""
            result = parse_canon_yaml(raw)
            assert len(result.diagnostics) == 0
            assert result.config.ide.ai_exposure.default == level

    def test_errors_on_non_list_restricted_tags(self):
        raw = """
ide:
  ai_exposure:
    restricted_tags: "security"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "restricted_tags" in errors[0].message
        assert "list" in errors[0].message
        assert result.config.ide.ai_exposure.restricted_tags == []

    def test_errors_on_non_string_items_in_restricted_tags(self):
        raw = """
ide:
  ai_exposure:
    restricted_tags:
      - 42
      - true
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "restricted_tags" in errors[0].message

    def test_errors_when_ide_is_not_mapping(self):
        raw = """
ide: true
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "ide" in errors[0].message
        assert "mapping" in errors[0].message
        # Falls back to defaults
        assert result.config.ide == DEFAULT_CONFIG.ide

    def test_errors_on_non_boolean_auto_context_fields(self):
        raw = """
ide:
  auto_context:
    enabled: "yes"
    on_prompt: 1
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 2
        assert result.config.ide.auto_context.enabled is True
        assert result.config.ide.auto_context.on_prompt is True

    def test_errors_on_non_integer_max_specs(self):
        raw = """
ide:
  auto_context:
    max_specs: "ten"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "max_specs" in errors[0].message
        assert result.config.ide.auto_context.max_specs == 5

    def test_existing_config_unaffected_by_ide_section(self):
        raw = """
team: platform
agents:
  pr_analysis: false
ide:
  auto_context:
    enabled: false
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        assert result.config.team == "platform"
        assert result.config.agents.pr_analysis is False
        assert result.config.ide.auto_context.enabled is False


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


class TestSlackConfig:
    def test_parses_full_slack_config(self):
        raw = """
slack:
  default_channel: "#eng-specs"
  sre_channel: "#sre-alerts"
  notifications:
    spec_status_change: true
    spec_created: false
    coverage_threshold: 90
  quiet_hours:
    start: "22:00"
    end: "08:00"
  digest:
    channel: "#weekly"
    schedule: "friday 10:00"
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        slack = result.config.slack
        assert slack.default_channel == "#eng-specs"
        assert slack.sre_channel == "#sre-alerts"
        assert slack.notifications.spec_status_change is True
        assert slack.notifications.spec_created is False
        assert slack.notifications.coverage_threshold == 90
        assert slack.quiet_hours is not None
        assert slack.quiet_hours.start == "22:00"
        assert slack.digest.channel == "#weekly"
        assert slack.digest.schedule == "friday 10:00"

    def test_missing_slack_section_returns_defaults(self):
        raw = """
team: test
"""
        result = parse_canon_yaml(raw)
        slack = result.config.slack
        assert slack.default_channel == "#canon-specs"
        assert slack.sre_channel == ""
        assert slack.notifications.spec_status_change is True
        assert slack.quiet_hours is None

    def test_unknown_slack_key_warns(self):
        raw = """
slack:
  default_channel: "#specs"
  bogus_key: true
"""
        result = parse_canon_yaml(raw)
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert any("bogus_key" in w.message for w in warnings)

    def test_non_mapping_slack_errors(self):
        raw = """
slack: "not a mapping"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert any("slack" in e.message and "mapping" in e.message for e in errors)

    def test_non_mapping_notifications_errors(self):
        raw = """
slack:
  notifications: "not a mapping"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert any("notifications" in e.message for e in errors)

    def test_non_mapping_digest_errors(self):
        raw = """
slack:
  digest: "not a mapping"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert any("digest" in e.message for e in errors)

    def test_unknown_notification_key_warns(self):
        raw = """
slack:
  notifications:
    bad_key: true
"""
        result = parse_canon_yaml(raw)
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert any("bad_key" in w.message for w in warnings)

    def test_notification_dict_form_with_channel(self):
        raw = """
slack:
  notifications:
    coverage_regression:
      enabled: true
      channel: "#eng-alerts"
    spec_status_change:
      enabled: false
      channel: "#specs"
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        notif = result.config.slack.notifications
        assert notif.coverage_regression is True
        assert notif.spec_status_change is False
        assert notif.channel_overrides == {
            "coverage_regression": "#eng-alerts",
            "spec_status_change": "#specs",
        }

    def test_notification_dict_form_unknown_subkey_warns(self):
        raw = """
slack:
  notifications:
    coverage_regression:
      enabled: true
      channel: "#eng-alerts"
      bad_subkey: true
"""
        result = parse_canon_yaml(raw)
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert any("bad_subkey" in w.message for w in warnings)

    def test_unknown_digest_key_warns(self):
        raw = """
slack:
  digest:
    bad_key: true
"""
        result = parse_canon_yaml(raw)
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert any("bad_key" in w.message for w in warnings)


class TestTeamDigestsConfig:
    def test_parses_team_digests_correctly(self):
        raw = """
slack:
  digest:
    channel: "#general-specs"
    schedule: "monday 09:00"
    team_digests:
      platform:
        channel: "#platform-specs"
        schedule: "monday 09:00"
      backend:
        channel: "#backend-specs"
        schedule: "tuesday 09:00"
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        digest = result.config.slack.digest
        assert digest.channel == "#general-specs"
        assert digest.schedule == "monday 09:00"
        assert len(digest.team_digests) == 2
        assert digest.team_digests["platform"].channel == "#platform-specs"
        assert digest.team_digests["platform"].schedule == "monday 09:00"
        assert digest.team_digests["backend"].channel == "#backend-specs"
        assert digest.team_digests["backend"].schedule == "tuesday 09:00"

    def test_team_digest_missing_channel_produces_error(self):
        raw = """
slack:
  digest:
    channel: "#general-specs"
    team_digests:
      platform:
        schedule: "monday 09:00"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "team_digests.platform.channel" in errors[0].message
        assert "required" in errors[0].message
        # The invalid team digest entry should be removed
        assert len(result.config.slack.digest.team_digests) == 0

    def test_non_mapping_team_digests_produces_error(self):
        raw = """
slack:
  digest:
    channel: "#general-specs"
    team_digests: "not a mapping"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "team_digests" in errors[0].message
        assert "mapping" in errors[0].message

    def test_team_digests_key_does_not_produce_unknown_key_warning(self):
        raw = """
slack:
  digest:
    channel: "#general-specs"
    team_digests:
      platform:
        channel: "#platform-specs"
"""
        result = parse_canon_yaml(raw)
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert len(warnings) == 0

    def test_team_digests_defaults_to_empty_dict(self):
        raw = """
slack:
  digest:
    channel: "#general-specs"
    schedule: "monday 09:00"
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        assert result.config.slack.digest.team_digests == {}

    def test_team_digest_uses_default_schedule(self):
        raw = """
slack:
  digest:
    channel: "#general-specs"
    team_digests:
      platform:
        channel: "#platform-specs"
"""
        result = parse_canon_yaml(raw)
        assert len(result.diagnostics) == 0
        assert result.config.slack.digest.team_digests["platform"].schedule == "monday 09:00"

    def test_non_mapping_team_entry_produces_error(self):
        raw = """
slack:
  digest:
    channel: "#general-specs"
    team_digests:
      platform: "not a mapping"
"""
        result = parse_canon_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert "team_digests.platform" in errors[0].message
        assert "mapping" in errors[0].message
