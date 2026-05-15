"""Tests for the search index (upsert, delete, hybrid search)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock

import pytest

from canon.search.index import SearchIndex, SearchResult, _to_pgvector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock pool whose acquire() returns an async context manager."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


class FakeTransaction:
    """Async context manager that does nothing (simulates a DB transaction)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _mock_conn_with_transaction() -> MagicMock:
    """Create a mock connection where transaction() returns an async CM directly.

    asyncpg's conn.transaction() returns a Transaction object (async CM) directly
    rather than a coroutine, so AsyncMock won't work here.
    """
    mock_conn = MagicMock()
    mock_conn.transaction.return_value = FakeTransaction()
    mock_conn.fetchval = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.executemany = AsyncMock()
    mock_conn.fetch = AsyncMock()
    return mock_conn


# ---------------------------------------------------------------------------
# _to_pgvector
# ---------------------------------------------------------------------------


class TestToPgvector:
    def test_none_returns_none(self):
        assert _to_pgvector(None) is None

    def test_empty_list(self):
        assert _to_pgvector([]) == "[]"

    def test_single_value(self):
        assert _to_pgvector([0.5]) == "[0.5]"

    def test_multiple_values(self):
        result = _to_pgvector([0.1, 0.2, 0.3])
        assert result == "[0.1,0.2,0.3]"

    def test_negative_values(self):
        result = _to_pgvector([-0.5, 0.0, 1.0])
        assert result == "[-0.5,0.0,1.0]"


# ---------------------------------------------------------------------------
# upsert_spec
# ---------------------------------------------------------------------------


class TestUpsertSpec:
    async def test_inserts_doc_and_sections(self):
        mock_conn = _mock_conn_with_transaction()
        mock_conn.fetchval.return_value = 42
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        doc_id = await index.upsert_spec(
            repo="org/repo",
            path="docs/specs/auth.md",
            title="Auth Migration",
            status="in-progress",
            content="# Auth\nSome content",
            doc_embedding=[0.1, 0.2],
            sections=[
                {
                    "heading": "Phase 1",
                    "level": 2,
                    "body": "Do stuff",
                    "status": "done",
                    "ticket_ref": "PROJ-123",
                    "embedding": [0.3, 0.4],
                },
            ],
        )

        assert doc_id == 42
        mock_conn.fetchval.assert_awaited_once()
        mock_conn.execute.assert_awaited_once()  # DELETE sections
        mock_conn.executemany.assert_awaited_once()

    async def test_no_sections(self):
        mock_conn = _mock_conn_with_transaction()
        mock_conn.fetchval.return_value = 1
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        doc_id = await index.upsert_spec(
            repo="org/repo",
            path="docs/specs/empty.md",
            title="Empty",
            status="draft",
            content="# Empty",
            doc_embedding=None,
            sections=[],
        )

        assert doc_id == 1
        mock_conn.executemany.assert_not_awaited()

    async def test_content_hash_computed(self):
        """Verify the content hash is passed to the INSERT query."""
        import hashlib

        mock_conn = _mock_conn_with_transaction()
        mock_conn.fetchval.return_value = 10
        mock_pool = _mock_pool_with_conn(mock_conn)

        content = "# Test Spec\nSome content here"
        expected_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        index = SearchIndex(mock_pool)
        await index.upsert_spec(
            repo="org/repo",
            path="docs/specs/test.md",
            title="Test",
            status="draft",
            content=content,
            doc_embedding=None,
            sections=[],
        )

        call_args = mock_conn.fetchval.call_args
        # content_hash is the 5th positional arg after the SQL
        assert call_args[0][5] == expected_hash

    async def test_embedding_conversion(self):
        """Embeddings are converted to pgvector string format."""
        mock_conn = _mock_conn_with_transaction()
        mock_conn.fetchval.return_value = 5
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index.upsert_spec(
            repo="org/repo",
            path="docs/specs/x.md",
            title="X",
            status="done",
            content="test",
            doc_embedding=[0.1, 0.2, 0.3],
            sections=[],
        )

        call_args = mock_conn.fetchval.call_args
        # embedding is the 7th positional arg (after commit_sha)
        assert call_args[0][7] == "[0.1,0.2,0.3]"

    async def test_commit_sha_passed_through(self):
        """Verify commit_sha is passed to the INSERT query."""
        mock_conn = _mock_conn_with_transaction()
        mock_conn.fetchval.return_value = 7
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index.upsert_spec(
            repo="org/repo",
            path="docs/specs/sha.md",
            title="SHA Test",
            status="draft",
            content="test",
            doc_embedding=None,
            sections=[],
            commit_sha="abc123",
        )

        call_args = mock_conn.fetchval.call_args
        # commit_sha is the 6th positional arg after the SQL
        assert call_args[0][6] == "abc123"

    async def test_commit_sha_defaults_to_empty(self):
        """Verify commit_sha defaults to empty string."""
        mock_conn = _mock_conn_with_transaction()
        mock_conn.fetchval.return_value = 8
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index.upsert_spec(
            repo="org/repo",
            path="docs/specs/default.md",
            title="Default",
            status="draft",
            content="test",
            doc_embedding=None,
            sections=[],
        )

        call_args = mock_conn.fetchval.call_args
        # commit_sha is the 6th positional arg, defaults to ""
        assert call_args[0][6] == ""


