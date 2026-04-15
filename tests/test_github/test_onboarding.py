"""Tests for GitHub App onboarding flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import yaml

from canon.github.client import DocPRResult
from canon.github.handlers.onboarding import (
    ONBOARD_BRANCH_PREFIX,
    ONBOARD_LABEL,
    ONBOARD_MARKER,
    _format_summary_body,
    onboard_repo,
    onboard_repos,
)
from canon.parser.models import (
    AcceptanceCriterion,
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
)
from canon.setup import create_canon_yaml

# ─── Helpers ──────────────────────────────────────────────────


def _make_spec(title: str = "My Spec", status: str = "draft", sections: int = 2, acs: int = 1):
    """Create a minimal spec dict matching load_repo_specs output."""
    spec_sections = [
        SpecSection(
            id=f"sec-{i}",
            section_number=str(i + 1),
            title=f"Section {i + 1}",
            depth=2,
            content="content",
            status=SectionStatus(state="draft"),
            acceptance_criteria=[
                AcceptanceCriterion(text=f"AC {j}", checked=False, line=j) for j in range(acs)
            ],
            start_line=1,
            end_line=10,
        )
        for i in range(sections)
    ]
    doc = SpecDocument(
        file_path=f"docs/specs/{title.lower().replace(' ', '-')}.md",
        frontmatter=SpecFrontmatter(title=title, status=status, owner="alice", team="eng"),
        sections=spec_sections,
        raw="# raw",
    )
    return {"file_path": doc.file_path, "document": doc, "raw": "# raw"}


def _mock_client():
    """Create a mock GitHubClient with common methods stubbed.

    list_issues returns [] by default (no existing onboarding issue).
    The idempotency check filters by the ``specwright-onboarding`` label
    and scans for ONBOARD_MARKER in the body.
    """
    client = AsyncMock()
    client.list_issues = AsyncMock(return_value=[])
    client.find_open_doc_pr = AsyncMock(return_value=None)
    client.get_file_content = AsyncMock(side_effect=Exception("404"))
    client.ensure_label = AsyncMock()
    client.create_issue = AsyncMock(return_value={"number": 1})
    client.create_doc_pr = AsyncMock(
        return_value=DocPRResult(pr_number=1, pr_url="https://github.com/o/r/pull/1")
    )
    return client


# ─── TestDefaultSpecwrightYaml ────────────────────────────────


class TestDefaultSpecwrightYaml:
    def test_is_valid_yaml(self):
        content = create_canon_yaml()
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)

    def test_has_expected_defaults(self):
        content = create_canon_yaml()
        parsed = yaml.safe_load(content)
        assert parsed["specs"]["auto_tickets"] is False
        assert parsed["specs"]["require_review"] is True
        assert parsed["agents"]["doc_updates"] is True
        assert parsed["agents"]["pr_analysis"] is True
        assert parsed["agents"]["stale_detection"] == "30d"


# ─── TestFormatSummaryBody ────────────────────────────────────


class TestFormatSummaryBody:
    def test_includes_marker(self):
        body = _format_summary_body([_make_spec()], [])
        assert ONBOARD_MARKER in body

    def test_includes_spec_rows(self):
        specs = [_make_spec("Auth"), _make_spec("Billing")]
        body = _format_summary_body(specs, [])
        assert "auth" in body.lower()
        assert "billing" in body.lower()
        # Table header + 2 data rows
        table_lines = [ln for ln in body.split("\n") if ln.startswith("|")]
        assert len(table_lines) == 4  # header + separator + 2 rows

    def test_includes_config_diagnostics(self):
        diags = ["- **warning**: Unknown config key"]
        body = _format_summary_body([_make_spec()], diags)
        assert "Config diagnostics" in body
        assert "Unknown config key" in body

    def test_no_diagnostics_section_when_clean(self):
        body = _format_summary_body([_make_spec()], [])
        assert "Config diagnostics" not in body


# ─── TestOnboardRepoWithSpecs ─────────────────────────────────


class TestOnboardRepoWithSpecs:
    @pytest.fixture()
    def client(self):
        return _mock_client()

    async def test_posts_summary_issue(self, client):
        specs = [_make_spec("Auth")]
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=specs),
        ):
            await onboard_repo(client, "acme", "api")

        client.ensure_label.assert_awaited_once()
        client.create_issue.assert_awaited_once()
        kw = client.create_issue.call_args.kwargs
        assert kw["title"] == "Canon: Welcome — spec summary"
        assert ONBOARD_MARKER in kw["body"]
        assert ONBOARD_LABEL in kw["labels"]

    async def test_includes_all_specs_in_body(self, client):
        specs = [_make_spec("Auth"), _make_spec("Billing")]
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=specs),
        ):
            await onboard_repo(client, "acme", "api")

        body = client.create_issue.call_args.kwargs["body"]
        assert "auth" in body.lower()
        assert "billing" in body.lower()

    async def test_validates_config_and_includes_diagnostics(self, client):
        specs = [_make_spec()]
        # Return valid YAML with a warning-triggering unknown key.
        # Depends on parse_specwright_yaml emitting a "warning" diagnostic
        # for unrecognized top-level keys (see config/parse.py).
        client.get_file_content = AsyncMock(
            return_value=("team: eng\nunknown_key: true\n", "sha123")
        )
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=specs),
        ):
            await onboard_repo(client, "acme", "api")

        body = client.create_issue.call_args.kwargs["body"]
        assert "Config diagnostics" in body
        assert "unknown_key" in body

    async def test_skips_if_issue_exists(self, client):
        client.list_issues = AsyncMock(
            return_value=[{"number": 42, "body": f"some text\n{ONBOARD_MARKER}\nmore text"}]
        )
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=[_make_spec()]),
        ) as mock_load:
            await onboard_repo(client, "acme", "api")

        client.create_issue.assert_not_awaited()
        mock_load.assert_not_awaited()

    async def test_skips_if_pr_exists(self, client):
        """Exercises the PR-check short-circuit: when an onboarding PR already
        exists, no issue is created and spec loading is skipped entirely."""
        client.find_open_doc_pr = AsyncMock(
            return_value=DocPRResult(pr_number=5, pr_url="https://github.com/acme/api/pull/5")
        )
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=[_make_spec()]),
        ) as mock_load:
            await onboard_repo(client, "acme", "api")

        client.create_issue.assert_not_awaited()
        mock_load.assert_not_awaited()


# ─── TestOnboardRepoWithoutSpecs ──────────────────────────────


class TestOnboardRepoWithoutSpecs:
    @pytest.fixture()
    def client(self):
        return _mock_client()

    async def test_opens_pr_with_template_and_config(self, client):
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=[]),
        ):
            await onboard_repo(client, "acme", "api")

        client.create_doc_pr.assert_awaited_once()
        call_kwargs = client.create_doc_pr.call_args[1]
        assert call_kwargs["branch"] == f"{ONBOARD_BRANCH_PREFIX}acme-api"
        file_paths = [f.path for f in call_kwargs["files"]]
        assert "docs/specs/_template.md" in file_paths
        assert "CANON.yaml" in file_paths

    async def test_opens_pr_without_config_when_config_exists(self, client):
        # Simulate existing CANON.yaml
        client.get_file_content = AsyncMock(return_value=("team: eng\n", "sha123"))
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=[]),
        ):
            await onboard_repo(client, "acme", "api")

        call_kwargs = client.create_doc_pr.call_args[1]
        file_paths = [f.path for f in call_kwargs["files"]]
        assert "docs/specs/_template.md" in file_paths
        assert "CANON.yaml" not in file_paths

    async def test_pr_body_has_getting_started(self, client):
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=[]),
        ):
            await onboard_repo(client, "acme", "api")

        body = client.create_doc_pr.call_args[1]["body"]
        assert "Getting started" in body
        assert ONBOARD_MARKER in body

    async def test_skips_if_pr_exists(self, client):
        """Exercises the PR-check short-circuit: when an onboarding PR already
        exists, no new PR is created."""
        client.find_open_doc_pr = AsyncMock(
            return_value=DocPRResult(pr_number=5, pr_url="https://github.com/acme/api/pull/5")
        )
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=[]),
        ):
            await onboard_repo(client, "acme", "api")

        client.create_doc_pr.assert_not_awaited()

    async def test_skips_if_issue_exists(self, client):
        client.list_issues = AsyncMock(return_value=[{"number": 42, "body": f"{ONBOARD_MARKER}"}])
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=[]),
        ):
            await onboard_repo(client, "acme", "api")

        client.create_doc_pr.assert_not_awaited()


# ─── TestOnboardRepos ─────────────────────────────────────────


class TestOnboardRepos:
    async def test_processes_multiple_repos(self):
        client = _mock_client()
        repos = [
            {"full_name": "acme/api"},
            {"full_name": "acme/web"},
        ]
        with (
            patch("canon.github.handlers.onboarding.load_repo_specs", AsyncMock(return_value=[])),
            patch("canon.github.handlers.onboarding.async_sleep", AsyncMock()),
        ):
            await onboard_repos(client, repos)

        assert client.create_doc_pr.await_count == 2

    async def test_one_failure_does_not_block_others(self):
        client = _mock_client()
        repos = [
            {"full_name": "acme/api"},
            {"full_name": "acme/web"},
        ]
        call_count = 0

        async def _mock_load(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            return []

        with (
            patch("canon.github.handlers.onboarding.load_repo_specs", _mock_load),
            patch("canon.github.handlers.onboarding.async_sleep", AsyncMock()),
        ):
            await onboard_repos(client, repos)

        # Second repo should still get its PR
        assert client.create_doc_pr.await_count == 1

    async def test_skips_invalid_names(self):
        client = _mock_client()
        repos = [
            {"full_name": "no-slash"},
            {"full_name": "acme/api"},
        ]
        with patch(
            "canon.github.handlers.onboarding.load_repo_specs",
            AsyncMock(return_value=[]),
        ):
            await onboard_repos(client, repos)

        # Only the valid repo gets processed
        assert client.create_doc_pr.await_count == 1
