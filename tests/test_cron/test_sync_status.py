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


class TestReverseSyncCompletedEvent:
    """``reverse_sync_completed`` fires per spec file with the adapter
    system name tag."""

    async def test_emits_reverse_sync_completed_with_adapter_name(self):
        """Happy path: one spec, one adapter, one event."""
        from canon.cron.sync_status import run_reverse_sync

        # Fake GitHub client that returns a single repo containing one spec.
        client = AsyncMock()
        client._auth_headers = AsyncMock(return_value={"Authorization": "Bearer x"})
        http_resp = MagicMock()
        http_resp.raise_for_status = MagicMock()
        http_resp.json.return_value = {
            "repositories": [
                {
                    "owner": {"login": "acme"},
                    "name": "widgets",
                    "default_branch": "main",
                }
            ]
        }
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=http_resp)
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

        with (
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
                "canon.cron.sync_status.load_org_mapping_config", new=AsyncMock(return_value=None)
            ),
            patch(
                "canon.cron.sync_status.synthesize_mapping_config",
                return_value=(TicketMappingConfig(), False),
            ),
            patch(
                "canon.cron.sync_status.create_adapter",
                return_value=_MockAdapter("jira"),
            ),
            patch(
                "canon.cron.sync_status.reverse_sync",
                new=AsyncMock(return_value=("updated-md", sync_result)),
            ),
            patch("canon.cron.sync_status.analytics") as mock_analytics,
        ):
            # ``tracked_cron`` wraps run_reverse_sync and emits its own
            # cron_job_executed event after the function completes — we
            # unwrap to bypass that layer so this test only asserts on
            # the per-file event.
            underlying = run_reverse_sync.__wrapped__
            await underlying()

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
