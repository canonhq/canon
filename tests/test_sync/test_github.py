"""Port of github-adapter tests — GitHub Issues integration."""

from __future__ import annotations

import pytest

from canon.parser.models import SectionStatus
from canon.sync.adapters.github_issues import (
    GitHubAdapter,
    parse_github_ticket_id,
)
from canon.sync.models import (
    CreateTicketInput,
    GitHubConfig,
    UpdateTicketInput,
)

TEST_OWNER = "test-org"
TEST_REPO = "test-repo"
TEST_API_BASE = f"https://api.github.com/repos/{TEST_OWNER}/{TEST_REPO}"


@pytest.fixture
def config() -> GitHubConfig:
    return GitHubConfig(
        token="test-token",
        default_owner=TEST_OWNER,
        default_repo=TEST_REPO,
    )


class TestParseGitHubTicketId:
    def test_bare_number(self, config: GitHubConfig):
        parsed = parse_github_ticket_id("7", config)
        assert parsed.owner == TEST_OWNER
        assert parsed.repo == TEST_REPO
        assert parsed.issue_number == 7

    def test_repo_number(self, config: GitHubConfig):
        parsed = parse_github_ticket_id("other-repo#42", config)
        assert parsed.owner == TEST_OWNER
        assert parsed.repo == "other-repo"
        assert parsed.issue_number == 42

    def test_full_format(self, config: GitHubConfig):
        parsed = parse_github_ticket_id("acme/widgets#99", config)
        assert parsed.owner == "acme"
        assert parsed.repo == "widgets"
        assert parsed.issue_number == 99

    def test_invalid_ticket_id_raises(self, config: GitHubConfig):
        with pytest.raises(ValueError, match="Invalid GitHub ticket ID"):
            parse_github_ticket_id("not-valid", config)


class TestGitHubAdapter:
    @pytest.mark.asyncio
    async def test_create_ticket(self, config: GitHubConfig, respx_mock):
        respx_mock.post(f"{TEST_API_BASE}/issues").respond(
            json={"number": 10, "html_url": "https://github.com/org/repo/issues/10"}
        )

        adapter = GitHubAdapter(config)
        result = await adapter.create_ticket(
            CreateTicketInput(
                project_key="GV",
                summary="[1] Test Section",
                description="Content",
                status=SectionStatus(state="todo"),
            )
        )
        assert result.ticket_id == "10"
        assert "issues/10" in result.ticket_url

    @pytest.mark.asyncio
    async def test_create_ticket_closes_for_done_status(self, config: GitHubConfig, respx_mock):
        respx_mock.post(f"{TEST_API_BASE}/issues").respond(
            json={"number": 11, "html_url": "https://github.com/org/repo/issues/11"}
        )
        respx_mock.patch(f"{TEST_API_BASE}/issues/11").respond(
            json={"number": 11, "state": "closed"}
        )

        adapter = GitHubAdapter(config)
        result = await adapter.create_ticket(
            CreateTicketInput(
                project_key="GV",
                summary="Done section",
                description="Done",
                status=SectionStatus(state="done"),
            )
        )
        assert result.ticket_id == "11"

    @pytest.mark.asyncio
    async def test_get_ticket_status(self, config: GitHubConfig, respx_mock):
        respx_mock.get(f"{TEST_API_BASE}/issues/7").respond(
            json={
                "state": "open",
                "labels": [{"name": "specwright:in-progress"}, {"name": "bug"}],
            }
        )

        adapter = GitHubAdapter(config)
        result = await adapter.get_ticket_status("7")
        assert result.status.state == "in_progress"
        # raw_status is the specwright label (most meaningful status string)
        assert result.raw_status == "specwright:in-progress"

    @pytest.mark.asyncio
    async def test_get_ticket_status_fallback(self, config: GitHubConfig, respx_mock):
        respx_mock.get(f"{TEST_API_BASE}/issues/8").respond(json={"state": "closed", "labels": []})

        adapter = GitHubAdapter(config)
        result = await adapter.get_ticket_status("8")
        assert result.status.state == "done"

    @pytest.mark.asyncio
    async def test_update_ticket_with_status(self, config: GitHubConfig, respx_mock):
        respx_mock.get(f"{TEST_API_BASE}/issues/7").respond(
            json={
                "state": "open",
                "labels": [{"name": "specwright:todo"}, {"name": "feature"}],
            }
        )
        respx_mock.patch(f"{TEST_API_BASE}/issues/7").respond(json={"number": 7})

        adapter = GitHubAdapter(config)
        await adapter.update_ticket(
            UpdateTicketInput(
                ticket_id="7",
                status=SectionStatus(state="in_progress"),
            )
        )

    @pytest.mark.asyncio
    async def test_link_pr(self, config: GitHubConfig, respx_mock):
        respx_mock.post(f"{TEST_API_BASE}/issues/7/comments").respond(json={"id": 1})

        adapter = GitHubAdapter(config)
        await adapter.link_pr("7", "https://github.com/org/repo/pull/5", "Fix thing")