# ---------------------------------------------------------------------------
# delete_spec
# ---------------------------------------------------------------------------


class TestDeleteSpec:
    async def test_returns_true_when_deleted(self):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "DELETE 1"
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        result = await index.delete_spec("org/repo", "docs/specs/old.md")

        assert result is True

    async def test_returns_false_when_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "DELETE 0"
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        result = await index.delete_spec("org/repo", "docs/specs/missing.md")

        assert result is False


# ---------------------------------------------------------------------------
# hybrid_search
# ---------------------------------------------------------------------------


class TestHybridSearch:
    async def test_returns_search_results(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "section_id": 1,
                "document_id": 10,
                "repo": "org/repo",
                "path": "docs/specs/auth.md",
                "doc_title": "Auth",
                "heading": "Phase 1",
                "body": "Do auth stuff",
                "status": "in-progress",
                "rrf_score": 0.032,
            },
        ]
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        results = await index.hybrid_search(
            query_embedding=[0.1, 0.2],
            query_text="authentication",
        )

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].section_id == 1
        assert results[0].heading == "Phase 1"
        assert results[0].rrf_score == pytest.approx(0.032)

    async def test_empty_results(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        results = await index.hybrid_search(
            query_embedding=[0.1],
            query_text="nonexistent",
        )

        assert results == []

    async def test_repo_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index.hybrid_search(
            query_embedding=[0.1],
            query_text="test",
            repo="org/specific-repo",
        )

        sql = mock_conn.fetch.call_args[0][0]
        assert "d.repo = $2" in sql

    async def test_status_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index.hybrid_search(
            query_embedding=[0.1],
            query_text="test",
            status="done",
        )

        sql = mock_conn.fetch.call_args[0][0]
        assert "s.status = $2" in sql

    async def test_both_filters(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index.hybrid_search(
            query_embedding=[0.1],
            query_text="test",
            repo="org/repo",
            status="in-progress",
        )

        sql = mock_conn.fetch.call_args[0][0]
        assert "d.repo = $2" in sql
        assert "s.status = $3" in sql

    async def test_limit_param(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index.hybrid_search(
            query_embedding=[0.1],
            query_text="test",
            limit=5,
        )

        # limit should be passed as a param
        call_args = mock_conn.fetch.call_args[0]
        assert 5 in call_args


# ---------------------------------------------------------------------------
# get_indexed_paths
# ---------------------------------------------------------------------------


class TestGetIndexedPaths:
    async def test_returns_indexed_documents(self):
        from datetime import datetime

        now = datetime(2026, 2, 13, tzinfo=UTC)
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "repo": "org/repo",
                "path": "docs/specs/auth.md",
                "indexed_at": now,
                "has_embedding": True,
            },
            {
                "repo": "org/repo",
                "path": "docs/specs/api.md",
                "indexed_at": now,
                "has_embedding": False,
            },
        ]
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        result = await index.get_indexed_paths()

        assert len(result) == 2
        assert "org/repo/docs/specs/auth.md" in result
        assert result["org/repo/docs/specs/auth.md"]["has_embedding"] is True
        assert result["org/repo/docs/specs/api.md"]["has_embedding"] is False

    async def test_repo_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index.get_indexed_paths(repo="org/specific")

        sql = mock_conn.fetch.call_args[0][0]
        assert "WHERE repo = $1" in sql

    async def test_no_repo_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index.get_indexed_paths()

        sql = mock_conn.fetch.call_args[0][0]
        assert "WHERE" not in sql


# ---------------------------------------------------------------------------
# delete_repo
# ---------------------------------------------------------------------------


class TestDeleteRepo:
    async def test_deletes_all_docs_for_repo(self):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "DELETE 3"
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        count = await index.delete_repo("org/repo")

        assert count == 3
        sql = mock_conn.execute.call_args[0][0]
        assert "DELETE FROM spec_documents" in sql
        assert "WHERE repo = $1" in sql

    async def test_returns_zero_when_no_docs(self):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "DELETE 0"
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        count = await index.delete_repo("org/empty")
        assert count == 0


# ---------------------------------------------------------------------------
# hybrid_search with empty embedding
# ---------------------------------------------------------------------------


class TestHybridSearchEmptyEmbedding:
    async def test_falls_back_to_bm25_with_none_embedding(self):
        """When query_embedding is None, should use BM25 fallback."""
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "section_id": 1,
                "document_id": 10,
                "repo": "org/repo",
                "path": "docs/specs/auth.md",
                "doc_title": "Auth",
                "heading": "Phase 1",
                "body": "Auth stuff",
                "status": "done",
                "bm25_score": 5.2,
            },
        ]
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        results = await index.hybrid_search(
            query_embedding=None,
            query_text="authentication",
        )

        assert len(results) == 1
        # BM25-only search should not include vector CTE
        sql = mock_conn.fetch.call_args[0][0]
        assert "paradedb" in sql.lower() or "ILIKE" in sql

    async def test_falls_back_to_bm25_with_empty_list(self):
        """When query_embedding is [], should use BM25 fallback."""
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        results = await index.hybrid_search(
            query_embedding=[],
            query_text="test",
        )

        assert results == []


