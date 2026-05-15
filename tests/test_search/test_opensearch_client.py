"""Tests for the OpenSearch client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from canon.search.opensearch_client import (
    SECTIONS_MAPPING,
    SPECS_MAPPING,
    OpenSearchClient,
    build_client_from_settings,
)


def _client_with_mock() -> tuple[OpenSearchClient, MagicMock]:
    """Construct an OpenSearchClient and inject a mock opensearch-py client."""
    client = OpenSearchClient(url="http://localhost:9200", enabled=True)
    mock = MagicMock()
    mock.ping = AsyncMock(return_value=True)
    mock.index = AsyncMock(return_value={"result": "created"})
    mock.bulk = AsyncMock(return_value={"errors": False, "items": []})
    mock.delete = AsyncMock(return_value={"result": "deleted"})
    mock.delete_by_query = AsyncMock(return_value={"deleted": 0})
    mock.close = AsyncMock(return_value=None)

    indices = MagicMock()
    indices.exists = AsyncMock(return_value=False)
    indices.create = AsyncMock(return_value={"acknowledged": True})
    mock.indices = indices

    client._client = mock
    client._enabled = True
    return client, mock


class TestEnablement:
    def test_disabled_when_flag_off(self):
        client = OpenSearchClient(url="http://localhost:9200", enabled=False)
        assert client.is_enabled is False

    def test_disabled_without_url(self):
        client = OpenSearchClient(url="", enabled=True)
        assert client.is_enabled is False

    def test_enabled_when_configured_with_mock(self):
        client, _ = _client_with_mock()
        assert client.is_enabled is True


class TestNoOpWhenDisabled:
    @pytest.mark.asyncio
    async def test_ensure_indexes_no_op(self):
        client = OpenSearchClient(enabled=False)
        await client.ensure_indexes()  # should not raise

    @pytest.mark.asyncio
    async def test_index_spec_no_op(self):
        client = OpenSearchClient(enabled=False)
        await client.index_spec(doc_id="x", document={"foo": "bar"})

    @pytest.mark.asyncio
    async def test_index_sections_no_op(self):
        client = OpenSearchClient(enabled=False)
        await client.index_sections([{"id": 1, "body": "hi"}])

    @pytest.mark.asyncio
    async def test_delete_spec_no_op(self):
        client = OpenSearchClient(enabled=False)
        await client.delete_spec("x")

    @pytest.mark.asyncio
    async def test_bulk_index_no_op(self):
        client = OpenSearchClient(enabled=False)
        await client.bulk_index([{"index": {"_index": "x"}}, {"foo": "bar"}])

    @pytest.mark.asyncio
    async def test_ping_returns_false_when_disabled(self):
        client = OpenSearchClient(enabled=False)
        assert await client.ping() is False


class TestEnsureIndexes:
    @pytest.mark.asyncio
    async def test_creates_both_indexes_when_missing(self):
        client, mock = _client_with_mock()
        await client.ensure_indexes()
        assert mock.indices.create.await_count == 2
        created_names = {call.kwargs["index"] for call in mock.indices.create.await_args_list}
        assert created_names == {"canon-specs", "canon-sections"}

    @pytest.mark.asyncio
    async def test_skips_existing_indexes(self):
        client, mock = _client_with_mock()
        mock.indices.exists = AsyncMock(return_value=True)
        await client.ensure_indexes()
        mock.indices.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_specs_with_knn_mapping(self):
        client, mock = _client_with_mock()
        await client.ensure_indexes()
        specs_call = next(
            c for c in mock.indices.create.await_args_list if c.kwargs["index"] == "canon-specs"
        )
        body = specs_call.kwargs["body"]
        assert body["mappings"] == SPECS_MAPPING
        assert body["settings"]["index"]["knn"] is True

    @pytest.mark.asyncio
    async def test_creates_sections_with_knn_mapping(self):
        client, mock = _client_with_mock()
        await client.ensure_indexes()
        sections_call = next(
            c for c in mock.indices.create.await_args_list if c.kwargs["index"] == "canon-sections"
        )
        assert sections_call.kwargs["body"]["mappings"] == SECTIONS_MAPPING

    @pytest.mark.asyncio
    async def test_swallows_create_errors(self):
        client, mock = _client_with_mock()
        mock.indices.create = AsyncMock(side_effect=RuntimeError("boom"))
        await client.ensure_indexes()  # must not raise


class TestIndexSpec:
    @pytest.mark.asyncio
    async def test_calls_index_with_document(self):
        client, mock = _client_with_mock()
        await client.index_spec(doc_id="repo/path", document={"title": "T"})
        mock.index.assert_awaited_once()
        kwargs = mock.index.await_args.kwargs
        assert kwargs["index"] == "canon-specs"
        assert kwargs["id"] == "repo/path"
        assert kwargs["body"] == {"title": "T"}

    @pytest.mark.asyncio
    async def test_swallows_index_errors(self):
        client, mock = _client_with_mock()
        mock.index = AsyncMock(side_effect=RuntimeError("boom"))
        await client.index_spec(doc_id="x", document={})


class TestIndexSections:
    @pytest.mark.asyncio
    async def test_bulk_indexes_sections(self):
        client, mock = _client_with_mock()
        sections = [
            {"id": 1, "spec_path": "a.md", "heading": "H1"},
            {"id": 2, "spec_path": "a.md", "heading": "H2"},
        ]
        await client.index_sections(sections)
        mock.bulk.assert_awaited_once()
        body = mock.bulk.await_args.kwargs["body"]
        # Two action/doc pairs = 4 entries; pin BOTH pairs so an off-by-one
        # in the action/doc interleave can't slip through with N>1 sections.
        assert len(body) == 4
        assert body[0] == {"index": {"_index": "canon-sections", "_id": 1}}
        assert body[1] == {"spec_path": "a.md", "heading": "H1"}
        assert body[2] == {"index": {"_index": "canon-sections", "_id": 2}}
        assert body[3] == {"spec_path": "a.md", "heading": "H2"}

    @pytest.mark.asyncio
    async def test_returns_false_on_per_item_error(self):
        """OpenSearch _bulk returns HTTP 200 with `{"errors": true, ...}`
        on partial failure. Without inspecting the flag, the indexer would
        update the spec doc's content_hash, leave missing sections behind,
        and the reconcile cron would never recover (matched hashes)."""
        client, mock = _client_with_mock()
        mock.bulk = AsyncMock(
            return_value={
                "errors": True,
                "items": [
                    {"index": {"_id": "1", "status": 201}},  # ok
                    {
                        "index": {
                            "_id": "2",
                            "status": 400,
                            "error": {"type": "mapper_parsing_exception"},
                        }
                    },
                ],
            }
        )
        ok = await client.index_sections([{"id": 1, "body": "a"}, {"id": 2, "body": "b"}])
        assert ok is False

    @pytest.mark.asyncio
    async def test_returns_true_when_no_item_errors(self):
        client, mock = _client_with_mock()
        mock.bulk = AsyncMock(return_value={"errors": False, "items": [{"index": {"status": 201}}]})
        assert await client.index_sections([{"id": 1, "body": "a"}]) is True

    @pytest.mark.asyncio
    async def test_skips_sections_without_id(self):
        client, mock = _client_with_mock()
        await client.index_sections([{"spec_path": "no-id.md"}])
        mock.bulk.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_list_no_op(self):
        client, mock = _client_with_mock()
        await client.index_sections([])
        mock.bulk.assert_not_called()


class TestDeleteSpec:
    @pytest.mark.asyncio
    async def test_deletes_spec_and_sections(self):
        client, mock = _client_with_mock()
        await client.delete_spec("repo/path")
        mock.delete.assert_awaited_once()
        mock.delete_by_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_delete_errors(self):
        client, mock = _client_with_mock()
        mock.delete = AsyncMock(side_effect=RuntimeError("boom"))
        mock.delete_by_query = AsyncMock(side_effect=RuntimeError("boom"))
        await client.delete_spec("x")  # must not raise


class TestDeleteRepo:
    @pytest.mark.asyncio
    async def test_deletes_specs_and_sections_with_correct_field_per_index(self):
        """specs index uses field=`repo`; sections index uses `spec_repo`.
        A regression in the field-switch would silently leak tenant data."""
        client, mock = _client_with_mock()
        await client.delete_repo("o/r")

        assert mock.delete_by_query.await_count == 2
        calls_by_index = {
            call.kwargs["index"]: call.kwargs["body"]["query"]["term"]
            for call in mock.delete_by_query.await_args_list
        }
        assert calls_by_index["canon-specs"] == {"repo": "o/r"}
        assert calls_by_index["canon-sections"] == {"spec_repo": "o/r"}

    @pytest.mark.asyncio
    async def test_no_op_when_disabled(self):
        client = OpenSearchClient(enabled=False)
        await client.delete_repo("o/r")  # must not raise

    @pytest.mark.asyncio
    async def test_swallows_per_index_errors_independently(self):
        """One index failing must not prevent the other from being attempted."""
        client, mock = _client_with_mock()
        mock.delete_by_query = AsyncMock(
            side_effect=[RuntimeError("specs index down"), {"deleted": 5}]
        )
        await client.delete_repo("o/r")
        # Both attempts ran even though the first raised.
        assert mock.delete_by_query.await_count == 2


class TestPing:
    @pytest.mark.asyncio
    async def test_returns_true_when_cluster_responds(self):
        client, _ = _client_with_mock()
        assert await client.ping() is True

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        client, mock = _client_with_mock()
        mock.ping = AsyncMock(side_effect=RuntimeError("boom"))
        assert await client.ping() is False


class TestBuildClientFromSettings:
    def test_unwraps_secret_str(self, monkeypatch):
        """The unwrapped password must reach the AsyncOpenSearch http_auth
        kwarg — without this assertion, dropping `get_secret_value()` would
        pass a SecretStr object through and the test would still go green."""
        from pydantic import SecretStr

        captured: dict[str, object] = {}

        class _FakeAsync:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        # Ship a stub opensearchpy module so the constructor's lazy import
        # finds it without requiring the cloud extra in test envs.
        import sys
        import types

        stub = types.ModuleType("opensearchpy")
        stub.AsyncOpenSearch = _FakeAsync
        monkeypatch.setitem(sys.modules, "opensearchpy", stub)

        settings = MagicMock()
        settings.opensearch_url = "http://localhost:9200"
        settings.opensearch_username = "admin"
        settings.opensearch_password = SecretStr("s3cret")
        settings.opensearch_specs_index = "canon-specs"
        settings.opensearch_sections_index = "canon-sections"
        settings.opensearch_enabled = True

        client = build_client_from_settings(settings)
        assert client.is_enabled is True
        assert captured["http_auth"] == ("admin", "s3cret")

    def test_handles_string_password(self):
        settings = MagicMock()
        settings.opensearch_url = ""
        settings.opensearch_username = ""
        settings.opensearch_password = ""
        settings.opensearch_specs_index = "canon-specs"
        settings.opensearch_sections_index = "canon-sections"
        settings.opensearch_enabled = False
        client = build_client_from_settings(settings)
        assert client.is_enabled is False


class TestListSpecHashes:
    @pytest.mark.asyncio
    async def test_raises_on_scroll_failure_mid_iteration(self):
        """Regression: scroll() failure must propagate so the reconcile cron
        aborts instead of computing orphans against a truncated view (which
        would mass-delete valid OpenSearch documents)."""
        client, mock = _client_with_mock()
        mock.search = AsyncMock(
            return_value={
                "_scroll_id": "scroll-abc",
                "hits": {"hits": [{"_id": "o/r:a.md", "_source": {"content_hash": "h1"}}]},
            }
        )
        mock.scroll = AsyncMock(side_effect=RuntimeError("network reset"))
        mock.clear_scroll = AsyncMock()

        with pytest.raises(RuntimeError):
            await client.list_spec_hashes()
        # The leaked context must still be cleared even when the call raises.
        mock.clear_scroll.assert_awaited_once_with(scroll_id="scroll-abc")

    @pytest.mark.asyncio
    async def test_paginates_across_multiple_scroll_pages(self):
        """Multi-page iteration: first page returns hits + scroll_id, second
        page returns more hits, third page returns empty hits which ends the
        loop. Confirms pagination works beyond the initial size=1000 batch."""
        client, mock = _client_with_mock()
        page1 = {
            "_scroll_id": "scroll-1",
            "hits": {"hits": [{"_id": "o/r:a.md", "_source": {"content_hash": "h1"}}]},
        }
        page2 = {
            "_scroll_id": "scroll-2",
            "hits": {"hits": [{"_id": "o/r:b.md", "_source": {"content_hash": "h2"}}]},
        }
        page3 = {"_scroll_id": "scroll-3", "hits": {"hits": []}}
        mock.search = AsyncMock(return_value=page1)
        mock.scroll = AsyncMock(side_effect=[page2, page3])
        mock.clear_scroll = AsyncMock()

        result = await client.list_spec_hashes()
        assert result == {"o/r:a.md": "h1", "o/r:b.md": "h2"}
        # Final scroll_id (from the empty page) is what gets cleared.
        mock.clear_scroll.assert_awaited_once_with(scroll_id="scroll-3")

    @pytest.mark.asyncio
    async def test_returns_empty_when_disabled(self):
        client = OpenSearchClient(enabled=False)
        assert await client.list_spec_hashes() == {}

    @pytest.mark.asyncio
    async def test_single_page_no_scroll(self):
        """A single page with no scroll_id ends the loop immediately."""
        client, mock = _client_with_mock()
        mock.search = AsyncMock(
            return_value={
                "hits": {"hits": [{"_id": "o/r:a.md", "_source": {"content_hash": "h1"}}]},
            }
        )
        result = await client.list_spec_hashes()
        assert result == {"o/r:a.md": "h1"}
        mock.scroll.assert_not_called()

    @pytest.mark.asyncio
    async def test_filters_by_repo_when_provided(self):
        client, mock = _client_with_mock()
        mock.search = AsyncMock(return_value={"hits": {"hits": []}})
        await client.list_spec_hashes(repo="org/r")
        body = mock.search.await_args.kwargs["body"]
        assert body["query"] == {"term": {"repo": "org/r"}}

    @pytest.mark.asyncio
    async def test_uses_match_all_when_no_repo(self):
        client, mock = _client_with_mock()
        mock.search = AsyncMock(return_value={"hits": {"hits": []}})
        await client.list_spec_hashes()
        body = mock.search.await_args.kwargs["body"]
        assert body["query"] == {"match_all": {}}


class TestClose:
    @pytest.mark.asyncio
    async def test_close_calls_underlying_client(self):
        client, mock = _client_with_mock()
        await client.close()
        mock.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_no_op_when_no_client(self):
        client = OpenSearchClient(enabled=False)
        await client.close()  # should not raise

    @pytest.mark.asyncio
    async def test_close_swallows_errors(self):
        client, mock = _client_with_mock()
        mock.close = AsyncMock(side_effect=RuntimeError("transport gone"))
        await client.close()  # should not raise


class TestDeleteSectionsForSpec:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        client, mock = _client_with_mock()
        result = await client.delete_sections_for_spec("org/r:p.md")
        assert result is True
        mock.delete_by_query.assert_awaited_once()
        kwargs = mock.delete_by_query.await_args.kwargs
        assert kwargs["index"] == "canon-sections"
        assert kwargs["body"]["query"]["term"]["_spec_doc_id"] == "org/r:p.md"

    @pytest.mark.asyncio
    async def test_returns_true_when_disabled(self):
        client = OpenSearchClient(enabled=False)
        assert await client.delete_sections_for_spec("x") is True

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        client, mock = _client_with_mock()
        mock.delete_by_query = AsyncMock(side_effect=RuntimeError("boom"))
        assert await client.delete_sections_for_spec("x") is False


class TestBulkIndex:
    @pytest.mark.asyncio
    async def test_calls_bulk_with_actions(self):
        client, mock = _client_with_mock()
        actions = [
            {"index": {"_index": "canon-specs", "_id": "1"}},
            {"title": "Test"},
        ]
        await client.bulk_index(actions)
        mock.bulk.assert_awaited_once()
        assert mock.bulk.await_args.kwargs["body"] == actions

    @pytest.mark.asyncio
    async def test_swallows_bulk_errors(self):
        client, mock = _client_with_mock()
        mock.bulk = AsyncMock(side_effect=RuntimeError("cluster down"))
        await client.bulk_index([{"index": {"_index": "x"}}, {"a": 1}])

    @pytest.mark.asyncio
    async def test_logs_item_errors(self):
        """When bulk returns errors=True, logs but does not raise."""
        client, mock = _client_with_mock()
        mock.bulk = AsyncMock(
            return_value={
                "errors": True,
                "items": [{"index": {"_id": "1", "error": {"type": "error"}}}],
            }
        )
        # Should not raise
        await client.bulk_index([{"index": {"_index": "x", "_id": "1"}}, {"a": 1}])

    @pytest.mark.asyncio
    async def test_empty_actions_no_op(self):
        client, mock = _client_with_mock()
        await client.bulk_index([])
        mock.bulk.assert_not_called()


class TestEnsureIndexEdgeCases:
    @pytest.mark.asyncio
    async def test_swallows_exists_check_error(self):
        """If indices.exists raises, the index creation is skipped."""
        client, mock = _client_with_mock()
        mock.indices.exists = AsyncMock(side_effect=RuntimeError("cluster unreachable"))
        await client.ensure_indexes()  # should not raise
        mock.indices.create.assert_not_called()


class TestProperties:
    def test_specs_index_name(self):
        client = OpenSearchClient(specs_index="my-specs", enabled=False)
        assert client.specs_index == "my-specs"

    def test_sections_index_name(self):
        client = OpenSearchClient(sections_index="my-sections", enabled=False)
        assert client.sections_index == "my-sections"


class TestBuildClientFromSettingsWarning:
    def test_warns_when_enabled_but_no_url(self, caplog):
        """Operator-visible warning when flag is on but URL is empty."""
        import logging

        settings = MagicMock()
        settings.opensearch_url = ""
        settings.opensearch_username = ""
        settings.opensearch_password = ""
        settings.opensearch_specs_index = "canon-specs"
        settings.opensearch_sections_index = "canon-sections"
        settings.opensearch_enabled = True

        with caplog.at_level(logging.WARNING, logger="canon.search.opensearch_client"):
            client = build_client_from_settings(settings)
        assert client.is_enabled is False
        assert any(
            "OPENSEARCH_ENABLED=true but OPENSEARCH_URL is empty" in r.message
            for r in caplog.records
        )
