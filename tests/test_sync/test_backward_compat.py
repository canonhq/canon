"""Tests for backward compatibility layer in ticket mapping."""

from __future__ import annotations

from canon.sync.mapping import (
    TicketMappingConfig,
    TicketSystemConfig,
    synthesize_mapping_config,
)


class TestSynthesizeMappingConfig:
    def test_legacy_only_creates_primary_system(self) -> None:
        config, deprecated = synthesize_mapping_config(
            ticket_system="jira",
            project_key="PAY",
            ticket_mapping=None,
        )
        assert not deprecated
        assert not config.is_empty()
        sys = config.single_system()
        assert sys is not None
        assert sys.system == "jira"
        assert sys.project == "PAY"
        # Uses default status maps (empty = fall back to defaults)
        assert sys.status_map.forward == {}
        assert sys.hierarchy.default_type == "Task"

    def test_new_style_used_when_present(self) -> None:
        mapping = TicketMappingConfig(
            ticket_systems={
                "eng": TicketSystemConfig(system="jira", project="ENG"),
            }
        )
        config, deprecated = synthesize_mapping_config(
            ticket_system=None,
            project_key=None,
            ticket_mapping=mapping,
        )
        assert not deprecated
        assert config is mapping

    def test_new_style_takes_precedence_with_deprecation(self) -> None:
        mapping = TicketMappingConfig(
            ticket_systems={
                "eng": TicketSystemConfig(system="jira", project="ENG"),
            }
        )
        config, deprecated = synthesize_mapping_config(
            ticket_system="jira",
            project_key="OLD",
            ticket_mapping=mapping,
        )
        assert deprecated
        assert config is mapping
        assert config.ticket_systems["eng"].project == "ENG"

    def test_neither_returns_empty(self) -> None:
        config, deprecated = synthesize_mapping_config(
            ticket_system=None,
            project_key=None,
            ticket_mapping=None,
        )
        assert not deprecated
        assert config.is_empty()

    def test_legacy_ticket_system_without_project_key(self) -> None:
        """ticket_system alone is enough — project_key may come from frontmatter."""
        config, deprecated = synthesize_mapping_config(
            ticket_system="jira",
            project_key=None,
            ticket_mapping=None,
        )
        assert not deprecated
        assert not config.is_empty()
        sys = config.single_system()
        assert sys is not None
        assert sys.system == "jira"
        assert sys.project == ""  # project comes from frontmatter at sync time

    def test_empty_new_style_falls_back_to_legacy(self) -> None:
        empty_mapping = TicketMappingConfig()
        config, deprecated = synthesize_mapping_config(
            ticket_system="linear",
            project_key="TEAM",
            ticket_mapping=empty_mapping,
        )
        assert not deprecated
        sys = config.single_system()
        assert sys is not None
        assert sys.system == "linear"
        assert sys.project == "TEAM"

    def test_legacy_github(self) -> None:
        config, deprecated = synthesize_mapping_config(
            ticket_system="github",
            project_key="org/repo",
            ticket_mapping=None,
        )
        assert not deprecated
        sys = config.single_system()
        assert sys.system == "github"
        assert sys.project == "org/repo"
