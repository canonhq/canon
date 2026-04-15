"""Tests for on_pull_request handler — search query building and context doc retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canon.github.handlers.on_pull_request import (
    _build_search_query,
    _load_context_docs_fallback,
    _retrieve_context_docs,
)

# ─── _build_search_query ────────────────────────────────


class TestBuildSearchQuery:
    def test_basic(self):
        pr = {"title": "Add auth flow", "body": "Implements OAuth login"}
        files = [
            {"filename": "src/auth.py"},
            {"filename": "tests/test_auth.py"},
        ]
        query = _build_search_query(pr, files)
        assert "Add auth flow" in query
        assert "Implements OAuth login" in query
        assert "src/auth.py" in query

    def test_caps_length(self):
        pr = {"title": "A" * 300, "body": "B" * 300}
        files = [{"filename": f"src/file{i}.py"} for i in range(50)]
        query = _build_search_query(pr, files)
        assert len(query) <= 500

    def test_excludes_config_files(self):
        pr = {"title": "Update config", "body": None}
        files = [
            {"filename": ".github/workflows/ci.yml"},
            {"filename": "src/auth.py"},
        ]
        query = _build_search_query(pr, files)
        assert "ci.yml" not in query
        assert "src/auth.py" in query

    def test_handles_none_body(self):
        pr = {"title": "Fix bug", "body": None}
        files = []
        query = _build_search_query(pr, files)
        assert query == "Fix bug"


# ─── _retrieve_context_docs ─────────────────────────────


@dataclass
class FakeSearchResult:
    section_id: int
    document_id: int
    repo: str
    path: str
    doc_title: str
    heading: str
    body: str
    status: str
    rrf_score: float


class TestRetrieveContextDocs:
    @pytest.mark.asyncio
    async def test_filters_spec_paths(self):
        results = [
            FakeSearchResult(
                1, 1, "org/repo", "docs/specs/auth.md", "Auth", "Login", "content", "done", 0.9
            ),
            FakeSearchResult(
                2,
                2,
                "org/repo",
                "docs/adrs/0001.md",
                "ADR 1",
                "Decision",
                "adr content",
                "done",
                0.8,
            ),
        ]
        search_index = MagicMock()
        search_index.hybrid_search = AsyncMock(return_value=results)

        docs = await _retrieve_context_docs(
            search_index,
            None,
            "auth flow",
            "org/repo",
            spec_paths={"docs/specs/auth.md"},
        )
        assert len(docs) == 1
        assert docs[0].path == "docs/adrs/0001.md"

    @pytest.mark.asyncio
    async def test_respects_char_budget(self):
        results = [
            FakeSearchResult(
                i,
                i,
                "org/repo",
                f"docs/adr{i}.md",
                f"ADR {i}",
                f"Section {i}",
                "x" * 3000,
                "done",
                0.9 - i * 0.1,
            )
            for i in range(5)
        ]
        search_index = MagicMock()
        search_index.hybrid_search = AsyncMock(return_value=results)

        docs = await _retrieve_context_docs(
            search_index,
            None,
            "query",
            "org/repo",
            spec_paths=set(),
            max_chars=8000,
        )
        total_chars = sum(len(d.body) for d in docs)
        assert total_chars <= 8000
        # Should have included 2 docs (3000 * 2 = 6000 <= 8000, 3000 * 3 = 9000 > 8000)
        assert len(docs) == 2

    @pytest.mark.asyncio
    async def test_deduplicates(self):
        results = [
            FakeSearchResult(
                1, 1, "org/repo", "docs/guide.md", "Guide", "Setup", "setup content", "done", 0.9
            ),
            FakeSearchResult(
                2, 1, "org/repo", "docs/guide.md", "Guide", "Setup", "setup content", "done", 0.7
            ),
        ]
        search_index = MagicMock()
        search_index.hybrid_search = AsyncMock(return_value=results)

        docs = await _retrieve_context_docs(
            search_index,
            None,
            "setup",
            "org/repo",
            spec_paths=set(),
        )
        assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_without_embedding(self):
        """Works with embed_client=None (text-only search)."""
        results = [
            FakeSearchResult(
                1, 1, "org/repo", "docs/readme.md", "README", "Overview", "overview", "done", 0.5
            ),
        ]
        search_index = MagicMock()
        search_index.hybrid_search = AsyncMock(return_value=results)

        docs = await _retrieve_context_docs(
            search_index,
            None,
            "overview",
            "org/repo",
            spec_paths=set(),
        )
        assert len(docs) == 1
        # hybrid_search should have been called with query_embedding=None
        call_kwargs = search_index.hybrid_search.call_args.kwargs
        assert call_kwargs["query_embedding"] is None

    @pytest.mark.asyncio
    async def test_with_embedding_client(self):
        """Embeds query when embed_client is available."""
        results = [
            FakeSearchResult(
                1, 1, "org/repo", "docs/readme.md", "README", "Intro", "intro body", "done", 0.8
            ),
        ]
        search_index = MagicMock()
        search_index.hybrid_search = AsyncMock(return_value=results)

        embed_client = MagicMock()
        embed_client.is_available = True
        embed_client.embed_query.return_value = [0.1, 0.2, 0.3]

        docs = await _retrieve_context_docs(
            search_index,
            embed_client,
            "intro",
            "org/repo",
            spec_paths=set(),
        )
        assert len(docs) == 1
        call_kwargs = search_index.hybrid_search.call_args.kwargs
        assert call_kwargs["query_embedding"] == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_search_failure_returns_empty(self):
        """Graceful return on search error."""
        search_index = MagicMock()
        search_index.hybrid_search = AsyncMock(side_effect=Exception("DB down"))

        docs = await _retrieve_context_docs(
            search_index,
            None,
            "query",
            "org/repo",
            spec_paths=set(),
        )
        assert docs == []


# ─── _load_context_docs_fallback ─────────────────────────


class TestLoadContextDocsFallback:
    @pytest.mark.asyncio
    async def test_loads_doc_paths(self):
        """Fallback loads docs from GitHub using CANON.yaml doc_paths."""
        config_yaml = """
