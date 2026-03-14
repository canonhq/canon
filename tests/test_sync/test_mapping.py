"""Tests for ticket mapping configuration models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from canon.sync.mapping import (
    AuthProfile,
    FieldMapConfig,
    HierarchyConfig,
    RoutingRule,
    StatusMapConfig,
    TicketMappingConfig,
    TicketSystemConfig,
)

# ─── StatusMapConfig ─────────────────────────────────────────────


class TestStatusMapConfig:
    def test_empty_is_valid(self) -> None:
        config = StatusMapConfig()
        assert config.forward == {}
        assert config.reverse == {}
        assert config.fallback == "draft"

    def test_full_forward_map(self) -> None:
        config = StatusMapConfig(
            forward={
                "draft": "Backlog",
                "todo": "Open",
                "in_progress": "In Development",
                "done": "Closed",
                "blocked": "On Hold",
                "deprecated": "Won't Fix",
            }
        )
        assert config.forward["in_progress"] == "In Development"
        assert config.missing_forward_states() == []

    def test_partial_forward_reports_missing(self) -> None:
        config = StatusMapConfig(forward={"todo": "Open", "done": "Closed"})
        missing = config.missing_forward_states()
        assert "draft" in missing
        assert "in_progress" in missing
        assert "blocked" in missing
        assert "deprecated" in missing

    def test_invalid_forward_key_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid spec state"):
            StatusMapConfig(forward={"invalid_state": "Open"})

    def test_invalid_fallback_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid fallback"):
            StatusMapConfig(fallback="nonexistent")

    def test_reverse_map(self) -> None:
        config = StatusMapConfig(
            reverse={"new": "todo", "indeterminate": "in_progress", "done": "done"}
        )
        assert config.reverse["new"] == "todo"

    def test_custom_fallback(self) -> None:
        config = StatusMapConfig(fallback="todo")
        assert config.fallback == "todo"


# ─── FieldMapConfig ──────────────────────────────────────────────


class TestFieldMapConfig:
    def test_empty_is_valid(self) -> None:
        config = FieldMapConfig()
        assert config.standard == {}
        assert config.custom == {}

    def test_valid_standard_sources(self) -> None:
        config = FieldMapConfig(
            standard={
                "frontmatter.team": "component",
                "frontmatter.owner": "assignee",
                "frontmatter.tags": "labels",
            }
        )
        assert config.standard["frontmatter.team"] == "component"

    def test_invalid_standard_source_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid field map source"):
            FieldMapConfig(standard={"frontmatter.nonexistent": "field"})

    def test_literal_custom_field(self) -> None:
        config = FieldMapConfig(custom={"customfield_10001": "literal:canon-managed"})
        assert config.custom["customfield_10001"] == "literal:canon-managed"

    def test_indexed_custom_field(self) -> None:
        config = FieldMapConfig(custom={"customfield_10001": "frontmatter.tags[0]"})
        assert config.custom["customfield_10001"] == "frontmatter.tags[0]"

    def test_invalid_custom_source_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid custom field source"):
            FieldMapConfig(custom={"customfield_10001": "nonexistent.field"})


# ─── HierarchyConfig ────────────────────────────────────────────


class TestHierarchyConfig:
    def test_defaults(self) -> None:
        config = HierarchyConfig()
        assert config.depth_to_type == {}
        assert config.auto_parent is False
        assert config.default_type == "Task"

    def test_depth_mapping(self) -> None:
        config = HierarchyConfig(
            depth_to_type={2: "Epic", 3: "Story", 4: "Sub-task"},
            auto_parent=True,
        )
        assert config.depth_to_type[2] == "Epic"
        assert config.auto_parent is True

    def test_empty_type_raises(self) -> None:
        with pytest.raises(ValidationError, match="non-empty string"):
            HierarchyConfig(depth_to_type={2: ""})

    def test_empty_default_type_raises(self) -> None:
        with pytest.raises(ValidationError, match="non-empty string"):
            HierarchyConfig(default_type="")


# ─── AuthProfile ─────────────────────────────────────────────────


class TestAuthProfile:
    def test_valid_profile(self) -> None:
        profile = AuthProfile(system="jira", auth_method="api_token", env_prefix="JIRA_CLOUD_")
        assert profile.system == "jira"

    def test_invalid_system_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid auth profile system"):
            AuthProfile(system="azure", auth_method="api_token", env_prefix="AZ_")

    def test_invalid_auth_method_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid auth method"):
            AuthProfile(system="jira", auth_method="oauth2", env_prefix="JIRA_")

    def test_empty_env_prefix_raises(self) -> None:
        with pytest.raises(ValidationError, match="non-empty string"):
            AuthProfile(system="jira", auth_method="api_token", env_prefix="")

    def test_all_auth_methods(self) -> None:
        for method in ("api_token", "personal_access_token", "api_key", "app_installation"):
            profile = AuthProfile(
                system="jira", auth_method=method, env_prefix=f"TEST_{method.upper()}_"
            )
            assert profile.auth_method == method


# ─── TicketSystemConfig ──────────────────────────────────────────


class TestTicketSystemConfig:
    def test_minimal(self) -> None:
        config = TicketSystemConfig(system="jira", project="PAY")
        assert config.system == "jira"
        assert config.project == "PAY"
        assert config.status_map.forward == {}
        assert config.hierarchy.default_type == "Task"

    def test_full_config(self) -> None:
        config = TicketSystemConfig(
            system="jira",
            project="ENG",
            auth_profile="jira-cloud",
            host_override="jira.example.com",
            status_map=StatusMapConfig(
                forward={"todo": "Open", "done": "Closed"},
                reverse={"new": "todo"},
            ),
            field_map=FieldMapConfig(standard={"frontmatter.team": "component"}),
            hierarchy=HierarchyConfig(depth_to_type={2: "Epic", 3: "Story"}, auto_parent=True),
        )
        assert config.host_override == "jira.example.com"
        assert config.hierarchy.auto_parent is True

    def test_invalid_system_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid ticket system"):
            TicketSystemConfig(system="servicenow", project="OPS")


# ─── RoutingRule ─────────────────────────────────────────────────


class TestRoutingRule:
    def test_tag_match(self) -> None:
        rule = RoutingRule(match={"tags": ["infrastructure"]}, target="ops")
        assert rule.match["tags"] == ["infrastructure"]

    def test_default_match(self) -> None:
        rule = RoutingRule(match={"default": True}, target="primary")
        assert rule.target == "primary"

    def test_invalid_match_key_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid routing match key"):
            RoutingRule(match={"priority": "high"}, target="primary")

    def test_empty_match_raises(self) -> None:
        with pytest.raises(ValidationError, match="at least one"):
            RoutingRule(match={}, target="primary")


# ─── TicketMappingConfig ─────────────────────────────────────────


class TestTicketMappingConfig:
    def test_empty_is_valid(self) -> None:
        config = TicketMappingConfig()
        assert config.is_empty()
        assert config.single_system() is None

    def test_single_system(self) -> None:
        config = TicketMappingConfig(
            ticket_systems={"primary": TicketSystemConfig(system="jira", project="PAY")}
        )
        assert not config.is_empty()
        assert config.single_system() is not None
        assert config.single_system().system == "jira"

    def test_multi_system(self) -> None:
        config = TicketMappingConfig(
            ticket_systems={
                "eng": TicketSystemConfig(system="jira", project="ENG"),
                "oss": TicketSystemConfig(system="github", project="org/repo"),
            },
            routing=[
                RoutingRule(match={"tags": ["open-source"]}, target="oss"),
                RoutingRule(match={"default": True}, target="eng"),
            ],
        )
        assert config.single_system() is None
        assert len(config.routing) == 2

    def test_auth_profile_reference(self) -> None:
        config = TicketMappingConfig(
            auth_profiles={
                "jira-cloud": AuthProfile(
                    system="jira", auth_method="api_token", env_prefix="JIRA_CLOUD_"
                )
            },
            ticket_systems={
                "primary": TicketSystemConfig(
                    system="jira", project="PAY", auth_profile="jira-cloud"
                )
            },
        )
        assert config.ticket_systems["primary"].auth_profile == "jira-cloud"

    def test_invalid_auth_profile_ref_raises(self) -> None:
        with pytest.raises(ValidationError, match="unknown auth profile"):
            TicketMappingConfig(
                ticket_systems={
                    "primary": TicketSystemConfig(
                        system="jira", project="PAY", auth_profile="nonexistent"
                    )
                }
            )

    def test_invalid_routing_target_raises(self) -> None:
        with pytest.raises(ValidationError, match="unknown ticket system"):
            TicketMappingConfig(
                ticket_systems={"primary": TicketSystemConfig(system="jira", project="PAY")},
                routing=[RoutingRule(match={"default": True}, target="nonexistent")],
            )

    def test_enterprise_config(self) -> None:
        """Full enterprise config: multiple systems, auth profiles, routing."""
        config = TicketMappingConfig(
            auth_profiles={
                "jira-cloud": AuthProfile(
                    system="jira", auth_method="api_token", env_prefix="JIRA_CLOUD_"
                ),
                "jira-dc": AuthProfile(
                    system="jira",
                    auth_method="personal_access_token",
                    env_prefix="JIRA_DC_",
                ),
            },
            ticket_systems={
                "engineering": TicketSystemConfig(
                    system="jira",
                    project="ENG",
                    auth_profile="jira-cloud",
                    status_map=StatusMapConfig(
                        forward={
                            "draft": "Backlog",
                            "todo": "Open",
                            "in_progress": "In Development",
                            "done": "Closed",
                            "blocked": "On Hold",
                            "deprecated": "Won't Fix",
                        },
                        reverse={
                            "new": "todo",
                            "indeterminate": "in_progress",
                            "done": "done",
                            "On Hold": "blocked",
                        },
                    ),
                    hierarchy=HierarchyConfig(
                        depth_to_type={2: "Epic", 3: "Story", 4: "Sub-task"},
                        auto_parent=True,
                    ),
                    field_map=FieldMapConfig(
                        standard={"frontmatter.team": "component"},
                        custom={"customfield_10001": "frontmatter.tags[0]"},
                    ),
                ),
                "operations": TicketSystemConfig(
                    system="jira",
                    project="OPS",
                    auth_profile="jira-dc",
                    host_override="jira-dc.example.com",
                ),
                "oss": TicketSystemConfig(system="github", project="org/public-repo"),
            },
            routing=[
                RoutingRule(
                    match={"tags": ["infrastructure", "ops"]},
                    target="operations",
                ),
                RoutingRule(match={"tags": ["open-source"]}, target="oss"),
                RoutingRule(match={"default": True}, target="engineering"),
            ],
        )
        assert len(config.ticket_systems) == 3
        assert len(config.routing) == 3
        eng = config.ticket_systems["engineering"]
        assert eng.hierarchy.depth_to_type[2] == "Epic"
        assert eng.status_map.forward["in_progress"] == "In Development"
        assert eng.field_map.custom["customfield_10001"] == "frontmatter.tags[0]"
