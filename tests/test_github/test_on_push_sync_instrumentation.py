"""Tests for the per-spec and push-level sync analytics events emitted by on_push.

These tests pin the contract that the ``Canon · Ticket Sync`` dashboard
depends on:

* ``spec_sync_completed`` — one per spec that successfully resolved an
  adapter, carrying the adapter system name, repo, file path, and sync
  result counts. Lets the dashboard break sync health down by
  jira/linear/github.
* ``forward_sync_completed`` — emitted once per push with a sorted
  ``adapters_used`` list rolled up from the per-spec loop, plus an
  ``adapter_count`` scalar for quick breakdowns.

Rather than mock every external dependency of ``on_push`` (there are
many: GitHub client, parse_spec, load_repo_config, load_org_mapping_config,
_resolve_adapter_multi, forward_sync, _index_specs, etc.), these tests
patch the minimum surface area to reach the emission points while
feeding a realistic push payload.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canon.config.parse import CanonConfig
from canon.github.handlers.on_push import on_push
from canon.sync.models import SyncResult


def _make_push_payload(spec_files: list[str]) -> dict:
    """Build a minimal webhook push payload that touches the given spec files."""
    return {
        "commits": [
            {
                "added": [],
                "modified": spec_files,
                "removed": [],
                "author": {"name": "dev"},
                "message": "update specs",
            }
        ],
        "ref": "refs/heads/main",
        "repository": {
            "owner": {"login": "acme"},
            "name": "widgets",
            "full_name": "acme/widgets",
        },
        "installation": {"id": 123},
        "after": "deadbeef",
    }


class _MockAdapter:
    """Minimal adapter test double that exposes system_name."""

    def __init__(self, system_name: str) -> None:
        self._name = system_name

    @property
    def system_name(self) -> str:
        return self._name


class TestSpecSyncCompletedEvent:
    """``spec_sync_completed`` fires once per successfully-synced spec with
    an adapter system_name tag."""

    @pytest.fixture
    def _mock_dependencies(self):
        """Patch every external dependency of on_push that would otherwise
        require real GitHub/DB/spec-parser infrastructure. Each test gets a
        fresh set of mocks. Yields the analytics mock for assertion use."""
        parsed_doc = MagicMock()
        parsed_doc.frontmatter.ticket_project = "PROJ-1"
        parsed_doc.frontmatter.title = "Test Spec"
        parsed_doc.frontmatter.status = "draft"
        parsed_doc.sections = []

        parse_result = MagicMock()
        parse_result.document = parsed_doc

        # Forward sync returns markdown + an empty SyncResult (no errors,
        # no tickets created — just exercises the code path).
        sync_result = SyncResult(
            created=[],
            updated=[],
            status_changed=[],
            closed=[],
            reopened=[],
            skipped=[],
            errors=[],
        )

        with (
            patch("canon.github.handlers.on_push.load_repo_config") as mock_cfg,
            patch("canon.github.handlers.on_push.parse_spec") as mock_parse,
            patch("canon.github.handlers.on_push.load_org_mapping_config") as mock_org,
            patch("canon.github.handlers.on_push.synthesize_mapping_config") as mock_synth,
            patch(
                "canon.github.handlers.on_push._resolve_adapter_multi", new_callable=AsyncMock
            ) as mock_resolve,
            patch("canon.github.handlers.on_push.forward_sync") as mock_forward,
            patch("canon.github.handlers.on_push._index_specs", new=AsyncMock()),
            patch("canon.github.handlers.on_push._index_doc_files", new=AsyncMock()),
            patch("canon.github.handlers.on_push._track_code_changes", new=AsyncMock()),
            patch("canon.github.handlers.on_push._get_doc_patterns", return_value=[]),
            patch("canon.github.handlers.on_push._invalidate_web_cache"),
            patch(
                "canon.github.handlers.on_push._get_notification_dispatcher",
                return_value=None,
            ),
            patch("canon.github.handlers.on_push.analytics") as mock_analytics,
        ):
            mock_cfg.return_value = CanonConfig()
            mock_parse.return_value = parse_result
            mock_org.return_value = None
            mock_synth.return_value = (MagicMock(), False)
            mock_forward.return_value = ("updated-markdown", sync_result)

            yield {
                "analytics": mock_analytics,
                "resolve_multi": mock_resolve,
                "forward": mock_forward,
                "parsed_doc": parsed_doc,
            }

    async def test_emits_spec_sync_completed_with_adapter_name(self, _mock_dependencies):
        """A single-spec push emits one spec_sync_completed event carrying
        the adapter's system_name."""
        mocks = _mock_dependencies
        mocks["resolve_multi"].return_value = (
            _MockAdapter("jira"),
            "CANON",
            MagicMock(),
            {},  # no shadow adapters
        )

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("spec content", "file-sha"))
        client.create_or_update_file = AsyncMock()

        payload = _make_push_payload(["docs/specs/feature-a.md"])
        await on_push(client, payload)

        spec_sync_calls = [
            c for c in mocks["analytics"].track.call_args_list if c.args[0] == "spec_sync_completed"
        ]
        assert len(spec_sync_calls) == 1, (
            f"expected exactly one spec_sync_completed event, got "
            f"{[c.args[0] for c in mocks['analytics'].track.call_args_list]}"
        )
        props = spec_sync_calls[0].kwargs["properties"]
        assert props["adapter"] == "jira"
        assert props["repo"] == "acme/widgets"
        assert props["file_path"] == "docs/specs/feature-a.md"
        assert props["project_key"] == "CANON"
        assert props["is_multi_sync"] is False
        assert props["shadow_adapter_count"] == 0
        assert props["success"] is True

    async def test_forward_sync_completed_carries_adapters_used_list(self, _mock_dependencies):
        """Multi-spec push with two different adapters rolls up into
        ``adapters_used=['jira','linear']`` on the push-level
        forward_sync_completed event."""
        mocks = _mock_dependencies

        def _resolve(mapping, doc, project_key, file_path, **kwargs):
            if "feature-a" in file_path:
                return (_MockAdapter("jira"), "CANON", MagicMock(), {})
            return (_MockAdapter("linear"), "LIN", MagicMock(), {})

        mocks["resolve_multi"].side_effect = _resolve

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("spec content", "file-sha"))
        client.create_or_update_file = AsyncMock()

        payload = _make_push_payload(["docs/specs/feature-a.md", "docs/specs/feature-b.md"])
        await on_push(client, payload)

        fwd_calls = [
            c
            for c in mocks["analytics"].track.call_args_list
            if c.args[0] == "forward_sync_completed"
        ]
        assert len(fwd_calls) == 1
        props = fwd_calls[0].kwargs["properties"]
        # Sorted order is part of the contract — the test would otherwise
        # flap on dict/set iteration order.
        assert props["adapters_used"] == ["jira", "linear"]
        assert props["adapter_count"] == 2
        assert props["spec_files_synced"] == 2

    async def test_forward_sync_completed_adapters_used_is_unique(self, _mock_dependencies):
        """Two specs on the same adapter report ``adapters_used=['jira']`` —
        no duplicates."""
        mocks = _mock_dependencies
        mocks["resolve_multi"].return_value = (
            _MockAdapter("jira"),
            "CANON",
            MagicMock(),
            {},
        )

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("spec content", "file-sha"))
        client.create_or_update_file = AsyncMock()

        payload = _make_push_payload(["docs/specs/feature-a.md", "docs/specs/feature-b.md"])
        await on_push(client, payload)

        fwd_calls = [
            c
            for c in mocks["analytics"].track.call_args_list
            if c.args[0] == "forward_sync_completed"
        ]
        assert len(fwd_calls) == 1
        props = fwd_calls[0].kwargs["properties"]
        assert props["adapters_used"] == ["jira"]
        assert props["adapter_count"] == 1

    async def test_forward_sync_completed_empty_adapters_used_when_no_resolution(
        self, _mock_dependencies
    ):
        """When adapter resolution returns None for every spec,
        ``adapters_used=[]``. The parent event still fires because the
        push did contain parsed specs — just none that could be routed."""
        mocks = _mock_dependencies
        mocks["resolve_multi"].return_value = (None, None, None, {})

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("spec content", "file-sha"))
        client.create_or_update_file = AsyncMock()

        payload = _make_push_payload(["docs/specs/feature-a.md"])
        await on_push(client, payload)

        # No per-spec event (the loop `continue`s when adapter is None)...
        spec_sync_calls = [
            c for c in mocks["analytics"].track.call_args_list if c.args[0] == "spec_sync_completed"
        ]
        assert len(spec_sync_calls) == 0

        # ...but the parent event still fires with an empty adapters list.
        fwd_calls = [
            c
            for c in mocks["analytics"].track.call_args_list
            if c.args[0] == "forward_sync_completed"
        ]
        assert len(fwd_calls) == 1
        props = fwd_calls[0].kwargs["properties"]
        assert props["adapters_used"] == []
        assert props["adapter_count"] == 0