specs:
  doc_paths:
    - "docs/**/*.md"
"""
        section = MagicMock()
        section.title = "Architecture"
        section.content = "This describes the architecture."
        section.children = []

        document = MagicMock()
        document.frontmatter.title = "Arch Guide"
        document.sections = [section]

        client = MagicMock()

        async def mock_get_file_content(owner, repo, path, ref=None):
            if path in ("CANON.yaml", "SPECWRIGHT.yaml"):
                return (config_yaml, "sha")
            return ("# Arch Guide\n\nThis describes the architecture.", "sha")

        client.get_file_content = AsyncMock(side_effect=mock_get_file_content)

        with patch(
            "canon.github.handlers.on_pull_request.load_repo_docs",
            new_callable=AsyncMock,
            return_value=[
                {
                    "file_path": "docs/architecture.md",
                    "document": document,
                    "raw": "# Arch Guide\n\nThis describes the architecture.",
                },
            ],
        ):
            docs = await _load_context_docs_fallback(
                client,
                "org",
                "repo",
                spec_paths=set(),
            )

        assert len(docs) == 1
        assert docs[0].path == "docs/architecture.md"
        assert docs[0].doc_title == "Arch Guide"

    @pytest.mark.asyncio
    async def test_excludes_spec_files(self):
        """Fallback skips files already in spec_paths."""
        section = MagicMock()
        section.title = "Section"
        section.content = "Some content"
        section.children = []

        document = MagicMock()
        document.frontmatter.title = "Spec"
        document.sections = [section]

        client = MagicMock()
        client.get_file_content = AsyncMock(side_effect=Exception("Not found"))

        with patch(
            "canon.github.handlers.on_pull_request.load_repo_docs",
            new_callable=AsyncMock,
            return_value=[
                {
                    "file_path": "docs/specs/auth.md",
                    "document": document,
                    "raw": "content",
                },
            ],
        ):
            docs = await _load_context_docs_fallback(
                client,
                "org",
                "repo",
                spec_paths={"docs/specs/auth.md"},
            )

        assert len(docs) == 0

    @pytest.mark.asyncio
    async def test_fallback_failure_returns_empty(self):
        """Returns empty list on total failure."""
        client = MagicMock()
        client.get_file_content = AsyncMock(side_effect=Exception("Not found"))

        with patch(
            "canon.github.handlers.on_pull_request.load_repo_docs",
            new_callable=AsyncMock,
            side_effect=Exception("Cannot list"),
        ):
            docs = await _load_context_docs_fallback(
                client,
                "org",
                "repo",
                spec_paths=set(),
            )

        assert docs == []
