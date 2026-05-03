"""Tests for the search indexer (flatten_sections, index_spec)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from canon.parser.models import (
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
    TicketLink,
)
from canon.search.indexer import flatten_sections, index_spec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_section(
    *,
    title: str = "Section",
    depth: int = 2,
    content: str = "Body text",
    state: str = "draft",
    ticket_id: str | None = None,
    children: list[SpecSection] | None = None,
) -> SpecSection:
    """Create a SpecSection with minimal required fields."""
    ticket_link = TicketLink(system="jira", ticket_id=ticket_id) if ticket_id else None
    return SpecSection(
        id="s1",
        section_number=None,
        title=title,
        depth=depth,
        content=content,
        ticket_link=ticket_link,
        status=SectionStatus(state=state),
        acceptance_criteria=[],
        children=children or [],
        start_line=1,
        end_line=10,
    )


def _make_doc(
    *,
    title: str = "Test Spec",
    status: str = "draft",
    sections: list[SpecSection] | None = None,
    file_path: str = "docs/specs/test.md",
) -> SpecDocument:
    """Create a SpecDocument with minimal required fields."""
    return SpecDocument(
        file_path=file_path,
        frontmatter=SpecFrontmatter(
            title=title,
            status=status,
            owner="eng",
            team="platform",
        ),
        sections=sections or [],
        raw="# Test Spec\nSome raw content",
    )


# ---------------------------------------------------------------------------
# TestFlattenSections
# ---------------------------------------------------------------------------


class TestFlattenSections:
    def test_empty_sections(self):
        assert flatten_sections([]) == []

    def test_flat_sections(self):
        sections = [
            _make_section(title="Phase 1", content="Do stuff", state="done"),
            _make_section(title="Phase 2", content="More stuff", state="todo"),
        ]
        result = flatten_sections(sections)

        assert len(result) == 2
        assert result[0]["heading"] == "Phase 1"
        assert result[0]["body"] == "Do stuff"
        assert result[0]["status"] == "done"
        assert result[0]["level"] == 2
        assert result[1]["heading"] == "Phase 2"
        assert result[1]["status"] == "todo"

    def test_nested_sections(self):
        child = _make_section(title="Sub-task", depth=3, content="Details")
        parent = _make_section(title="Parent", depth=2, content="Overview", children=[child])
        result = flatten_sections([parent])

        assert len(result) == 2
        assert result[0]["heading"] == "Parent"
        assert result[0]["level"] == 2
        assert result[1]["heading"] == "Sub-task"
        assert result[1]["level"] == 3

    def test_ticket_ref_formatting(self):
        section = _make_section(title="With Ticket", ticket_id="PROJ-123")
        result = flatten_sections([section])

        assert result[0]["ticket_ref"] == "PROJ-123"

    def test_no_ticket_ref(self):
        section = _make_section(title="No Ticket")
        result = flatten_sections([section])

        assert result[0]["ticket_ref"] == ""

    def test_status_extraction(self):
        section = _make_section(state="in_progress")
        result = flatten_sections([section])

        assert result[0]["status"] == "in_progress"

    def test_deeply_nested(self):
        grandchild = _make_section(title="GC", depth=4)
        child = _make_section(title="C", depth=3, children=[grandchild])
        parent = _make_section(title="P", depth=2, children=[child])
        result = flatten_sections([parent])

        assert len(result) == 3
        assert [r["heading"] for r in result] == ["P", "C", "GC"]


# ---------------------------------------------------------------------------
# TestIndexSpec
# ---------------------------------------------------------------------------


class TestIndexSpec:
    async def test_without_embeddings(self):
        """index_spec works with no embed_client (BM25-only)."""
        doc = _make_doc(sections=[_make_section(title="Auth", content="Login flow")])
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 42

        doc_id = await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
        )

        assert doc_id == 42
        mock_index.upsert_spec.assert_awaited_once()
        call_kwargs = mock_index.upsert_spec.call_args.kwargs
        assert call_kwargs["doc_embedding"] is None
        assert call_kwargs["sections"][0]["embedding"] is None

    async def test_with_embeddings(self):
        """index_spec computes embeddings when embed_client is available."""
        doc = _make_doc(sections=[_make_section(title="Auth", content="Login flow")])
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 42

        mock_embed = MagicMock()
        mock_embed.is_available = True
        # embed_documents receives [doc_text, section_text] → returns 2 embeddings
        mock_embed.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]

        doc_id = await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
            embed_client=mock_embed,
        )

        assert doc_id == 42
        mock_embed.embed_documents.assert_called_once()
        call_kwargs = mock_index.upsert_spec.call_args.kwargs
        assert call_kwargs["doc_embedding"] == [0.1, 0.2]
        assert call_kwargs["sections"][0]["embedding"] == [0.3, 0.4]

    async def test_embedding_failure_degrades(self):
        """If embeddings fail, upsert proceeds with None embeddings."""
        doc = _make_doc(sections=[_make_section()])
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 99

        mock_embed = MagicMock()
        mock_embed.is_available = True
        mock_embed.embed_documents.side_effect = RuntimeError("API down")

        doc_id = await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
            embed_client=mock_embed,
        )

        assert doc_id == 99
        call_kwargs = mock_index.upsert_spec.call_args.kwargs
        assert call_kwargs["doc_embedding"] is None
        assert call_kwargs["sections"][0]["embedding"] is None

    async def test_commit_sha_passthrough(self):
        """commit_sha is forwarded to upsert_spec."""
        doc = _make_doc(sections=[])
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 1

        await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
            commit_sha="deadbeef",
        )

        call_kwargs = mock_index.upsert_spec.call_args.kwargs
        assert call_kwargs["commit_sha"] == "deadbeef"

    async def test_empty_sections(self):
        """index_spec handles docs with no sections."""
        doc = _make_doc(sections=[])
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 5

        doc_id = await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
        )

        assert doc_id == 5


class TestOpenSearchDualWrite:
    async def test_dual_write_skipped_when_client_none(self):
        doc = _make_doc(sections=[_make_section()])
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 1
        await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
            opensearch_client=None,
        )
        # No assertions on opensearch — just confirm it doesn't blow up

    async def test_dual_write_skipped_when_client_disabled(self):
        doc = _make_doc(sections=[_make_section()])
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 1
        opensearch = MagicMock()
        opensearch.is_enabled = False
        opensearch.index_spec = AsyncMock()
        await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
            opensearch_client=opensearch,
        )
        opensearch.index_spec.assert_not_called()

    async def test_dual_write_indexes_spec_and_sections(self):
        doc = _make_doc(
            sections=[
                _make_section(title="Heading A", content="Body A"),
                _make_section(title="Heading B", content="Body B"),
            ]
        )
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 1

        opensearch = MagicMock()
        opensearch.is_enabled = True
        opensearch.index_spec = AsyncMock()
        opensearch.delete_sections_for_spec = AsyncMock()
        opensearch.index_sections = AsyncMock()

        await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
            opensearch_client=opensearch,
        )

        opensearch.index_spec.assert_awaited_once()
        spec_call = opensearch.index_spec.await_args
        assert spec_call.kwargs["doc_id"] == "org/repo:docs/specs/test.md"
        spec_doc = spec_call.kwargs["document"]
        assert spec_doc["repo"] == "org/repo"
        assert spec_doc["owner"] == "org"
        assert spec_doc["raw_markdown"] == "# Test Spec\nSome raw content"
        assert "content_hash" in spec_doc
        assert "synced_at" in spec_doc
        # No embedding was provided, so the materialised flag must be False.
        assert spec_doc["has_embedding"] is False
        assert "embedding" not in spec_doc

        opensearch.delete_sections_for_spec.assert_awaited_once_with("org/repo:docs/specs/test.md")
        opensearch.index_sections.assert_awaited_once()
        sections = opensearch.index_sections.await_args.args[0]
        assert len(sections) == 2
        assert sections[0]["id"] == "org/repo:docs/specs/test.md:0"
        assert sections[0]["_spec_doc_id"] == "org/repo:docs/specs/test.md"
        assert sections[0]["heading"] == "Heading A"
        assert sections[1]["id"] == "org/repo:docs/specs/test.md:1"

    async def test_dual_write_includes_embeddings(self):
        doc = _make_doc(sections=[_make_section(title="A", content="body")])
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 1

        embed = MagicMock()
        embed.is_available = True
        embed.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]

        opensearch = MagicMock()
        opensearch.is_enabled = True
        opensearch.index_spec = AsyncMock()
        opensearch.delete_sections_for_spec = AsyncMock()
        opensearch.index_sections = AsyncMock()

        await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
            embed_client=embed,
            opensearch_client=opensearch,
        )

        spec_doc = opensearch.index_spec.await_args.kwargs["document"]
        assert spec_doc["embedding"] == [0.1, 0.2]
        assert spec_doc["has_embedding"] is True
        section = opensearch.index_sections.await_args.args[0][0]
        assert section["embedding"] == [0.3, 0.4]

    async def test_postgres_commits_before_opensearch_call_order(self):
        """Postgres is source of truth; the OpenSearch dual-write must
        happen AFTER the Postgres upsert returns successfully. The
        section delete + bulk write must precede the spec-doc write so
        a section-write failure leaves the spec doc with its OLD
        content_hash (lets reconcile detect drift and retry)."""
        parent = MagicMock()
        mock_index = AsyncMock()
        mock_index.upsert_spec = AsyncMock(return_value=1)
        opensearch = MagicMock()
        opensearch.is_enabled = True
        opensearch.index_spec = AsyncMock()
        opensearch.delete_sections_for_spec = AsyncMock(return_value=True)
        opensearch.index_sections = AsyncMock(return_value=True)
        parent.attach_mock(mock_index.upsert_spec, "pg_upsert")
        parent.attach_mock(opensearch.index_spec, "os_index_spec")
        parent.attach_mock(opensearch.delete_sections_for_spec, "os_delete_sections")
        parent.attach_mock(opensearch.index_sections, "os_index_sections")

        await index_spec(
            doc=_make_doc(sections=[_make_section(title="A")]),
            repo="org/repo",
            search_index=mock_index,
            opensearch_client=opensearch,
        )

        names = [c[0] for c in parent.mock_calls]
        assert names == [
            "pg_upsert",
            "os_delete_sections",
            "os_index_sections",
            "os_index_spec",
        ]

    async def test_skips_spec_doc_write_when_sections_bulk_fails(self):
        """If the bulk section write fails, the spec doc — which carries
        the canonical content_hash — must NOT be updated. Otherwise the
        reconcile cron would see PG.hash == OS.hash and never retry,
        leaving the spec permanently invisible to hybrid search."""
        mock_index = AsyncMock()
        mock_index.upsert_spec = AsyncMock(return_value=1)
        opensearch = MagicMock()
        opensearch.is_enabled = True
        opensearch.index_spec = AsyncMock()
        opensearch.delete_sections_for_spec = AsyncMock(return_value=True)
        opensearch.index_sections = AsyncMock(return_value=False)  # bulk failed

        await index_spec(
            doc=_make_doc(sections=[_make_section(title="A")]),
            repo="org/repo",
            search_index=mock_index,
            opensearch_client=opensearch,
        )

        opensearch.index_spec.assert_not_called()

    async def test_skips_spec_doc_write_when_section_delete_fails(self):
        """Same gate applies if the section delete-by-query fails — old
        sections may linger for the same spec, but at least the OS spec
        doc retains its old hash so reconcile retries."""
        mock_index = AsyncMock()
        mock_index.upsert_spec = AsyncMock(return_value=1)
        opensearch = MagicMock()
        opensearch.is_enabled = True
        opensearch.index_spec = AsyncMock()
        opensearch.delete_sections_for_spec = AsyncMock(return_value=False)
        opensearch.index_sections = AsyncMock(return_value=True)

        await index_spec(
            doc=_make_doc(sections=[_make_section(title="A")]),
            repo="org/repo",
            search_index=mock_index,
            opensearch_client=opensearch,
        )

        opensearch.index_spec.assert_not_called()

    async def test_postgres_commits_even_when_opensearch_index_raises(self):
        """If OpenSearch index_spec raises (despite the client's normal
        swallowing), the exception escapes — but the Postgres upsert must
        already have committed. Pin that contract."""
        import pytest as _pytest

        mock_index = AsyncMock()
        mock_index.upsert_spec = AsyncMock(return_value=42)

        opensearch = MagicMock()
        opensearch.is_enabled = True
        opensearch.index_spec = AsyncMock(side_effect=RuntimeError("boom"))
        opensearch.delete_sections_for_spec = AsyncMock()
        opensearch.index_sections = AsyncMock()

        with _pytest.raises(RuntimeError):
            await index_spec(
                doc=_make_doc(sections=[_make_section()]),
                repo="org/repo",
                search_index=mock_index,
                opensearch_client=opensearch,
            )

        # The PG side committed before the OS error escaped — caller's
        # eventual-consistency expectations rely on this.
        mock_index.upsert_spec.assert_awaited_once()


class TestEmbedAvailability:
    async def test_embed_client_not_available(self):
        """If embed_client exists but is_available is False, skip embeddings."""
        doc = _make_doc(sections=[_make_section()])
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 10

        mock_embed = MagicMock()
        mock_embed.is_available = False

        doc_id = await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
            embed_client=mock_embed,
        )

        assert doc_id == 10
        mock_embed.embed_documents.assert_not_called()
        call_kwargs = mock_index.upsert_spec.call_args.kwargs
        assert call_kwargs["doc_embedding"] is None

    async def test_multiple_sections_batched(self):
        """All section texts are batched into a single embed_documents call."""
        sections = [
            _make_section(title="S1", content="Body 1"),
            _make_section(title="S2", content="Body 2"),
            _make_section(title="S3", content="Body 3"),
        ]
        doc = _make_doc(sections=sections)
        mock_index = AsyncMock()
        mock_index.upsert_spec.return_value = 20

        mock_embed = MagicMock()
        mock_embed.is_available = True
        # 1 doc + 3 sections = 4 embeddings
        mock_embed.embed_documents.return_value = [
            [0.1],
            [0.2],
            [0.3],
            [0.4],
        ]

        await index_spec(
            doc=doc,
            repo="org/repo",
            search_index=mock_index,
            embed_client=mock_embed,
        )

        # Should be called exactly once with 4 texts
        mock_embed.embed_documents.assert_called_once()
        texts = mock_embed.embed_documents.call_args[0][0]
        assert len(texts) == 4

        call_kwargs = mock_index.upsert_spec.call_args.kwargs
        assert len(call_kwargs["sections"]) == 3
        assert call_kwargs["sections"][0]["embedding"] == [0.2]
        assert call_kwargs["sections"][1]["embedding"] == [0.3]
        assert call_kwargs["sections"][2]["embedding"] == [0.4]
