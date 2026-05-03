"""Tests for ContentSyncEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from canon.sync.content_sync import ContentSyncEngine, SyncStats


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.upsert_spec = AsyncMock(return_value=1)
    store.upsert_config = AsyncMock()
    store.upsert_sync_state = AsyncMock()
    store.list_specs = AsyncMock(return_value=[])
    store.delete_spec = AsyncMock()
    return store


@pytest.fixture
def mock_github():
    gh = AsyncMock()
    gh.get_default_branch = AsyncMock(return_value="main")
    gh.get_file_content = AsyncMock(
        return_value=(
            "---\ntitle: Test\nstatus: draft\n---\n# Test\n## Section 1\nContent",
            "abc123",
        )
    )
    gh._get = AsyncMock(return_value={"tree": []})
    gh.for_installation = MagicMock(return_value=gh)
    gh.list_installation_repos = AsyncMock(return_value=[])
    return gh


@pytest.fixture
def engine(mock_store, mock_github):
    return ContentSyncEngine(mock_store, mock_github)


class TestSyncSpec:
    """Tests for single-file incremental sync."""

    @pytest.mark.asyncio
    async def test_sync_spec_upserts_to_store(self, engine, mock_store):
        raw = "---\ntitle: My Spec\nstatus: draft\nowner: ng\nteam: canon\n---\n# My Spec\n## 1. Section\n\nSome content\n"
        doc_id = await engine.sync_spec(
            "owner", "repo", "docs/specs/test.md", raw, commit_sha="abc"
        )

        assert doc_id == 1
        mock_store.upsert_spec.assert_called_once()
        call_kwargs = mock_store.upsert_spec.call_args
        assert call_kwargs.kwargs["title"] == "My Spec"
        assert call_kwargs.kwargs["github_sha"] == "abc"
        assert call_kwargs.kwargs["raw_markdown"] == raw

    @pytest.mark.asyncio
    async def test_sync_spec_includes_sections(self, engine, mock_store):
        raw = "---\ntitle: Test\nstatus: draft\nowner: ng\nteam: canon\n---\n# Test\n## 1. First\n\nBody one\n\n## 2. Second\n\nBody two\n"
        await engine.sync_spec("owner", "repo", "docs/specs/test.md", raw)

        call_kwargs = mock_store.upsert_spec.call_args
        sections = call_kwargs.kwargs["sections"]
        assert len(sections) >= 2
        # Parser strips section numbers from headings
        headings = [s["heading"] for s in sections]
        assert "First" in headings
        assert "Second" in headings


class TestSyncConfig:
    """Tests for CANON.yaml config sync."""

    @pytest.mark.asyncio
    async def test_sync_config_caches_yaml(self, engine, mock_store, mock_github):
        mock_github.get_file_content = AsyncMock(
            return_value=("specs:\n  patterns:\n    - docs/specs/*.md\n", "sha1")
        )
        await engine.sync_config("owner", "repo", 12345)

        mock_store.upsert_config.assert_called_once()
        args = mock_store.upsert_config.call_args
        assert args.kwargs["owner"] == "owner" or args[0][0] == "owner"

    @pytest.mark.asyncio
    async def test_sync_config_handles_missing(self, engine, mock_store, mock_github):
        mock_github.get_file_content = AsyncMock(side_effect=Exception("404"))
        await engine.sync_config("owner", "repo", 12345)
        mock_store.upsert_config.assert_not_called()


class TestSyncRepo:
    """Tests for full repo reconciliation."""

    @pytest.mark.asyncio
    async def test_sync_repo_fetches_changed_files(self, engine, mock_store, mock_github):
        # Git tree returns two spec files
        mock_github._get = AsyncMock(
            return_value={
                "tree": [
                    {"path": "docs/specs/a.md", "sha": "sha_a", "type": "blob"},
                    {"path": "docs/specs/b.md", "sha": "sha_b", "type": "blob"},
                    {"path": "README.md", "sha": "sha_r", "type": "blob"},
                    {"path": "docs/specs", "sha": "dir_sha", "type": "tree"},
                ]
            }
        )
        # No cached specs yet
        mock_store.list_specs = AsyncMock(return_value=[])
        mock_github.get_file_content = AsyncMock(
            return_value=(
                "---\ntitle: Test\nstatus: draft\nowner: ng\nteam: canon\n---\n# Test\n",
                "sha",
            )
        )

        stats = await engine.sync_repo("owner", "repo", 12345)

        assert stats.specs_synced == 2
        assert stats.specs_skipped == 0

    @pytest.mark.asyncio
    async def test_sync_repo_skips_unchanged(self, engine, mock_store, mock_github):
        mock_github._get = AsyncMock(
            return_value={
                "tree": [
                    {"path": "docs/specs/a.md", "sha": "sha_a", "type": "blob"},
                ]
            }
        )
        # Already cached with same SHA
        mock_store.list_specs = AsyncMock(
            return_value=[{"path": "docs/specs/a.md", "github_sha": "sha_a", "id": 1}]
        )

        stats = await engine.sync_repo("owner", "repo", 12345)

        assert stats.specs_synced == 0
        assert stats.specs_skipped == 1
        # get_file_content may be called for config sync, but NOT for spec files
        spec_fetch_calls = [
            c
            for c in mock_github.get_file_content.call_args_list
            if c.args[2].endswith(".md")  # only spec file fetches
        ]
        assert len(spec_fetch_calls) == 0

    @pytest.mark.asyncio
    async def test_sync_repo_deletes_removed_specs(self, engine, mock_store, mock_github):
        mock_github._get = AsyncMock(return_value={"tree": []})
        mock_store.list_specs = AsyncMock(
            return_value=[{"path": "docs/specs/old.md", "github_sha": "old_sha", "id": 1}]
        )

        stats = await engine.sync_repo("owner", "repo", 12345)

        assert stats.specs_deleted == 1
        mock_store.delete_spec.assert_called_once_with("owner/repo", "docs/specs/old.md")

    @pytest.mark.asyncio
    async def test_sync_repo_updates_sync_state(self, engine, mock_store, mock_github):
        mock_github._get = AsyncMock(return_value={"tree": []})
        mock_store.list_specs = AsyncMock(return_value=[])

        await engine.sync_repo("owner", "repo", 12345)

        # Should be called at least twice: once for "syncing", once for "synced"
        assert mock_store.upsert_sync_state.call_count >= 2

    @pytest.mark.asyncio
    async def test_sync_repo_handles_errors(self, engine, mock_store, mock_github):
        mock_github.get_default_branch = AsyncMock(side_effect=Exception("API down"))

        stats = await engine.sync_repo("owner", "repo", 12345)

        assert len(stats.errors) > 0
        # Should mark sync_status as error
        last_call = mock_store.upsert_sync_state.call_args
        assert last_call.kwargs.get("sync_status") == "error"


class TestReconcileAll:
    """Tests for multi-installation reconciliation."""

    @pytest.mark.asyncio
    async def test_reconcile_with_provided_repos(self, engine, mock_store, mock_github):
        mock_github._get = AsyncMock(return_value={"tree": []})
        mock_store.list_specs = AsyncMock(return_value=[])

        installations = [{"id": 1, "repos": [{"owner": "org", "name": "repo1"}]}]
        stats = await engine.reconcile_all(installations)

        assert isinstance(stats, SyncStats)

    @pytest.mark.asyncio
    async def test_reconcile_lists_repos_when_not_provided(self, engine, mock_store, mock_github):
        mock_github._get = AsyncMock(return_value={"tree": []})
        mock_store.list_specs = AsyncMock(return_value=[])
        mock_github.list_installation_repos = AsyncMock(
            return_value=[{"owner": {"login": "org"}, "name": "repo1"}]
        )

        installations = [{"id": 1}]
        await engine.reconcile_all(installations)

        mock_github.for_installation.assert_called()
