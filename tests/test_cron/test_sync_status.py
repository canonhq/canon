"""Tests for reverse sync cron job instrumentation.

These tests pin the ``reverse_sync_completed`` event contract that the
``Canon · Ticket Sync`` dashboard depends on for per-file reverse sync
health. Like the forward sync tests in
``tests/test_github/test_on_push_sync_instrumentation.py``, these patch
the minimum external dependencies to reach the emission point in
:func:`canon.cron.sync_status.run_reverse_sync`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canon.config.parse import CanonConfig, SpecsConfig
from canon.sync.mapping import TicketMappingConfig
from canon.sync.models import SyncResult, SyncStatusChanged


class _MockAdapter:
    """Minimal adapter test double exposing system_name."""

    def __init__(self, system_name: str) -> None:
        self._name = system_name

    @property
    def system_name(self) -> str:
        return self._name


def _make_client(*, tree_response=None):
    """Build a fake GitHubClient with Trees API support.

    Args:
        tree_response: If provided, ``client._get`` returns this dict for
            the Trees API call. If None, Trees API raises so the fallback
            Contents API path is exercised.
    """
    client = AsyncMock()
    client.get_installation_token = AsyncMock(return_value="fake-token")
    client.list_installation_repos = AsyncMock(
        return_value=[
            {
                "owner": {"login": "acme"},
                "name": "widgets",
                "default_branch": "main",
            }
        ]
    )
    if tree_response is not None:
        client._get = AsyncMock(return_value=tree_response)
    else:
        client._get = AsyncMock(side_effect=Exception("Trees API unavailable"))
    client.list_directory = AsyncMock(
        return_value=[
            {
                "type": "file",
                "name": "feature-a.md",
                "path": "docs/specs/feature-a.md",
            }
        ]
    )
    client.get_file_content = AsyncMock(return_value=("spec content", "file-sha"))
    client.create_or_update_file = AsyncMock()
    client.close = AsyncMock()
    return client


def _standard_patches(client, mock_adapter=None):
    """Return a list of context managers for the standard sync patches."""
    parsed_doc = MagicMock()
    parsed_doc.frontmatter.ticket_project = "CANON"
    parsed_doc.frontmatter.title = "Feature A"
    parse_result = MagicMock()
    parse_result.document = parsed_doc

    sync_result = SyncResult(
        status_changed=[
            SyncStatusChanged(
                section_id="1",
                ticket_id="CANON-1",
                old_state="todo",
                new_state="done",
            )
        ],
        errors=[],
    )

    settings_mock = MagicMock(
        gh_app_id="123",
        gh_private_key="key",
        gh_installation_id="456",
    )

    repo_config = CanonConfig(
        ticket_system="jira",
        project_key="CANON",
        specs=SpecsConfig(doc_paths=["docs/specs"]),
    )

    adapter = mock_adapter or _MockAdapter("jira")

    return (
        patch("canon.cron.sync_status.Settings", return_value=settings_mock),
        patch("canon.cron.sync_status.GitHubClient", return_value=client),
        patch(
            "canon.github.spec_utils.load_repo_config",
            new=AsyncMock(return_value=repo_config),
        ),
        patch(
            "canon.github.spec_utils.extract_directories",
            return_value=[("docs/specs", False)],
        ),
        patch("canon.github.spec_utils.matches_doc_patterns", return_value=True),
        patch("canon.cron.sync_status.parse_spec", return_value=parse_result),
        patch(
            "canon.cron.sync_status.load_org_mapping_config",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "canon.cron.sync_status.synthesize_mapping_config",
            return_value=(TicketMappingConfig(), False),
        ),
        patch(
            "canon.cron.sync_status.create_adapter",
            return_value=adapter,
        ),
        patch(
            "canon.cron.sync_status.reverse_sync",
            new=AsyncMock(return_value=("updated-md", sync_result)),
        ),
        patch("canon.cron.sync_status.analytics"),
    )


class TestReverseSyncCompletedEvent:
    """``reverse_sync_completed`` fires per spec file with the adapter
    system name tag."""

    async def test_emits_reverse_sync_completed_via_trees_api(self):
        """Happy path using Git Trees API (primary path)."""
        from canon.cron.sync_status import run_reverse_sync

        tree_response = {
            "tree": [
                {"path": "docs/specs/feature-a.md", "type": "blob"},
                {"path": "src/main.py", "type": "blob"},
                {"path": "src", "type": "tree"},
            ],
            "truncated": False,
        }
        client = _make_client(tree_response=tree_response)
        patches = _standard_patches(client)

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
            patches[10] as mock_analytics,
        ):
            underlying = run_reverse_sync.__wrapped__
            await underlying()

        # Trees API was called, not list_directory
        client._get.assert_called_once()
        client.list_directory.assert_not_called()

        reverse_calls = [
            c for c in mock_analytics.track.call_args_list if c.args[0] == "reverse_sync_completed"
        ]
        assert len(reverse_calls) == 1, (
            f"expected one reverse_sync_completed event, got "
            f"{[c.args[0] for c in mock_analytics.track.call_args_list]}"
        )
        props = reverse_calls[0].kwargs["properties"]
        assert props["adapter"] == "jira"
        assert props["repo"] == "acme/widgets"
        assert props["file_path"] == "docs/specs/feature-a.md"
        assert props["status_changed_count"] == 1
        assert props["error_count"] == 0
        assert props["success"] is True

    async def test_falls_back_to_contents_api_on_trees_failure(self):
        """When Trees API fails, falls back to Contents API listing."""
        from canon.cron.sync_status import run_reverse_sync

        client = _make_client(tree_response=None)  # Trees API will raise
        patches = _standard_patches(client)

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
            patches[10] as mock_analytics,
        ):
            underlying = run_reverse_sync.__wrapped__
            await underlying()

        # Trees API was attempted then fell back to list_directory
        client._get.assert_called_once()
        client.list_directory.assert_called_once()

        reverse_calls = [
            c for c in mock_analytics.track.call_args_list if c.args[0] == "reverse_sync_completed"
        ]
        assert len(reverse_calls) == 1

    async def test_falls_back_on_truncated_tree(self):
        """Truncated tree response triggers Contents API fallback."""
        from canon.cron.sync_status import run_reverse_sync

        tree_response = {
            "tree": [{"path": "docs/specs/feature-a.md", "type": "blob"}],
            "truncated": True,
        }
        client = _make_client(tree_response=tree_response)
        patches = _standard_patches(client)

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
            patches[10],
        ):
            underlying = run_reverse_sync.__wrapped__
            await underlying()

        # Should have fallen back to list_directory
        client.list_directory.assert_called_once()

    async def test_repo_list_failure_raises(self):
        """When list_installation_repos fails, the job raises (not silent no-op)."""
        from canon.cron.sync_status import run_reverse_sync

        client = _make_client()
        client.list_installation_repos = AsyncMock(side_effect=Exception("403 rate limit"))
        patches = _standard_patches(client)

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
            patches[10] as mock_analytics,
        ):
            underlying = run_reverse_sync.__wrapped__
            with pytest.raises(Exception, match="403 rate limit"):
                await underlying()

        # Should have emitted the failure analytics event before re-raising
        fail_calls = [
            c
            for c in mock_analytics.track.call_args_list
            if c.args[0] == "reverse_sync_repo_list_failed"
        ]
        assert len(fail_calls) == 1
