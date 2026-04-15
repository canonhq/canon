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
        call_kwargs = mock_index.upsert_spec.call_args.kwargs
        assert call_kwargs["sections"] == []

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