# ---------------------------------------------------------------------------
# _ilike_search (last resort fallback)
# ---------------------------------------------------------------------------


class TestIlikeSearch:
    async def test_searches_with_ilike(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "section_id": 1,
                "document_id": 10,
                "repo": "org/repo",
                "path": "docs/specs/auth.md",
                "doc_title": "Auth",
                "heading": "Login",
                "body": "Login flow",
                "status": "draft",
            },
        ]
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        results = await index._ilike_search(query_text="login")

        assert len(results) == 1
        assert results[0].heading == "Login"
        assert results[0].rrf_score == 0.0

    async def test_ilike_with_repo_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index._ilike_search(query_text="test", repo="org/repo")

        sql = mock_conn.fetch.call_args[0][0]
        assert "d.repo = $2" in sql

    async def test_ilike_with_status_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index._ilike_search(query_text="test", status="done")

        sql = mock_conn.fetch.call_args[0][0]
        assert "s.status = $2" in sql

    async def test_ilike_with_both_filters(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index._ilike_search(query_text="test", repo="org/r", status="draft")

        sql = mock_conn.fetch.call_args[0][0]
        assert "d.repo = $2" in sql
        assert "s.status = $3" in sql


# ---------------------------------------------------------------------------
# _vector_only_search
# ---------------------------------------------------------------------------


class TestVectorOnlySearch:
    async def test_returns_results_with_similarity_score(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "section_id": 1,
                "document_id": 10,
                "repo": "org/repo",
                "path": "docs/specs/auth.md",
                "doc_title": "Auth",
                "heading": "Phase 1",
                "body": "Do auth",
                "status": "draft",
                "similarity": 0.85,
            },
        ]
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        results = await index._vector_only_search(
            query_embedding=[0.1, 0.2, 0.3],
        )

        assert len(results) == 1
        assert results[0].rrf_score == pytest.approx(0.85)

    async def test_vector_only_with_repo_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index._vector_only_search(
            query_embedding=[0.1],
            repo="org/repo",
        )

        sql = mock_conn.fetch.call_args[0][0]
        assert "d.repo = $2" in sql

    async def test_vector_only_with_status_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index._vector_only_search(
            query_embedding=[0.1],
            status="in-progress",
        )

        sql = mock_conn.fetch.call_args[0][0]
        assert "s.status = $2" in sql

    async def test_vector_only_with_both_filters(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index._vector_only_search(
            query_embedding=[0.1],
            repo="org/repo",
            status="done",
        )

        sql = mock_conn.fetch.call_args[0][0]
        assert "d.repo = $2" in sql
        assert "s.status = $3" in sql


# ---------------------------------------------------------------------------
# _bm25_only_search
# ---------------------------------------------------------------------------


class TestBm25OnlySearch:
    async def test_with_repo_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index._bm25_only_search(query_text="test", repo="org/repo")

        sql = mock_conn.fetch.call_args[0][0]
        assert "d.repo = $2" in sql

    async def test_with_status_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index._bm25_only_search(query_text="test", status="done")

        sql = mock_conn.fetch.call_args[0][0]
        assert "s.status = $2" in sql

    async def test_falls_back_to_ilike_on_paradedb_error(self):
        """When ParadeDB is unavailable, falls back to ILIKE search."""
        mock_conn = AsyncMock()
        # First call (BM25) raises, second call (ILIKE fallback) works
        mock_conn.fetch = AsyncMock(
            side_effect=[
                Exception("paradedb not installed"),
                [
                    {
                        "section_id": 1,
                        "document_id": 10,
                        "repo": "org/repo",
                        "path": "p.md",
                        "doc_title": "T",
                        "heading": "H",
                        "body": "B",
                        "status": "draft",
                    },
                ],
            ]
        )
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        results = await index._bm25_only_search(query_text="test")

        assert len(results) == 1
        assert results[0].rrf_score == 0.0  # ILIKE fallback score


# ---------------------------------------------------------------------------
# hybrid_search fallback to vector-only
# ---------------------------------------------------------------------------


class TestHybridSearchFallback:
    async def test_falls_back_to_vector_only_when_bm25_unavailable(self):
        """When the hybrid SQL fails (e.g. ParadeDB not installed), falls
        back to vector-only search."""
        mock_conn = AsyncMock()
        # First call (hybrid) raises, second call (vector-only) works
        mock_conn.fetch = AsyncMock(
            side_effect=[
                Exception("paradedb not installed"),
                [
                    {
                        "section_id": 1,
                        "document_id": 10,
                        "repo": "org/repo",
                        "path": "p.md",
                        "doc_title": "T",
                        "heading": "H",
                        "body": "B",
                        "status": "draft",
                        "similarity": 0.9,
                    },
                ],
            ]
        )
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        results = await index.hybrid_search(
            query_embedding=[0.1, 0.2],
            query_text="test",
        )

        assert len(results) == 1
        assert results[0].rrf_score == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# get_facet_counts
# ---------------------------------------------------------------------------


class TestGetFacetCounts:
    async def test_returns_status_and_repo_counts(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            side_effect=[
                # status query
                [
                    {"status": "draft", "cnt": 5},
                    {"status": "done", "cnt": 2},
                ],
                # repo query
                [
                    {"repo": "org/repo1", "cnt": 4},
                    {"repo": "org/repo2", "cnt": 3},
                ],
            ]
        )
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        result = await index.get_facet_counts()

        assert result["status"] == {"draft": 5, "done": 2}
        assert result["repo"] == {"org/repo1": 4, "org/repo2": 3}

    async def test_with_repo_filter(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            side_effect=[
                [{"status": "draft", "cnt": 1}],
                [{"repo": "org/r", "cnt": 1}],
            ]
        )
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        await index.get_facet_counts(repo="org/r")

        # Both queries should include WHERE clause
        for call in mock_conn.fetch.call_args_list:
            sql = call[0][0]
            assert "WHERE" in sql

    async def test_filters_out_empty_status(self):
        """Rows with empty-string status are excluded."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            side_effect=[
                [{"status": "", "cnt": 2}, {"status": "draft", "cnt": 3}],
                [],
            ]
        )
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        result = await index.get_facet_counts()
        assert "" not in result["status"]
        assert result["status"] == {"draft": 3}


# ---------------------------------------------------------------------------
# mark_code_change
# ---------------------------------------------------------------------------


class TestMarkCodeChange:
    async def test_returns_empty_when_no_paths(self):
        mock_pool = MagicMock()
        index = SearchIndex(mock_pool)
        result = await index.mark_code_change("org/repo", [])
        assert result == []

    async def test_updates_last_code_change_and_returns_stale_ids(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 3")
        mock_conn.fetch = AsyncMock(return_value=[{"id": 42}, {"id": 99}])
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        result = await index.mark_code_change("org/repo", ["src/auth.py"])

        assert result == [42, 99]
        # Verify the UPDATE for last_code_change_at was called
        update_sql = mock_conn.execute.call_args[0][0]
        assert "last_code_change_at" in update_sql
        # Verify the stale_since UPDATE+RETURNING was called
        stale_sql = mock_conn.fetch.call_args[0][0]
        assert "stale_since" in stale_sql

    async def test_returns_empty_when_no_docs_become_stale(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        result = await index.mark_code_change("org/repo", ["src/main.py"])
        assert result == []


# ---------------------------------------------------------------------------
# find_related_docs
# ---------------------------------------------------------------------------


class TestFindRelatedDocs:
    async def test_returns_empty_when_no_code_paths(self):
        mock_pool = MagicMock()
        index = SearchIndex(mock_pool)
        result = await index.find_related_docs("org/repo", [])
        assert result == []

    async def test_returns_empty_when_no_dirs_extracted(self):
        """Single-component paths produce no directory prefixes."""
        mock_pool = MagicMock()
        index = SearchIndex(mock_pool)
        result = await index.find_related_docs("org/repo", ["README.md"])
        assert result == []

    async def test_returns_results_matching_dirs(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "section_id": 1,
                "document_id": 10,
                "repo": "org/repo",
                "path": "docs/specs/auth.md",
                "doc_title": "Auth",
                "heading": "Login",
                "body": "src/auth code",
                "status": "draft",
            },
        ]
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        results = await index.find_related_docs("org/repo", ["src/auth/handler.py"])

        assert len(results) == 1
        assert results[0].heading == "Login"
        assert results[0].rrf_score == 0.0

    async def test_limits_to_5_dirs(self):
        """Only the first 5 unique directory prefixes are used in the query."""
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        paths = [f"dir{i}/file.py" for i in range(10)]
        await index.find_related_docs("org/repo", paths)

        sql = mock_conn.fetch.call_args[0][0]
        # Should have at most 5 ILIKE conditions
        ilike_count = sql.count("ILIKE")
        assert ilike_count <= 5


# ---------------------------------------------------------------------------
# delete_repo edge cases
# ---------------------------------------------------------------------------


class TestDeleteRepoEdgeCases:
    async def test_handles_unexpected_result_format(self):
        """If execute returns something unparseable, returns 0."""
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "UNEXPECTED"
        mock_pool = _mock_pool_with_conn(mock_conn)

        index = SearchIndex(mock_pool)
        count = await index.delete_repo("org/repo")
        assert count == 0
