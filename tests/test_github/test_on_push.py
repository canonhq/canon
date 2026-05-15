"""Tests for the on_push webhook handler.

Covers the main ``on_push`` orchestrator and key helper functions:
- Bot/loop-prevention logic
- File classification (changed vs removed, spec vs non-spec)
- ``_notify_spec_status_change`` / ``_notify_coverage_regression``
- ``_index_specs`` / ``_cache_specs`` / ``_index_doc_files``
- ``_invalidate_web_cache``
- ``_resolve_adapter`` / ``_resolve_adapter_multi``
- End-to-end orchestrator flow (happy path, errors, edge cases)

The existing ``test_on_push_sync_instrumentation.py`` covers analytics
event contracts; this file covers everything else.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canon.config.parse import CanonConfig
from canon.github.handlers.on_push import (
    BOT_SUFFIX,
    _invalidate_web_cache,
    _notify_coverage_regression,
    _notify_spec_status_change,
    on_push,
)
from canon.sync.models import SyncCreated, SyncError, SyncResult

# ─── Helpers ────────────────────────────────────────────


def _make_push_payload(
    *,
    spec_files_modified: list[str] | None = None,
    spec_files_added: list[str] | None = None,
    spec_files_removed: list[str] | None = None,
    non_spec_files: list[str] | None = None,
    author_name: str = "dev",
    commit_message: str = "update specs",
    ref: str = "refs/heads/main",
    owner: str = "acme",
    repo: str = "widgets",
    before_sha: str = "aaa111",
    after_sha: str = "bbb222",
) -> dict:
    """Build a push webhook payload with fine-grained control."""
    added = list(spec_files_added or [])
    modified = list(spec_files_modified or [])
    removed = list(spec_files_removed or [])
    if non_spec_files:
        modified.extend(non_spec_files)

    return {
        "commits": [
            {
                "added": added,
                "modified": modified,
                "removed": removed,
                "author": {"name": author_name},
                "message": commit_message,
            }
        ],
        "ref": ref,
        "repository": {
            "owner": {"login": owner},
            "name": repo,
            "full_name": f"{owner}/{repo}",
        },
        "installation": {"id": 123},
        "before": before_sha,
        "after": after_sha,
    }


def _empty_sync_result(**overrides) -> SyncResult:
    return SyncResult(
        created=overrides.get("created", []),
        updated=overrides.get("updated", []),
        status_changed=overrides.get("status_changed", []),
        closed=[],
        reopened=[],
        skipped=[],
        errors=overrides.get("errors", []),
    )


class _FakeAdapter:
    """Minimal adapter double."""

    def __init__(self, name: str = "jira") -> None:
        self._name = name

    @property
    def system_name(self) -> str:
        return self._name


# ─── Bot / Loop Prevention ──────────────────────────────


class TestBotLoopPrevention:
    """on_push should skip pushes authored by bots or with canon commit prefixes."""

    @pytest.fixture
    def _patch_deps(self):
        """Minimal patches — we only need to verify early return."""
        with (
            patch("canon.github.handlers.on_push._invalidate_web_cache"),
            patch("canon.github.handlers.on_push.analytics"),
        ):
            yield

    async def test_skips_bot_author(self, _patch_deps):
        payload = _make_push_payload(
            spec_files_modified=["docs/specs/foo.md"],
            author_name=f"canon{BOT_SUFFIX}",
        )
        client = AsyncMock()
        await on_push(client, payload)
        # Should return immediately — no file content fetched
        client.get_file_content.assert_not_called()

    async def test_skips_canon_chore_commit(self, _patch_deps):
        payload = _make_push_payload(
            spec_files_modified=["docs/specs/foo.md"],
            commit_message="chore(canon): add ticket links to docs/specs/foo.md",
        )
        client = AsyncMock()
        await on_push(client, payload)
        client.get_file_content.assert_not_called()

    async def test_skips_specwright_chore_commit(self, _patch_deps):
        payload = _make_push_payload(
            spec_files_modified=["docs/specs/foo.md"],
            commit_message="chore(specwright): legacy prefix",
        )
        client = AsyncMock()
        await on_push(client, payload)
        client.get_file_content.assert_not_called()

    async def test_allows_normal_commits(self, _patch_deps):
        """A normal commit message should NOT be skipped at the bot-check stage."""
        payload = _make_push_payload(
            spec_files_modified=["docs/specs/foo.md"],
            commit_message="feat: add new feature",
        )
        # We need more patches to avoid errors deeper in the flow
        with (
            patch("canon.github.handlers.on_push.load_repo_config", new_callable=AsyncMock) as cfg,
            patch(
                "canon.github.handlers.on_push.load_org_mapping_config",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("canon.github.handlers.on_push.synthesize_mapping_config") as synth,
            patch("canon.github.handlers.on_push.parse_spec") as parse,
            patch(
                "canon.github.handlers.on_push._resolve_adapter_multi", new_callable=AsyncMock
            ) as resolve,
            patch("canon.github.handlers.on_push._index_specs", new=AsyncMock()),
            patch("canon.github.handlers.on_push._cache_specs", new=AsyncMock()),
            patch("canon.github.handlers.on_push._get_doc_patterns", return_value=[]),
            patch("canon.github.handlers.on_push._track_code_changes", new=AsyncMock()),
        ):
            cfg.return_value = CanonConfig()
            synth.return_value = (MagicMock(), False)
            doc = MagicMock()
            doc.frontmatter.ticket_project = ""
            doc.frontmatter.status = "draft"
            doc.frontmatter.title = "Test"
            doc.sections = []
            parse.return_value = MagicMock(document=doc)
            resolve.return_value = (None, None, None, {})

            client = AsyncMock()
            client.get_file_content = AsyncMock(return_value=("content", "sha"))
            client.get_installation_token = AsyncMock(return_value="tok")
            await on_push(client, payload)
            # It should have proceeded past bot check and fetched file content
            client.get_file_content.assert_called()


# ─── No Spec Files ──────────────────────────────────────


class TestNoSpecFiles:
    """When push contains no spec files, on_push should return early after cache invalidation."""

    async def test_returns_early_no_specs(self):
        payload = _make_push_payload(non_spec_files=["src/main.py", "README.md"])
        with (
            patch("canon.github.handlers.on_push._invalidate_web_cache") as mock_cache,
            patch("canon.github.handlers.on_push.analytics"),
        ):
            client = AsyncMock()
            await on_push(client, payload)
            # Cache is invalidated even without specs
            mock_cache.assert_called_once_with("acme", "widgets")
            # But no config loading happens
            client.get_file_content.assert_not_called()

    async def test_empty_commits(self):
        """Push with no commits at all."""
        payload = {
            "commits": [],
            "ref": "refs/heads/main",
            "repository": {"owner": {"login": "acme"}, "name": "widgets"},
            "after": "abc123",
        }
        with (
            patch("canon.github.handlers.on_push._invalidate_web_cache") as mock_cache,
            patch("canon.github.handlers.on_push.analytics"),
        ):
            client = AsyncMock()
            await on_push(client, payload)
            mock_cache.assert_called_once()


# ─── File Classification ────────────────────────────────


class TestFileClassification:
    """Verify that changed vs removed files are correctly classified."""

    async def test_removed_files_excluded_from_sync_loop(self):
        """Removed spec files should not be fetched or synced, but should
        be passed to _index_specs for deletion."""
        payload = _make_push_payload(
            spec_files_modified=["docs/specs/kept.md"],
            spec_files_removed=["docs/specs/deleted.md"],
        )

        parsed_doc = MagicMock()
        parsed_doc.frontmatter.ticket_project = ""
        parsed_doc.frontmatter.status = "draft"
        parsed_doc.frontmatter.title = "Kept"
        parsed_doc.sections = []

        with (
            patch("canon.github.handlers.on_push._invalidate_web_cache"),
            patch("canon.github.handlers.on_push.analytics"),
            patch(
                "canon.github.handlers.on_push.load_repo_config",
                new_callable=AsyncMock,
                return_value=CanonConfig(),
            ),
            patch(
                "canon.github.handlers.on_push.load_org_mapping_config",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "canon.github.handlers.on_push.synthesize_mapping_config",
                return_value=(MagicMock(), False),
            ),
            patch(
                "canon.github.handlers.on_push.parse_spec",
                return_value=MagicMock(document=parsed_doc),
            ),
            patch(
                "canon.github.handlers.on_push._resolve_adapter_multi",
                new_callable=AsyncMock,
                return_value=(None, None, None, {}),
            ),
            patch(
                "canon.github.handlers.on_push._index_specs", new_callable=AsyncMock
            ) as mock_index,
            patch("canon.github.handlers.on_push._cache_specs", new_callable=AsyncMock),
            patch("canon.github.handlers.on_push._get_doc_patterns", return_value=[]),
            patch("canon.github.handlers.on_push._track_code_changes", new=AsyncMock()),
        ):
            client = AsyncMock()
            client.get_file_content = AsyncMock(return_value=("content", "sha"))
            client.get_installation_token = AsyncMock(return_value="tok")

            await on_push(client, payload)

            # Only the kept file should be fetched (not the deleted one)
            fetched_paths = [call.args[2] for call in client.get_file_content.call_args_list]
            assert "docs/specs/deleted.md" not in fetched_paths
            assert "docs/specs/kept.md" in fetched_paths

            # _index_specs receives the removed set
            mock_index.assert_called_once()
            removed_arg = mock_index.call_args.args[3]  # removed_spec_files
            assert "docs/specs/deleted.md" in removed_arg


# ─── Notification Helpers ───────────────────────────────


class TestNotifySpecStatusChange:
    """_notify_spec_status_change is best-effort and should never raise."""

    async def test_sends_notification_when_dispatcher_available(self):
        dispatcher = AsyncMock()
        with patch(
            "canon.github.handlers.on_push._get_notification_dispatcher",
            return_value=dispatcher,
        ):
            await _notify_spec_status_change(
                "My Spec", "draft", "in_progress", "dev", "https://github.com/x"
            )
            dispatcher.send_spec_status_change.assert_called_once_with(
                spec_title="My Spec",
                old_status="draft",
                new_status="in_progress",
                author="dev",
                github_url="https://github.com/x",
            )

    async def test_noop_when_no_dispatcher(self):
        with patch(
            "canon.github.handlers.on_push._get_notification_dispatcher",
            return_value=None,
        ):
            # Should not raise
            await _notify_spec_status_change(
                "My Spec", "draft", "in_progress", "dev", "https://github.com/x"
            )

    async def test_swallows_dispatcher_exception(self):
        dispatcher = AsyncMock()
        dispatcher.send_spec_status_change.side_effect = RuntimeError("Slack down")
        with patch(
            "canon.github.handlers.on_push._get_notification_dispatcher",
            return_value=dispatcher,
        ):
            # Should not raise even when dispatcher fails
            await _notify_spec_status_change(
                "My Spec", "draft", "in_progress", "dev", "https://github.com/x"
            )


class TestNotifyCoverageRegression:
    """_notify_coverage_regression is best-effort and should never raise."""

    async def test_sends_notification(self):
        dispatcher = AsyncMock()
        with patch(
            "canon.github.handlers.on_push._get_notification_dispatcher",
            return_value=dispatcher,
        ):
            await _notify_coverage_regression("My Spec", 60, 80, "https://github.com/x")
            dispatcher.send_coverage_regression.assert_called_once_with(
                spec_title="My Spec",
                coverage_pct=60,
                threshold=80,
                github_url="https://github.com/x",
            )

    async def test_noop_when_no_dispatcher(self):
        with patch(
            "canon.github.handlers.on_push._get_notification_dispatcher",
            return_value=None,
        ):
            await _notify_coverage_regression("My Spec", 60, 80, "https://github.com/x")

    async def test_swallows_exception(self):
        dispatcher = AsyncMock()
        dispatcher.send_coverage_regression.side_effect = RuntimeError("boom")
        with patch(
            "canon.github.handlers.on_push._get_notification_dispatcher",
            return_value=dispatcher,
        ):
            await _notify_coverage_regression("My Spec", 60, 80, "https://github.com/x")


# ─── _invalidate_web_cache ──────────────────────────────


class TestInvalidateWebCache:
    """_invalidate_web_cache invalidates multiple cache keys and never raises."""

    def test_invalidates_all_cache_keys(self):
        mock_cache = MagicMock()
        mock_app = MagicMock()
        mock_app.state.cache = mock_cache

        with (
            patch("canon.github.handlers.on_push.app", mock_app, create=True),
            patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}),
        ):
            _invalidate_web_cache("acme", "widgets")

        mock_cache.invalidate.assert_any_call("repo:acme/widgets")
        mock_cache.invalidate.assert_any_call("config:acme/widgets")
        mock_cache.invalidate_prefix.assert_any_call("spec:acme/widgets/")
        mock_cache.invalidate_prefix.assert_any_call("doc:acme/widgets/")
        mock_cache.invalidate_prefix.assert_any_call("org_overview:")
        mock_cache.invalidate_prefix.assert_any_call("search:")
        mock_cache.invalidate_prefix.assert_any_call("facets:")

    def test_no_crash_when_cache_unavailable(self):
        """Should not raise when canon.main is not importable."""
        with patch.dict("sys.modules", {"canon.main": None}):
            # Force ImportError by removing the module
            _invalidate_web_cache("acme", "widgets")


# ─── _index_specs ───────────────────────────────────────


class TestIndexSpecs:
    """_index_specs indexes changed specs and deletes removed ones."""

    async def test_indexes_parsed_specs(self):
        from canon.github.handlers.on_push import _index_specs

        mock_search_index = AsyncMock()
        mock_app = MagicMock()
        mock_app.state.search_index = mock_search_index
        mock_app.state.embed_client = None
        mock_app.state.opensearch_client = None

        mock_index_spec = AsyncMock()

        with (
            patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}),
            patch("canon.search.indexer.index_spec", mock_index_spec),
        ):
            doc1 = MagicMock()
            doc2 = MagicMock()
            parsed = {
                "docs/specs/a.md": doc1,
                "docs/specs/b.md": doc2,
            }
            await _index_specs("acme", "widgets", parsed, set(), "sha123")

            assert mock_index_spec.call_count == 2

    async def test_deletes_removed_specs(self):
        from canon.github.handlers.on_push import _index_specs

        mock_search_index = AsyncMock()
        mock_app = MagicMock()
        mock_app.state.search_index = mock_search_index
        mock_app.state.embed_client = None
        mock_app.state.opensearch_client = None

        with patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}):
            await _index_specs("acme", "widgets", {}, {"docs/specs/old.md"}, "sha123")

            mock_search_index.delete_spec.assert_called_once_with(
                "acme/widgets", "docs/specs/old.md"
            )

    async def test_no_crash_when_search_index_unavailable(self):
        from canon.github.handlers.on_push import _index_specs

        mock_app = MagicMock()
        mock_app.state.search_index = None

        with patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}):
            # Should not raise
            await _index_specs("acme", "widgets", {"a.md": MagicMock()}, set(), "sha")

    async def test_swallows_individual_index_errors(self):
        from canon.github.handlers.on_push import _index_specs

        mock_search_index = AsyncMock()
        mock_app = MagicMock()
        mock_app.state.search_index = mock_search_index
        mock_app.state.embed_client = None
        mock_app.state.opensearch_client = None

        mock_index_spec = AsyncMock(side_effect=RuntimeError("index failed"))

        with (
            patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}),
            patch("canon.search.indexer.index_spec", mock_index_spec),
        ):
            # Should not raise even when individual indexing fails
            await _index_specs("acme", "widgets", {"a.md": MagicMock()}, set(), "sha")


# ─── _cache_specs ───────────────────────────────────────


class TestCacheSpecs:
    """_cache_specs stores spec content in Postgres and handles removals."""

    async def test_caches_specs_with_content(self):
        from canon.github.handlers.on_push import _cache_specs

        mock_store = AsyncMock()
        AsyncMock()
        mock_app = MagicMock()
        mock_app.state.content_cache_store = mock_store
        mock_app.state.github_client = MagicMock()

        with (
            patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}),
            patch("canon.sync.content_sync.ContentSyncEngine") as MockEngine,
        ):
            engine_instance = AsyncMock()
            MockEngine.return_value = engine_instance

            parsed = {"docs/specs/a.md": MagicMock()}
            contents = {"docs/specs/a.md": ("# Spec A\ncontent", "file-sha-1")}
            await _cache_specs("acme", "widgets", parsed, contents, set())

            engine_instance.sync_spec.assert_called_once_with(
                "acme", "widgets", "docs/specs/a.md", "# Spec A\ncontent", commit_sha="file-sha-1"
            )

    async def test_deletes_removed_specs(self):
        from canon.github.handlers.on_push import _cache_specs

        mock_store = AsyncMock()
        mock_app = MagicMock()
        mock_app.state.content_cache_store = mock_store
        mock_app.state.github_client = MagicMock()

        with (
            patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}),
            patch("canon.sync.content_sync.ContentSyncEngine"),
        ):
            await _cache_specs("acme", "widgets", {}, {}, {"docs/specs/old.md"})

            mock_store.delete_spec.assert_called_once_with("acme/widgets", "docs/specs/old.md")

    async def test_skips_specs_without_raw_content(self):
        from canon.github.handlers.on_push import _cache_specs

        mock_store = AsyncMock()
        mock_app = MagicMock()
        mock_app.state.content_cache_store = mock_store
        mock_app.state.github_client = MagicMock()

        with (
            patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}),
            patch("canon.sync.content_sync.ContentSyncEngine") as MockEngine,
        ):
            engine_instance = AsyncMock()
            MockEngine.return_value = engine_instance

            parsed = {"docs/specs/a.md": MagicMock()}
            # Empty content dict — no raw content available
            contents: dict[str, tuple[str, str]] = {}
            await _cache_specs("acme", "widgets", parsed, contents, set())

            engine_instance.sync_spec.assert_not_called()

    async def test_no_crash_when_content_cache_unavailable(self):
        from canon.github.handlers.on_push import _cache_specs

        mock_app = MagicMock()
        mock_app.state.content_cache_store = None

        with patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}):
            await _cache_specs("acme", "widgets", {}, {}, set())

    async def test_updates_push_sync_timestamp_with_installation_id(self):
        from canon.github.handlers.on_push import _cache_specs

        mock_store = AsyncMock()
        mock_app = MagicMock()
        mock_app.state.content_cache_store = mock_store
        mock_app.state.github_client = MagicMock()

        with (
            patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}),
            patch("canon.sync.content_sync.ContentSyncEngine"),
        ):
            await _cache_specs("acme", "widgets", {}, {}, set(), installation_id=42)

            mock_store.upsert_sync_state.assert_called_once()
            call_args = mock_store.upsert_sync_state.call_args
            assert call_args.args[0] == "acme"
            assert call_args.args[1] == "widgets"
            assert call_args.args[2] == 42


# ─── _index_doc_files ──────────────────────────────────


class TestIndexDocFiles:
    """_index_doc_files indexes non-spec doc files matching configurable patterns."""

    async def test_indexes_doc_files_matching_patterns(self):
        from canon.github.handlers.on_push import _index_doc_files

        mock_search_index = AsyncMock()
        mock_app = MagicMock()
        mock_app.state.search_index = mock_search_index
        mock_app.state.embed_client = None
        mock_app.state.opensearch_client = None

        mock_index_spec = AsyncMock()

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("# Doc content", "sha"))

        with (
            patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}),
            patch("canon.search.indexer.index_spec", mock_index_spec),
            patch("canon.github.handlers.on_push.parse_spec") as mock_parse,
            patch("canon.github.handlers.on_push.filter_spec_files", return_value=[]),
            patch("canon.github.handlers.on_push.matches_doc_patterns", return_value=True),
        ):
            mock_parse.return_value = MagicMock(document=MagicMock())

            await _index_doc_files(
                client,
                "acme",
                "widgets",
                changed_files={"docs/rfcs/rfc-001.md"},
                removed_files=set(),
                doc_patterns=["docs/rfcs/**/*.md"],
                commit_sha="sha123",
            )

            mock_index_spec.assert_called_once()

    async def test_deletes_removed_doc_files(self):
        from canon.github.handlers.on_push import _index_doc_files

        mock_search_index = AsyncMock()
        mock_app = MagicMock()
        mock_app.state.search_index = mock_search_index
        mock_app.state.embed_client = None
        mock_app.state.opensearch_client = None

        client = AsyncMock()

        with (
            patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}),
            patch("canon.github.handlers.on_push.matches_doc_patterns", return_value=True),
        ):
            await _index_doc_files(
                client,
                "acme",
                "widgets",
                changed_files=set(),
                removed_files={"docs/rfcs/old.md"},
                doc_patterns=["docs/rfcs/**/*.md"],
                commit_sha="sha123",
            )

            mock_search_index.delete_spec.assert_called_once_with(
                "acme/widgets", "docs/rfcs/old.md"
            )

    async def test_no_crash_when_search_index_unavailable(self):
        from canon.github.handlers.on_push import _index_doc_files

        mock_app = MagicMock()
        mock_app.state.search_index = None

        client = AsyncMock()

        with patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}):
            await _index_doc_files(
                client,
                "acme",
                "widgets",
                changed_files={"docs/x.md"},
                removed_files=set(),
                doc_patterns=["docs/**/*.md"],
                commit_sha="sha",
            )

    async def test_skips_files_already_handled_as_specs(self):
        from canon.github.handlers.on_push import _index_doc_files

        mock_search_index = AsyncMock()
        mock_app = MagicMock()
        mock_app.state.search_index = mock_search_index
        mock_app.state.embed_client = None
        mock_app.state.opensearch_client = None

        mock_index_spec = AsyncMock()
        client = AsyncMock()

        with (
            patch.dict("sys.modules", {"canon.main": MagicMock(app=mock_app)}),
            patch("canon.search.indexer.index_spec", mock_index_spec),
            patch("canon.github.handlers.on_push.matches_doc_patterns", return_value=True),
            # filter_spec_files returns the file — meaning it IS a spec file
            patch(
                "canon.github.handlers.on_push.filter_spec_files",
                return_value=["docs/specs/feature.md"],
            ),
        ):
            await _index_doc_files(
                client,
                "acme",
                "widgets",
                changed_files={"docs/specs/feature.md"},
                removed_files=set(),
                doc_patterns=["docs/**/*.md"],
                commit_sha="sha",
            )

            # Should not index it as a doc file since it's already a spec
            mock_index_spec.assert_not_called()


# ─── _resolve_adapter ──────────────────────────────────


class TestResolveAdapter:
    """_resolve_adapter resolves ticket adapter from mapping config."""

    async def test_returns_none_when_no_project_key(self):
        from canon.github.handlers.on_push import _resolve_adapter
        from canon.sync.mapping import TicketMappingConfig

        mapping = TicketMappingConfig()
        doc = MagicMock()
        adapter, key, cfg = await _resolve_adapter(mapping, doc, "", "docs/specs/x.md")
        assert adapter is None
        assert key == ""
        assert cfg is None

    async def test_uses_create_adapter_fallback(self):
        from canon.github.handlers.on_push import _resolve_adapter
        from canon.sync.mapping import TicketMappingConfig

        mapping = TicketMappingConfig()
        doc = MagicMock()
        fake_adapter = _FakeAdapter()

        with patch("canon.github.handlers.on_push.create_adapter", return_value=fake_adapter):
            adapter, key, _cfg = await _resolve_adapter(mapping, doc, "PROJ", "docs/specs/x.md")
            assert adapter is fake_adapter
            assert key == "PROJ"

    async def test_returns_none_and_tracks_when_no_adapter_resolved(self):
        from canon.github.handlers.on_push import _resolve_adapter
        from canon.sync.mapping import TicketMappingConfig

        mapping = TicketMappingConfig()
        doc = MagicMock()

        with (
            patch("canon.github.handlers.on_push.create_adapter", return_value=None),
            patch("canon.github.handlers.on_push.analytics") as mock_analytics,
        ):
            adapter, _key, _cfg = await _resolve_adapter(mapping, doc, "PROJ", "docs/specs/x.md")
            assert adapter is None
            # Analytics event for failed resolution
            mock_analytics.track.assert_called_once()
            assert mock_analytics.track.call_args.args[0] == "sync_adapter_resolution_failed"


# ─── Orchestrator Integration ───────────────────────────


class TestOnPushOrchestrator:
    """End-to-end tests for the main on_push flow."""

    @pytest.fixture
    def _full_mock_deps(self):
        """Patch all external dependencies for orchestrator tests.
        Yields a dict of mocks for assertion."""
        parsed_doc = MagicMock()
        parsed_doc.frontmatter.ticket_project = "PROJ"
        parsed_doc.frontmatter.title = "Test Feature"
        parsed_doc.frontmatter.status = "in_progress"
        parsed_doc.frontmatter.owner = "dev"
        parsed_doc.frontmatter.team = "eng"
        parsed_doc.sections = []

        parse_result = MagicMock()
        parse_result.document = parsed_doc

        sync_result = _empty_sync_result()

        with (
            patch(
                "canon.github.handlers.on_push.load_repo_config", new_callable=AsyncMock
            ) as mock_cfg,
            patch("canon.github.handlers.on_push.parse_spec") as mock_parse,
            patch(
                "canon.github.handlers.on_push.load_org_mapping_config",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("canon.github.handlers.on_push.synthesize_mapping_config") as mock_synth,
            patch(
                "canon.github.handlers.on_push._resolve_adapter_multi", new_callable=AsyncMock
            ) as mock_resolve,
            patch(
                "canon.github.handlers.on_push.forward_sync", new_callable=AsyncMock
            ) as mock_forward,
            patch(
                "canon.github.handlers.on_push.forward_sync_multi", new_callable=AsyncMock
            ) as mock_forward_multi,
            patch(
                "canon.github.handlers.on_push._index_specs", new_callable=AsyncMock
            ) as mock_index,
            patch(
                "canon.github.handlers.on_push._cache_specs", new_callable=AsyncMock
            ) as mock_cache,
            patch(
                "canon.github.handlers.on_push._index_doc_files", new_callable=AsyncMock
            ) as mock_index_docs,
            patch(
                "canon.github.handlers.on_push._track_code_changes", new_callable=AsyncMock
            ) as mock_track,
            patch("canon.github.handlers.on_push._get_doc_patterns", return_value=[]),
            patch("canon.github.handlers.on_push._invalidate_web_cache") as mock_invalidate,
            patch("canon.github.handlers.on_push._get_notification_dispatcher", return_value=None),
            patch("canon.github.handlers.on_push.analytics") as mock_analytics,
        ):
            mock_cfg.return_value = CanonConfig()
            mock_parse.return_value = parse_result
            mock_synth.return_value = (MagicMock(), False)
            mock_resolve.return_value = (_FakeAdapter("jira"), "PROJ", MagicMock(), {})
            mock_forward.return_value = ("updated-markdown", sync_result)

            yield {
                "analytics": mock_analytics,
                "resolve_multi": mock_resolve,
                "forward": mock_forward,
                "forward_multi": mock_forward_multi,
                "index_specs": mock_index,
                "cache_specs": mock_cache,
                "index_docs": mock_index_docs,
                "track_code": mock_track,
                "invalidate_cache": mock_invalidate,
                "parse": mock_parse,
                "parsed_doc": parsed_doc,
                "sync_result": sync_result,
                "config": mock_cfg,
            }

    async def test_happy_path_single_spec(self, _full_mock_deps):
        """Single spec push: parse, sync, index, cache."""
        mocks = _full_mock_deps
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("spec content", "sha"))
        client.get_installation_token = AsyncMock(return_value="gh-token")

        payload = _make_push_payload(spec_files_modified=["docs/specs/feature.md"])
        await on_push(client, payload)

        # forward_sync was called (not forward_sync_multi — no shadow adapters)
        mocks["forward"].assert_called_once()
        mocks["forward_multi"].assert_not_called()

        # Index and cache called
        mocks["index_specs"].assert_called_once()
        mocks["cache_specs"].assert_called_once()

        # Cache invalidated
        mocks["invalidate_cache"].assert_called_once_with("acme", "widgets")

    async def test_uses_forward_sync_multi_when_shadow_adapters(self, _full_mock_deps):
        """When shadow adapters are present, forward_sync_multi is used."""
        mocks = _full_mock_deps
        shadow = {"linear": (_FakeAdapter("linear"), MagicMock())}
        mocks["resolve_multi"].return_value = (_FakeAdapter("jira"), "PROJ", MagicMock(), shadow)
        mocks["forward_multi"].return_value = ("markdown", _empty_sync_result())

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("spec content", "sha"))
        client.get_installation_token = AsyncMock(return_value="tok")

        payload = _make_push_payload(spec_files_modified=["docs/specs/feature.md"])
        await on_push(client, payload)

        mocks["forward_multi"].assert_called_once()
        mocks["forward"].assert_not_called()

    async def test_commits_updated_markdown_when_tickets_created(self, _full_mock_deps):
        """When forward_sync creates tickets, the updated markdown is committed."""
        mocks = _full_mock_deps
        sync_result = _empty_sync_result(
            created=[SyncCreated(section_id="1-auth", ticket_id="PROJ-1", ticket_url="http://x")]
        )
        mocks["forward"].return_value = ("updated-with-links", sync_result)

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("original", "sha-1"))
        client.get_installation_token = AsyncMock(return_value="tok")
        client.create_or_update_file = AsyncMock()

        payload = _make_push_payload(spec_files_modified=["docs/specs/auth.md"])
        await on_push(client, payload)

        client.create_or_update_file.assert_called_once()
        call_args = client.create_or_update_file.call_args
        assert call_args.args[2] == "docs/specs/auth.md"  # file path
        assert call_args.args[3] == "updated-with-links"  # new content
        assert "chore(canon):" in call_args.args[4]  # commit message
        assert call_args.args[5] == "sha-1"  # file sha

    async def test_does_not_commit_when_no_tickets_created(self, _full_mock_deps):
        """When no tickets are created, no commit is made."""
        mocks = _full_mock_deps
        mocks["forward"].return_value = ("same-markdown", _empty_sync_result())

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("content", "sha"))
        client.get_installation_token = AsyncMock(return_value="tok")
        client.create_or_update_file = AsyncMock()

        payload = _make_push_payload(spec_files_modified=["docs/specs/x.md"])
        await on_push(client, payload)

        client.create_or_update_file.assert_not_called()

    async def test_sync_error_triggers_notification(self, _full_mock_deps):
        """When forward_sync returns errors, a ticket_sync_failure notification fires."""
        mocks = _full_mock_deps
        sync_result = _empty_sync_result(
            errors=[SyncError(section_id="1", error="Jira API timeout")]
        )
        mocks["forward"].return_value = ("md", sync_result)

        dispatcher = AsyncMock()
        with patch(
            "canon.github.handlers.on_push._get_notification_dispatcher",
            return_value=dispatcher,
        ):
            client = AsyncMock()
            client.get_file_content = AsyncMock(return_value=("c", "s"))
            client.get_installation_token = AsyncMock(return_value="tok")

            payload = _make_push_payload(spec_files_modified=["docs/specs/x.md"])
            await on_push(client, payload)

            dispatcher.send_ticket_sync_failure.assert_called_once()
            call_kwargs = dispatcher.send_ticket_sync_failure.call_args.kwargs
            assert call_kwargs["system"] == "jira"
            assert "Jira API timeout" in call_kwargs["error"]

    async def test_individual_spec_error_does_not_halt_others(self, _full_mock_deps):
        """An exception on one spec file should not prevent others from syncing."""
        mocks = _full_mock_deps

        call_count = 0

        async def _get_file(owner, repo, path, ref=None):
            nonlocal call_count
            call_count += 1
            if "bad" in path:
                raise RuntimeError("file fetch failed")
            return ("content", "sha")

        client = AsyncMock()
        client.get_file_content = AsyncMock(side_effect=_get_file)
        client.get_installation_token = AsyncMock(return_value="tok")

        payload = _make_push_payload(
            spec_files_modified=["docs/specs/bad.md", "docs/specs/good.md"]
        )
        await on_push(client, payload)

        # Both files were attempted (good file also gets a prev-version fetch
        # for status-change detection, so call_count may be > 2)
        assert call_count >= 2
        # forward_sync still called for the good file
        mocks["forward"].assert_called_once()

    async def test_skips_adapter_when_resolution_returns_none(self, _full_mock_deps):
        """When adapter resolution returns None, the spec is skipped."""
        mocks = _full_mock_deps
        mocks["resolve_multi"].return_value = (None, None, None, {})

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("content", "sha"))
        client.get_installation_token = AsyncMock(return_value="tok")

        payload = _make_push_payload(spec_files_modified=["docs/specs/x.md"])
        await on_push(client, payload)

        mocks["forward"].assert_not_called()
        # But indexing still happens
        mocks["index_specs"].assert_called_once()

    async def test_doc_patterns_trigger_doc_indexing(self, _full_mock_deps):
        """When doc_patterns are configured, _index_doc_files is called."""
        mocks = _full_mock_deps

        with patch(
            "canon.github.handlers.on_push._get_doc_patterns",
            return_value=["docs/**/*.md"],
        ):
            client = AsyncMock()
            client.get_file_content = AsyncMock(return_value=("content", "sha"))
            client.get_installation_token = AsyncMock(return_value="tok")

            payload = _make_push_payload(spec_files_modified=["docs/specs/x.md"])
            await on_push(client, payload)

            mocks["index_docs"].assert_called_once()

    async def test_non_spec_changes_trigger_staleness_tracking(self, _full_mock_deps):
        """Non-spec file changes trigger _track_code_changes."""
        mocks = _full_mock_deps

        payload = _make_push_payload(
            spec_files_modified=["docs/specs/x.md"],
            non_spec_files=["src/main.py"],
        )

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("content", "sha"))
        client.get_installation_token = AsyncMock(return_value="tok")

        await on_push(client, payload)

        mocks["track_code"].assert_called_once()
        tracked_paths = mocks["track_code"].call_args.args[2]
        assert "src/main.py" in tracked_paths

    async def test_status_change_detection(self, _full_mock_deps):
        """When a spec's status changes between commits, notifications fire."""
        mocks = _full_mock_deps

        # Current parse returns in_progress
        current_doc = MagicMock()
        current_doc.frontmatter.ticket_project = "PROJ"
        current_doc.frontmatter.title = "Feature"
        current_doc.frontmatter.status = "in_progress"
        current_doc.frontmatter.owner = "dev"
        current_doc.frontmatter.team = "eng"
        current_doc.sections = []

        # Previous parse returns draft
        prev_doc = MagicMock()
        prev_doc.frontmatter.status = "draft"
        prev_doc.sections = []

        call_num = 0

        def _parse(content, opts):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return MagicMock(document=current_doc)
            return MagicMock(document=prev_doc)

        mocks["parse"].side_effect = _parse

        dispatcher = AsyncMock()
        with patch(
            "canon.github.handlers.on_push._get_notification_dispatcher",
            return_value=dispatcher,
        ):
            client = AsyncMock()
            client.get_file_content = AsyncMock(return_value=("content", "sha"))
            client.get_installation_token = AsyncMock(return_value="tok")

            payload = _make_push_payload(spec_files_modified=["docs/specs/feature.md"])
            await on_push(client, payload)

            dispatcher.send_spec_status_change.assert_called_once()
            call_kwargs = dispatcher.send_spec_status_change.call_args.kwargs
            assert call_kwargs["old_status"] == "draft"
            assert call_kwargs["new_status"] == "in_progress"

    async def test_added_spec_emits_spec_detected_event(self, _full_mock_deps):
        """Newly added spec files emit a spec_detected analytics event."""
        mocks = _full_mock_deps

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("content", "sha"))
        client.get_installation_token = AsyncMock(return_value="tok")

        payload = _make_push_payload(spec_files_added=["docs/specs/new-feature.md"])
        await on_push(client, payload)

        spec_detected_calls = [
            c for c in mocks["analytics"].track.call_args_list if c.args[0] == "spec_detected"
        ]
        assert len(spec_detected_calls) == 1
        props = spec_detected_calls[0].kwargs["properties"]
        assert props["spec_path"] == "docs/specs/new-feature.md"

    async def test_installation_id_passed_to_cache_specs(self, _full_mock_deps):
        """The client's installation_id is forwarded to _cache_specs."""
        mocks = _full_mock_deps

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("content", "sha"))
        client.get_installation_token = AsyncMock(return_value="tok")
        client.installation_id = 999

        payload = _make_push_payload(spec_files_modified=["docs/specs/x.md"])
        await on_push(client, payload)

        cache_call = mocks["cache_specs"].call_args
        assert cache_call.kwargs.get("installation_id") == 999
