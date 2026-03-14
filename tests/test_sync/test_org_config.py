"""Tests for org-level config loading."""

from __future__ import annotations

import pytest

from canon.sync import org_config
from canon.sync.org_config import load_org_mapping_config


@pytest.fixture(autouse=True)
def _clear_org_config_cache():
    """Clear the org config cache between tests."""
    org_config._cache.clear()
    yield
    org_config._cache.clear()


class MockGitHubClient:
    """Minimal mock for GitHubClient.get_file_content."""

    def __init__(self, files: dict[tuple[str, str, str], str] | None = None):
        self._files = files or {}

    async def get_file_content(self, owner: str, repo: str, path: str, **kwargs):
        key = (owner, repo, path)
        if key in self._files:
            return self._files[key], "fake-sha"
        raise FileNotFoundError(f"Not found: {owner}/{repo}/{path}")


class TestLoadOrgMappingConfig:
    @pytest.mark.asyncio
    async def test_loads_valid_org_config(self):
        yaml_content = """\
ticket_systems:
  primary:
    system: jira
    project: ENG
    status_map:
      forward:
        draft: "Backlog"
        todo: "To Do"
        in_progress: "In Progress"
        done: "Done"
        blocked: "Blocked"
        deprecated: "Won't Do"
"""
        client = MockGitHubClient(
            {
                ("MyOrg", ".github", "specwright.yaml"): yaml_content,
            }
        )

        result = await load_org_mapping_config(client, "MyOrg")
        assert result is not None
        assert "primary" in result.ticket_systems
        assert result.ticket_systems["primary"].system == "jira"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_github_repo(self):
        client = MockGitHubClient()
        result = await load_org_mapping_config(client, "NoOrg")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_file(self):
        client = MockGitHubClient(
            {
                ("MyOrg", ".github", "specwright.yaml"): "",
            }
        )
        result = await load_org_mapping_config(client, "MyOrg")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_ticket_mapping(self):
        yaml_content = """\
team: platform
specs:
  auto_tickets: true
"""
        client = MockGitHubClient(
            {
                ("MyOrg", ".github", "specwright.yaml"): yaml_content,
            }
        )
        result = await load_org_mapping_config(client, "MyOrg")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_invalid_yaml(self):
        client = MockGitHubClient(
            {
                ("MyOrg", ".github", "specwright.yaml"): "{{invalid: yaml: [",
            }
        )
        result = await load_org_mapping_config(client, "MyOrg")
        assert result is None
