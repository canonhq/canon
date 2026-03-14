"""Tests for org-level config deep merge."""

from __future__ import annotations

from canon.sync.mapping import (
    AuthProfile,
    HierarchyConfig,
    StatusMapConfig,
    TemplateConfig,
    TicketMappingConfig,
    TicketSystemConfig,
    deep_merge_configs,
    deep_merge_dicts,
)


class TestDeepMergeDicts:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert deep_merge_dicts(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 100}}
        result = deep_merge_dicts(base, override)
        assert result == {"a": {"x": 1, "y": 99, "z": 100}, "b": 3}

    def test_none_removes_key(self):
        base = {"a": 1, "b": 2, "c": 3}
        override = {"b": None}
        assert deep_merge_dicts(base, override) == {"a": 1, "c": 3}

    def test_list_replaced_not_appended(self):
        base = {"tags": ["a", "b"]}
        override = {"tags": ["c"]}
        assert deep_merge_dicts(base, override) == {"tags": ["c"]}

    def test_empty_override(self):
        base = {"a": 1}
        assert deep_merge_dicts(base, {}) == {"a": 1}

    def test_empty_base(self):
        override = {"a": 1}
        assert deep_merge_dicts({}, override) == {"a": 1}


class TestDeepMergeConfigs:
    def test_repo_overrides_org_system_config(self):
        org = TicketMappingConfig(
            ticket_systems={
                "primary": TicketSystemConfig(
                    system="jira",
                    project="ORG-DEFAULT",
                    status_map=StatusMapConfig(
                        forward={"draft": "Backlog", "todo": "To Do"},
                    ),
                )
            }
        )
        repo = TicketMappingConfig(
            ticket_systems={
                "primary": TicketSystemConfig(
                    system="jira",
                    project="TEAM-PAY",
                )
            }
        )

        merged = deep_merge_configs(org, repo)
        primary = merged.ticket_systems["primary"]
        assert primary.project == "TEAM-PAY"
        # Status map from org should be preserved via deep merge
        assert primary.system == "jira"

    def test_repo_adds_new_system(self):
        org = TicketMappingConfig(
            ticket_systems={"engineering": TicketSystemConfig(system="jira", project="ENG")}
        )
        repo = TicketMappingConfig(
            ticket_systems={"oss": TicketSystemConfig(system="github", project="org/repo")}
        )

        merged = deep_merge_configs(org, repo)
        assert "engineering" in merged.ticket_systems
        assert "oss" in merged.ticket_systems

    def test_repo_inherits_org_auth_profiles(self):
        org = TicketMappingConfig(
            auth_profiles={
                "jira-cloud": AuthProfile(
                    system="jira",
                    auth_method="api_token",
                    env_prefix="JIRA_CLOUD_",
                )
            }
        )
        repo = TicketMappingConfig(
            ticket_systems={
                "primary": TicketSystemConfig(
                    system="jira",
                    project="PAY",
                    auth_profile="jira-cloud",
                )
            },
            auth_profiles={
                "jira-cloud": AuthProfile(
                    system="jira",
                    auth_method="api_token",
                    env_prefix="JIRA_CLOUD_",
                )
            },
        )

        merged = deep_merge_configs(org, repo)
        assert "jira-cloud" in merged.auth_profiles

    def test_repo_routing_replaces_org(self):
        from canon.sync.mapping import RoutingRule

        org = TicketMappingConfig(
            ticket_systems={
                "eng": TicketSystemConfig(system="jira", project="ENG"),
                "ops": TicketSystemConfig(system="jira", project="OPS"),
            },
            routing=[
                RoutingRule(match={"tags": ["ops"]}, target="ops"),
                RoutingRule(match={"default": True}, target="eng"),
            ],
        )
        repo = TicketMappingConfig(
            ticket_systems={
                "eng": TicketSystemConfig(system="jira", project="ENG"),
                "ops": TicketSystemConfig(system="jira", project="OPS"),
            },
            routing=[
                RoutingRule(match={"default": True}, target="ops"),
            ],
        )

        merged = deep_merge_configs(org, repo)
        # Repo routing completely replaces org routing
        assert len(merged.routing) == 1
        assert merged.routing[0].target == "ops"

    def test_org_routing_used_when_repo_has_none(self):
        from canon.sync.mapping import RoutingRule

        org = TicketMappingConfig(
            ticket_systems={
                "eng": TicketSystemConfig(system="jira", project="ENG"),
            },
            routing=[
                RoutingRule(match={"default": True}, target="eng"),
            ],
        )
        repo = TicketMappingConfig(
            ticket_systems={
                "eng": TicketSystemConfig(system="jira", project="ENG"),
            },
        )

        merged = deep_merge_configs(org, repo)
        assert len(merged.routing) == 1
        assert merged.routing[0].target == "eng"

    def test_empty_repo_inherits_everything(self):
        org = TicketMappingConfig(
            ticket_systems={
                "primary": TicketSystemConfig(
                    system="jira",
                    project="ENG",
                    hierarchy=HierarchyConfig(
                        depth_to_type={2: "Epic", 3: "Story"},
                        auto_parent=True,
                    ),
                    templates=TemplateConfig(
                        summary="[§{{section.section_number}}] {{section.title}}"
                    ),
                )
            }
        )
        repo = TicketMappingConfig()

        merged = deep_merge_configs(org, repo)
        primary = merged.ticket_systems["primary"]
        assert primary.hierarchy.depth_to_type == {2: "Epic", 3: "Story"}
        assert primary.hierarchy.auto_parent is True
        assert primary.templates.summary is not None

    def test_deep_merge_status_map(self):
        org = TicketMappingConfig(
            ticket_systems={
                "primary": TicketSystemConfig(
                    system="jira",
                    project="ENG",
                    status_map=StatusMapConfig(
                        forward={
                            "draft": "Backlog",
                            "todo": "To Do",
                            "in_progress": "In Development",
                            "done": "Done",
                            "blocked": "Blocked",
                            "deprecated": "Won't Do",
                        },
                    ),
                )
            }
        )
        repo = TicketMappingConfig(
            ticket_systems={
                "primary": TicketSystemConfig(
                    system="jira",
                    project="PAY",
                    status_map=StatusMapConfig(
                        forward={
                            "draft": "Backlog",
                            "todo": "Open",  # Override org default
                            "in_progress": "In Progress",  # Override
                            "done": "Closed",  # Override
                            "blocked": "On Hold",  # Override
                            "deprecated": "Won't Fix",  # Override
                        },
                    ),
                )
            }
        )

        merged = deep_merge_configs(org, repo)
        primary = merged.ticket_systems["primary"]
        assert primary.project == "PAY"
        # Repo overrides should win
        assert primary.status_map.forward["todo"] == "Open"
        assert primary.status_map.forward["done"] == "Closed"

    def test_unset_repo_fields_do_not_strip_org_defaults(self):
        """Repo config that omits 'project' should not remove org's project."""
        org = TicketMappingConfig(
            ticket_systems={
                "primary": TicketSystemConfig(
                    system="jira",
                    project="ORG-DEFAULT",
                    host_override="jira.org.com",
                )
            }
        )
        # Repo only sets system — project and host_override are unset
        repo = TicketMappingConfig(
            ticket_systems={
                "primary": TicketSystemConfig(
                    system="jira",
                )
            }
        )

        merged = deep_merge_configs(org, repo)
        primary = merged.ticket_systems["primary"]
        # Org defaults should survive since repo didn't explicitly set them
        assert primary.project == "ORG-DEFAULT"
        assert primary.host_override == "jira.org.com"

    def test_explicit_none_in_dict_merge_removes_key(self):
        """An explicit None in the override dict removes the org key.

        This tests the underlying deep_merge_dicts behavior that powers
        the "null-out an org default" feature. At the config level, this
        happens when YAML parsing produces an explicit None for a field
        (e.g. ``host_override: null`` in CANON.yaml).
        """
        org_dict = {"system": "jira", "project": "ORG-DEFAULT", "host_override": "jira.org.com"}
        repo_dict = {"system": "jira", "host_override": None}

        merged = deep_merge_dicts(org_dict, repo_dict)
        assert merged["project"] == "ORG-DEFAULT"
        assert "host_override" not in merged
