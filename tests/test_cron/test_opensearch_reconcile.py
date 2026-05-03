"""Tests for OpenSearch reconciliation cron."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canon.cron.opensearch_reconcile import _reconcile, run_opensearch_reconciliation


class TestRunOpenSearchReconciliation:
    async def test_skipped_when_flag_off(self):
        with patch("canon.cron.opensearch_reconcile.Settings") as MockSettings:
            MockSettings.return_value = MagicMock(
                opensearch_enabled=False,
                database_url="postgres://localhost/x",
            )
            result = await run_opensearch_reconciliation()
            assert result == {"skipped": True}

    async def test_exits_without_database(self):
        with patch("canon.cron.opensearch_reconcile.Settings") as MockSettings:
            MockSettings.return_value = MagicMock(
                opensearch_enabled=True,
                database_url="",
            )
            with pytest.raises(RuntimeError, match="DATABASE_URL"):
                await run_opensearch_reconciliation()


class TestReconcileDiff:
    @staticmethod
    def _store_with(specs: list[dict]) -> MagicMock:
        store = MagicMock()
        store.list_all_spec_hashes = AsyncMock(return_value=specs)
        store.get_spec_raw = AsyncMock(return_value="# raw markdown\nbody")
        return store

    @staticmethod
    def _opensearch_with(hashes: dict[str, str]) -> MagicMock:
        os_client = MagicMock()
        os_client.list_spec_hashes = AsyncMock(return_value=hashes)
        os_client.delete_spec = AsyncMock()
        os_client.index_spec = AsyncMock()
        os_client.index_sections = AsyncMock()
        os_client.delete_sections_for_spec = AsyncMock()
        os_client.is_enabled = True
        return os_client

    async def test_reindexes_mismatched_hash(self):
        pg_specs = [{"repo": "org/r", "path": "specs/a.md", "content_hash": "new"}]
        store = self._store_with(pg_specs)
        opensearch = self._opensearch_with({"org/r:specs/a.md": "old"})

        result = await _reconcile(store, opensearch, embed_client=None)

        assert result["reindexed"] == 1
        assert result["deleted"] == 0
        assert opensearch.index_spec.await_count == 1

    async def test_skips_matching_hash(self):
        pg_specs = [{"repo": "org/r", "path": "specs/a.md", "content_hash": "same"}]
        store = self._store_with(pg_specs)
        opensearch = self._opensearch_with({"org/r:specs/a.md": "same"})

        result = await _reconcile(store, opensearch, embed_client=None)

        assert result["reindexed"] == 0
        assert result["deleted"] == 0
        opensearch.index_spec.assert_not_called()

    async def test_deletes_orphans_in_opensearch(self):
        store = self._store_with([])  # nothing in PG
        opensearch = self._opensearch_with({"org/r:specs/gone.md": "any"})

        result = await _reconcile(store, opensearch, embed_client=None)

        assert result["deleted"] == 1
        opensearch.delete_spec.assert_awaited_once_with("org/r:specs/gone.md")

    async def test_indexes_specs_missing_from_opensearch(self):
        pg_specs = [{"repo": "org/r", "path": "specs/new.md", "content_hash": "h1"}]
        store = self._store_with(pg_specs)
        opensearch = self._opensearch_with({})  # empty

        result = await _reconcile(store, opensearch, embed_client=None)

        assert result["reindexed"] == 1
        opensearch.index_spec.assert_awaited_once()

    async def test_missing_raw_counts_as_error_not_reindexed(self):
        """Specs whose raw_markdown is unexpectedly None must NOT be counted
        as reindexed (the cron would otherwise loop forever on the same hash
        mismatch with no alert) AND must surface in `errors` so existing
        threshold alerts catch persistent occurrences."""
        pg_specs = [
            {"repo": "org/r", "path": "specs/a.md", "content_hash": "h1"},
            {"repo": "org/r", "path": "specs/b.md", "content_hash": "h2"},
        ]
        store = self._store_with(pg_specs)
        # First spec fails to fetch raw, second succeeds
        store.get_spec_raw = AsyncMock(side_effect=[None, "# raw"])
        opensearch = self._opensearch_with({})

        result = await _reconcile(store, opensearch, embed_client=None)

        # Only the spec that actually got reindexed counts toward `reindexed`;
        # the missing-raw case folds into `errors`.
        assert result["reindexed"] == 1
        assert result["errors"] == 1

    async def test_errors_count_when_reindex_raises_mid_loop(self):
        """Regression: if _reindex_spec raises (vs returns False), the loop
        must continue to the next spec and the failure must be reflected in
        `errors`. The original test that covered this branch was repurposed
        into the missing-raw case above; this re-pins the raise path."""
        pg_specs = [
            {"repo": "org/r", "path": "specs/a.md", "content_hash": "h1"},
            {"repo": "org/r", "path": "specs/b.md", "content_hash": "h2"},
        ]
        store = self._store_with(pg_specs)
        store.get_spec_raw = AsyncMock(side_effect=[RuntimeError("connection reset"), "# raw"])
        opensearch = self._opensearch_with({})

        result = await _reconcile(store, opensearch, embed_client=None)

        assert result["reindexed"] == 1
        assert result["errors"] == 1

    async def test_aborts_when_list_spec_hashes_raises(self):
        """Regression: a partial OpenSearch view (e.g. transient scroll
        failure) must NOT cause mass-delete of valid OS docs. The reconcile
        function should propagate the exception so @tracked_cron records
        a failed run instead of computing orphans against incomplete data."""
        import pytest as _pytest

        store = self._store_with([{"repo": "org/r", "path": "a.md", "content_hash": "h"}])
        opensearch = self._opensearch_with({})
        opensearch.list_spec_hashes = AsyncMock(side_effect=RuntimeError("scroll context expired"))

        with _pytest.raises(RuntimeError):
            await _reconcile(store, opensearch, embed_client=None)

        # Critical: must NOT have called delete_spec on anything.
        opensearch.delete_spec.assert_not_called()
