"""Tests for ticket mapping config parsing in CANON.yaml."""

from __future__ import annotations

from canon.config import parse_specwright_yaml


class TestTicketSystemsParsing:
    def test_parses_single_ticket_system(self) -> None:
        raw = """
ticket_systems:
  primary:
    system: jira
    project: PAY
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0
        assert result.config.ticket_mapping is not None
        assert "primary" in result.config.ticket_mapping.ticket_systems
        sys = result.config.ticket_mapping.ticket_systems["primary"]
        assert sys.system == "jira"
        assert sys.project == "PAY"

    def test_parses_multiple_ticket_systems(self) -> None:
        raw = """
ticket_systems:
  engineering:
    system: jira
    project: ENG
  oss:
    system: github
    project: org/repo
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0
        mapping = result.config.ticket_mapping
        assert mapping is not None
        assert len(mapping.ticket_systems) == 2

    def test_parses_status_map(self) -> None:
        raw = """
ticket_systems:
  primary:
    system: jira
    project: PAY
    status_map:
      forward:
        draft: "Backlog"
        todo: "Open"
        in_progress: "In Dev"
        done: "Closed"
        blocked: "On Hold"
        deprecated: "Won't Fix"
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0
        sys = result.config.ticket_mapping.ticket_systems["primary"]
        assert sys.status_map.forward["in_progress"] == "In Dev"

    def test_warns_on_incomplete_status_map(self) -> None:
        raw = """
ticket_systems:
  primary:
    system: jira
    project: PAY
    status_map:
      forward:
        todo: "Open"
        done: "Closed"
"""
        result = parse_specwright_yaml(raw)
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert any("missing forward mappings" in w.message for w in warnings)

    def test_parses_hierarchy(self) -> None:
        raw = """
ticket_systems:
  primary:
    system: jira
    project: PAY
    hierarchy:
      depth_to_type:
        2: Epic
        3: Story
        4: Sub-task
      auto_parent: true
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0
        h = result.config.ticket_mapping.ticket_systems["primary"].hierarchy
        assert h.depth_to_type[2] == "Epic"
        assert h.auto_parent is True

    def test_parses_field_map(self) -> None:
        raw = """
ticket_systems:
  primary:
    system: jira
    project: PAY
    field_map:
      standard:
        frontmatter.team: component
        frontmatter.tags: labels
      custom:
        customfield_10001: "literal:managed-by-canon"
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0
        fm = result.config.ticket_mapping.ticket_systems["primary"].field_map
        assert fm.standard["frontmatter.team"] == "component"
        assert fm.custom["customfield_10001"] == "literal:managed-by-canon"

    def test_errors_on_invalid_system(self) -> None:
        raw = """
ticket_systems:
  primary:
    system: servicenow
    project: OPS
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) >= 1
        assert any("servicenow" in e.message or "Invalid" in e.message for e in errors)

    def test_errors_on_non_mapping_ticket_systems(self) -> None:
        raw = """
ticket_systems: true
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert any("mapping" in e.message for e in errors)

    def test_no_ticket_mapping_when_absent(self) -> None:
        raw = """
team: backend
ticket_system: jira
project_key: PAY
"""
        result = parse_specwright_yaml(raw)
        assert result.config.ticket_mapping is None
        assert result.config.ticket_system == "jira"
        assert result.config.project_key == "PAY"


class TestAuthProfilesParsing:
    def test_parses_auth_profiles(self) -> None:
        raw = """
auth_profiles:
  jira-cloud:
    system: jira
    auth_method: api_token
    env_prefix: JIRA_CLOUD_
ticket_systems:
  primary:
    system: jira
    project: PAY
    auth_profile: jira-cloud
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0
        mapping = result.config.ticket_mapping
        assert "jira-cloud" in mapping.auth_profiles
        assert mapping.ticket_systems["primary"].auth_profile == "jira-cloud"

    def test_errors_on_invalid_auth_profile_reference(self) -> None:
        raw = """
ticket_systems:
  primary:
    system: jira
    project: PAY
    auth_profile: nonexistent
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert any(
            "nonexistent" in e.message or "unknown auth profile" in e.message for e in errors
        )

    def test_errors_on_invalid_auth_method(self) -> None:
        raw = """
auth_profiles:
  bad:
    system: jira
    auth_method: oauth2
    env_prefix: BAD_
ticket_systems:
  primary:
    system: jira
    project: PAY
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert any("auth method" in e.message.lower() or "oauth2" in e.message for e in errors)


class TestRoutingParsing:
    def test_parses_routing_rules(self) -> None:
        raw = """
ticket_systems:
  engineering:
    system: jira
    project: ENG
  oss:
    system: github
    project: org/repo
routing:
  - match:
      tags: [open-source]
    target: oss
  - match:
      default: true
    target: engineering
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0
        mapping = result.config.ticket_mapping
        assert len(mapping.routing) == 2
        assert mapping.routing[0].target == "oss"
        assert mapping.routing[1].match["default"] is True

    def test_errors_on_invalid_routing_target(self) -> None:
        raw = """
ticket_systems:
  primary:
    system: jira
    project: PAY
routing:
  - match:
      default: true
    target: nonexistent
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert any(
            "nonexistent" in e.message or "unknown ticket system" in e.message for e in errors
        )

    def test_errors_on_non_list_routing(self) -> None:
        raw = """
ticket_systems:
  primary:
    system: jira
    project: PAY
routing: true
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert any("list" in e.message for e in errors)


class TestEnterpriseConfig:
    def test_full_enterprise_config(self) -> None:
        raw = """
team: platform
ticket_system: jira
project_key: PLAT
auth_profiles:
  jira-cloud:
    system: jira
    auth_method: api_token
    env_prefix: JIRA_CLOUD_
  jira-dc:
    system: jira
    auth_method: personal_access_token
    env_prefix: JIRA_DC_
ticket_systems:
  engineering:
    system: jira
    project: ENG
    auth_profile: jira-cloud
    status_map:
      forward:
        draft: "Backlog"
        todo: "Open"
        in_progress: "In Development"
        done: "Closed"
        blocked: "On Hold"
        deprecated: "Won't Fix"
    hierarchy:
      depth_to_type:
        2: Epic
        3: Story
      auto_parent: true
    field_map:
      standard:
        frontmatter.team: component
  operations:
    system: jira
    project: OPS
    auth_profile: jira-dc
    host_override: jira-dc.example.com
  oss:
    system: github
    project: org/public-repo
routing:
  - match:
      tags: [infrastructure, ops]
    target: operations
  - match:
      tags: [open-source]
    target: oss
  - match:
      default: true
    target: engineering
specs:
  auto_tickets: true
  require_review: true
"""
        result = parse_specwright_yaml(raw)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert len(errors) == 0

        # Legacy fields still work
        assert result.config.ticket_system == "jira"
        assert result.config.project_key == "PLAT"

        # New mapping is populated
        mapping = result.config.ticket_mapping
        assert mapping is not None
        assert len(mapping.auth_profiles) == 2
        assert len(mapping.ticket_systems) == 3
        assert len(mapping.routing) == 3

        eng = mapping.ticket_systems["engineering"]
        assert eng.status_map.forward["in_progress"] == "In Development"
        assert eng.hierarchy.depth_to_type[2] == "Epic"
        assert eng.hierarchy.auto_parent is True
        assert eng.field_map.standard["frontmatter.team"] == "component"

        ops = mapping.ticket_systems["operations"]
        assert ops.host_override == "jira-dc.example.com"
        assert ops.auth_profile == "jira-dc"
