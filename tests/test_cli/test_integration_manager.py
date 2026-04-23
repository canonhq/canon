"""Tests for IntegrationManager — credential source abstraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from canon.cli.integration_manager import IntegrationManager


class TestListAll:
    def test_all_unconfigured_returns_three_providers(self, tmp_path: Path):
        manager = IntegrationManager(root=tmp_path)
        results = manager.list_all(org=None)
        assert len(results) == 3
        providers = [i.provider for i in results]
        assert providers == ["jira", "linear", "github"]
        assert all(i.status == "not_configured" for i in results)

    def test_detects_jira_from_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("JIRA_HOST", "acme.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@acme.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "secret")
        manager = IntegrationManager(root=tmp_path)
        results = manager.list_all(org=None)
        jira = next(i for i in results if i.provider == "jira")
        assert jira.status == "configured"
        assert jira.source == "env_var"
        assert "acme.atlassian.net" in jira.details

    def test_detects_linear_from_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_key")
        manager = IntegrationManager(root=tmp_path)
        results = manager.list_all(org=None)
        linear = next(i for i in results if i.provider == "linear")
        assert linear.status == "configured"
        assert linear.source == "env_var"

    def test_detects_github_from_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        monkeypatch.setenv("GITHUB_OWNER", "acme")
        monkeypatch.setenv("GITHUB_REPO", "repo")
        manager = IntegrationManager(root=tmp_path)
        results = manager.list_all(org=None)
        gh = next(i for i in results if i.provider == "github")
        assert gh.status == "configured"
        assert gh.source == "env_var"
        assert "acme/repo" in gh.details

    def test_canon_yaml_overrides_env_var(self, tmp_path: Path, monkeypatch):
        """CANON.yaml auth_profiles take priority over env vars."""
        monkeypatch.setenv("JIRA_HOST", "env-host.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "env@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "env-secret")

        yaml_content = """\
team: test
ticket_systems:
  jira_prod:
    system: jira
    project: TEST
    auth_profile: jira_prod
auth_profiles:
  jira_prod:
    system: jira
    auth_method: api_token
    env_prefix: JIRA_PROD_
"""
        (tmp_path / "CANON.yaml").write_text(yaml_content)

        manager = IntegrationManager(root=tmp_path)
        results = manager.list_all(org=None)
        jira = next(i for i in results if i.provider == "jira")
        assert jira.source == "canon_yaml"
        assert "TEST" in jira.details
        assert "api_token" in jira.details

    def test_ordered_by_provider(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "key")
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        manager = IntegrationManager(root=tmp_path)
        results = manager.list_all(org=None)
        providers = [i.provider for i in results]
        assert providers == ["jira", "linear", "github"]


class TestFromCanonYaml:
    def test_empty_yaml_returns_nothing(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: test\n")
        manager = IntegrationManager(root=tmp_path)
        results = manager._from_canon_yaml()
        assert results == []

    def test_no_yaml_returns_empty(self, tmp_path: Path):
        manager = IntegrationManager(root=tmp_path)
        results = manager._from_canon_yaml()
        assert results == []


class TestFromEnvVars:
    def test_jira_needs_all_three_vars(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("JIRA_HOST", "host")
        monkeypatch.setenv("JIRA_EMAIL", "email")
        # Missing JIRA_API_TOKEN
        manager = IntegrationManager(root=tmp_path)
        results = manager._from_env_vars()
        assert not any(i.provider == "jira" for i in results)

    def test_github_token_alone_works(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        manager = IntegrationManager(root=tmp_path)
        results = manager._from_env_vars()
        gh = [i for i in results if i.provider == "github"]
        assert len(gh) == 1
        assert gh[0].status == "configured"


class TestAddLocalIntegration:
    def test_creates_yaml_if_missing(self, tmp_path: Path):
        manager = IntegrationManager(root=tmp_path)
        manager.add_local_integration("jira", project_key="TEST")
        config = (tmp_path / "CANON.yaml").read_text()
        assert "ticket_system: jira" in config
        assert "project_key: TEST" in config

    def test_updates_existing_yaml(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: myteam\nticket_system: github\n")
        manager = IntegrationManager(root=tmp_path)
        manager.add_local_integration("linear", project_key="LIN")
        config = (tmp_path / "CANON.yaml").read_text()
        assert "ticket_system: linear" in config
        assert "team: myteam" in config


class TestRemoveLocalIntegration:
    def test_removes_ticket_system(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: myteam\nticket_system: jira\n")
        manager = IntegrationManager(root=tmp_path)
        removed = manager.remove_local_integration("jira")
        assert removed
        config = (tmp_path / "CANON.yaml").read_text()
        assert "ticket_system" not in config
        assert "team: myteam" in config

    def test_no_yaml_returns_false(self, tmp_path: Path):
        manager = IntegrationManager(root=tmp_path)
        assert not manager.remove_local_integration("jira")

    def test_wrong_provider_returns_false(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: myteam\nticket_system: github\n")
        manager = IntegrationManager(root=tmp_path)
        assert not manager.remove_local_integration("jira")


class TestGetProjectKey:
    def test_reads_from_yaml(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("project_key: acme/repo\n")
        manager = IntegrationManager(root=tmp_path)
        assert manager._get_project_key() == "acme/repo"

    def test_fallback_to_git_remote(self, tmp_path: Path):
        manager = IntegrationManager(root=tmp_path)
        with patch("canon.cli._local.resolve_github_remote", return_value=("acme", "repo")):
            assert manager._get_project_key() == "acme/repo"

    def test_returns_empty_when_nothing(self, tmp_path: Path):
        manager = IntegrationManager(root=tmp_path)
        with patch("canon.cli._local.resolve_github_remote", return_value=None):
            assert manager._get_project_key() == ""
