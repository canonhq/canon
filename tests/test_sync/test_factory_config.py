"""Tests for config-driven adapter factory."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from canon.sync.adapters.factory import _detect_system, create_adapter, from_config
from canon.sync.adapters.github_issues import GitHubAdapter
from canon.sync.adapters.jira import JiraAdapter
from canon.sync.adapters.linear import LinearAdapter
from canon.sync.mapping import AuthProfile, TicketSystemConfig


class TestFromConfig:
    def test_jira_with_default_env(self) -> None:
        config = TicketSystemConfig(system="jira", project="PAY")
        env = {"JIRA_HOST": "jira.example.com", "JIRA_EMAIL": "a@b.com", "JIRA_API_TOKEN": "tok"}
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("primary", config)
        assert isinstance(adapter, JiraAdapter)

    def test_jira_with_auth_profile(self) -> None:
        config = TicketSystemConfig(system="jira", project="ENG", auth_profile="jira-cloud")
        profiles = {
            "jira-cloud": AuthProfile(
                system="jira", auth_method="api_token", env_prefix="JIRA_CLOUD_"
            )
        }
        env = {
            "JIRA_CLOUD_HOST": "cloud.jira.com",
            "JIRA_CLOUD_EMAIL": "a@b.com",
            "JIRA_CLOUD_API_TOKEN": "tok",
        }
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("primary", config, profiles)
        assert isinstance(adapter, JiraAdapter)
        assert adapter.config.host == "cloud.jira.com"

    def test_jira_host_override(self) -> None:
        config = TicketSystemConfig(
            system="jira", project="OPS", host_override="ops-jira.example.com"
        )
        env = {"JIRA_HOST": "default.jira.com", "JIRA_EMAIL": "a@b.com", "JIRA_API_TOKEN": "tok"}
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("ops", config)
        assert isinstance(adapter, JiraAdapter)
        assert adapter.config.host == "ops-jira.example.com"

    def test_linear_with_default_env(self) -> None:
        config = TicketSystemConfig(system="linear", project="TEAM")
        env = {"LINEAR_API_KEY": "lin_key"}
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("primary", config)
        assert isinstance(adapter, LinearAdapter)

    def test_linear_with_auth_profile(self) -> None:
        config = TicketSystemConfig(system="linear", project="TEAM", auth_profile="lin-eng")
        profiles = {
            "lin-eng": AuthProfile(system="linear", auth_method="api_key", env_prefix="LINEAR_ENG_")
        }
        env = {"LINEAR_ENG_API_KEY": "eng_key"}
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("primary", config, profiles)
        assert isinstance(adapter, LinearAdapter)

    def test_github_with_project_owner_repo(self) -> None:
        config = TicketSystemConfig(system="github", project="myorg/myrepo")
        env = {"GITHUB_TOKEN": "ghp_tok"}
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("oss", config)
        assert isinstance(adapter, GitHubAdapter)
        assert adapter.config.default_owner == "myorg"
        assert adapter.config.default_repo == "myrepo"

    def test_missing_credentials_returns_none(self) -> None:
        config = TicketSystemConfig(system="jira", project="PAY")
        with patch.dict(os.environ, {}, clear=True):
            adapter = from_config("primary", config)
        assert adapter is None

    def test_unknown_system_raises(self) -> None:
        # Bypass the validator for testing
        config = TicketSystemConfig.__new__(TicketSystemConfig)
        object.__setattr__(config, "system", "azure")
        object.__setattr__(config, "project", "PROJ")
        object.__setattr__(config, "auth_profile", None)
        object.__setattr__(config, "host_override", None)
        with pytest.raises(ValueError, match="No default env prefix"):
            from_config("primary", config)


class TestDetectSystemWithToken:
    def test_github_token_triggers_github_detection(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert _detect_system(github_token="ghs_xxx") == "github"

    def test_no_token_no_env_returns_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert _detect_system() is None

    def test_env_var_still_works(self) -> None:
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_tok"}, clear=True):
            assert _detect_system() == "github"

    def test_jira_takes_precedence_over_github_token(self) -> None:
        with patch.dict(os.environ, {"JIRA_HOST": "jira.example.com"}, clear=True):
            assert _detect_system(github_token="ghs_xxx") == "jira"


class TestCreateAdapterWithGitHubToken:
    def test_github_token_with_owner_repo_project(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            adapter = create_adapter(ticket_project="myorg/myrepo", github_token="ghs_xxx")
        assert isinstance(adapter, GitHubAdapter)
        assert adapter.config.default_owner == "myorg"
        assert adapter.config.default_repo == "myrepo"
        assert adapter.config.token == "ghs_xxx"

    def test_env_token_takes_precedence_over_github_token(self) -> None:
        env = {
            "GITHUB_TOKEN": "ghp_env",
            "GITHUB_OWNER": "env-org",
            "GITHUB_REPO": "env-repo",
        }
        with patch.dict(os.environ, env, clear=True):
            adapter = create_adapter(ticket_project="myorg/myrepo", github_token="ghs_app")
        assert isinstance(adapter, GitHubAdapter)
        assert adapter.config.token == "ghp_env"

    def test_no_token_no_env_returns_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            adapter = create_adapter(ticket_project="myorg/myrepo")
        assert adapter is None

    def test_project_without_slash_returns_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            adapter = create_adapter(ticket_project="no-slash", github_token="ghs_xxx")
        assert adapter is None

    def test_project_with_multiple_slashes_splits_on_first(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            adapter = create_adapter(ticket_project="org/repo/extra", github_token="ghs_xxx")
        assert isinstance(adapter, GitHubAdapter)
        assert adapter.config.default_owner == "org"
        assert adapter.config.default_repo == "repo/extra"

    def test_env_owner_repo_not_overridden_by_project(self) -> None:
        env = {"GITHUB_OWNER": "env-org", "GITHUB_REPO": "env-repo"}
        with patch.dict(os.environ, env, clear=True):
            adapter = create_adapter(ticket_project="proj-org/proj-repo", github_token="ghs_xxx")
        assert isinstance(adapter, GitHubAdapter)
        assert adapter.config.default_owner == "env-org"
        assert adapter.config.default_repo == "env-repo"


class TestFromConfigWithGitHubToken:
    def test_env_token_takes_precedence_over_github_token(self) -> None:
        """Auth profile / env var credentials should win over installation token."""
        config = TicketSystemConfig(system="github", project="myorg/myrepo")
        env = {"GITHUB_TOKEN": "ghp_env_token"}
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("oss", config, github_token="ghs_app_token")
        assert isinstance(adapter, GitHubAdapter)
        assert adapter.config.token == "ghp_env_token"

    def test_falls_back_to_github_token_when_no_env(self) -> None:
        """Installation token is fallback when no env var is configured."""
        config = TicketSystemConfig(system="github", project="myorg/myrepo")
        with patch.dict(os.environ, {}, clear=True):
            adapter = from_config("oss", config, github_token="ghs_app_token")
        assert isinstance(adapter, GitHubAdapter)
        assert adapter.config.token == "ghs_app_token"
        assert adapter.config.default_owner == "myorg"
        assert adapter.config.default_repo == "myrepo"

    def test_env_token_used_when_no_github_token(self) -> None:
        config = TicketSystemConfig(system="github", project="myorg/myrepo")
        env = {"GITHUB_TOKEN": "ghp_env_token"}
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("oss", config, github_token="")
        assert isinstance(adapter, GitHubAdapter)
        assert adapter.config.token == "ghp_env_token"

    def test_jira_unaffected_by_github_token(self) -> None:
        config = TicketSystemConfig(system="jira", project="PAY")
        env = {"JIRA_HOST": "j.com", "JIRA_EMAIL": "a@b.com", "JIRA_API_TOKEN": "tok"}
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("primary", config, github_token="ghs_xxx")
        assert isinstance(adapter, JiraAdapter)


class TestAdapterCapabilities:
    def test_jira_capabilities(self) -> None:
        env = {"JIRA_HOST": "jira.example.com", "JIRA_EMAIL": "a@b.com", "JIRA_API_TOKEN": "tok"}
        config = TicketSystemConfig(system="jira", project="PAY")
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("primary", config)
        assert adapter is not None
        caps = adapter.capabilities
        assert caps.supports_custom_fields is True
        assert caps.supports_hierarchy is True
        assert caps.supports_subtasks is True
        assert caps.supports_issue_types is True

    def test_linear_capabilities(self) -> None:
        env = {"LINEAR_API_KEY": "lin_key"}
        config = TicketSystemConfig(system="linear", project="TEAM")
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("primary", config)
        assert adapter is not None
        caps = adapter.capabilities
        assert caps.supports_custom_fields is False
        assert caps.supports_issue_types is False
        assert caps.supports_hierarchy is True

    def test_github_capabilities(self) -> None:
        config = TicketSystemConfig(system="github", project="org/repo")
        env = {"GITHUB_TOKEN": "ghp_tok"}
        with patch.dict(os.environ, env, clear=False):
            adapter = from_config("oss", config)
        assert adapter is not None
        caps = adapter.capabilities
        assert caps.supports_custom_fields is False
        assert caps.supports_hierarchy is False
        assert caps.supports_subtasks is False
        assert caps.supports_labels is True
