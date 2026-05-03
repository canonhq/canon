"""Tests for the search parity comparison module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from canon.search.index import SearchResult
from canon.search.parity import (
    _overlap_at,
    _rank_correlation,
    _result_key,
    compare_corpus,
    compare_query,
)


def _result(repo: str, path: str, heading: str, score: float = 1.0) -> SearchResult:
    return SearchResult(
        section_id=hash(heading) & 0x7FFFFFFF,
        document_id=1,
        repo=repo,
        path=path,
        doc_title=path,
        heading=heading,
        body=f"body for {heading}",
        status="draft",
        rrf_score=score,
    )


def _backend_returning(results: list[SearchResult]):
    backend = MagicMock()
    backend.hybrid_search = AsyncMock(return_value=results)
    return backend


class TestResultKey:
    def test_uses_repo_path_heading(self):
        r = _result("o/r", "p.md", "Auth")
        assert _result_key(r) == "o/r::p.md::Auth"


class TestOverlapAt:
    def test_full_overlap(self):
        keys = ["a", "b", "c"]
        assert _overlap_at(3, keys, keys) == 3

    def test_partial_overlap(self):
        assert _overlap_at(3, ["a", "b", "c"], ["a", "z", "c"]) == 2

    def test_disjoint(self):
        assert _overlap_at(5, ["a", "b"], ["x", "y"]) == 0

    def test_handles_short_lists(self):
        assert _overlap_at(10, ["a"], ["a"]) == 1


class TestRankCorrelation:
    def test_identical_orderings_return_one(self):
        keys = ["a", "b", "c"]
        assert _rank_correlation(keys, keys) == 1.0

    def test_reversed_orderings_return_minus_one(self):
        assert _rank_correlation(["a", "b", "c"], ["c", "b", "a"]) == -1.0

    def test_disjoint_returns_none(self):
        assert _rank_correlation(["a", "b"], ["x", "y"]) is None

    def test_single_overlap_returns_none(self):
        assert _rank_correlation(["a", "b"], ["a", "z"]) is None

    def test_partial_overlap_stays_in_range(self):
        """The two overlapping keys appear far apart in both lists; the
        correlation must still be bounded to [-1, 1] by re-ranking within
        the intersection (older buggy formula returned -49 here)."""
        result = _rank_correlation(
            ["a", "x1", "x2", "x3", "x4", "b"],
            ["b", "y1", "y2", "y3", "y4", "a"],
        )
        # Within {a,b}, PG order is (a,b) and OS order is (b,a) — fully
        # reversed → correlation = -1.0.
        assert result == -1.0

    def test_partial_overlap_same_order(self):
        """Two overlapping keys, same order in both lists, regardless of
        their absolute positions."""
        result = _rank_correlation(
            ["a", "x", "y", "b"],
            ["q", "a", "r", "b"],
        )
        assert result == 1.0


class TestCompareQuery:
    async def test_full_overlap_yields_high_metrics(self):
        results = [
            _result("o/r", "a.md", "H1"),
            _result("o/r", "a.md", "H2"),
            _result("o/r", "b.md", "H3"),
        ]
        pg = _backend_returning(results)
        os_ = _backend_returning(results)

        cmp = await compare_query(query="hello", postgres=pg, opensearch=os_, limit=3)
        assert cmp.overlap_at_5 == 3
        assert cmp.overlap_at_10 == 3
        assert cmp.overlap_at_20 == 3
        assert cmp.rank_correlation == 1.0

    async def test_disjoint_results(self):
        pg = _backend_returning([_result("o/r", "a.md", "X")])
        os_ = _backend_returning([_result("o/r", "b.md", "Y")])

        cmp = await compare_query(query="hello", postgres=pg, opensearch=os_)
        assert cmp.overlap_at_5 == 0
        assert cmp.rank_correlation is None

    async def test_passes_filters_to_both_backends(self):
        pg = _backend_returning([])
        os_ = _backend_returning([])

        await compare_query(
            query="auth",
            postgres=pg,
            opensearch=os_,
            repo="o/r",
            status="draft",
            limit=10,
        )
        for backend in (pg, os_):
            kwargs = backend.hybrid_search.await_args.kwargs
            assert kwargs["repo"] == "o/r"
            assert kwargs["status"] == "draft"
            assert kwargs["limit"] == 10
            assert kwargs["query_text"] == "auth"

    async def test_uses_same_embedding_for_both_backends(self):
        pg = _backend_returning([])
        os_ = _backend_returning([])
        embed = MagicMock()
        embed.is_available = True
        embed.embed_query.return_value = [0.1, 0.2, 0.3]

        await compare_query(query="auth", postgres=pg, opensearch=os_, embed_client=embed)
        embed.embed_query.assert_called_once_with("auth")
        for backend in (pg, os_):
            kwargs = backend.hybrid_search.await_args.kwargs
            assert kwargs["query_embedding"] == [0.1, 0.2, 0.3]

    async def test_skips_embedding_when_unavailable(self):
        pg = _backend_returning([])
        os_ = _backend_returning([])
        embed = MagicMock()
        embed.is_available = False

        await compare_query(query="auth", postgres=pg, opensearch=os_, embed_client=embed)
        embed.embed_query.assert_not_called()

    async def test_to_dict_truncates_long_bodies(self):
        long_body = "x" * 500
        long_result = SearchResult(1, 1, "o/r", "p.md", "T", "H", long_body, "draft", 0.5)
        pg = _backend_returning([long_result])
        os_ = _backend_returning([long_result])

        cmp = await compare_query(query="x", postgres=pg, opensearch=os_)
        d = cmp.to_dict()
        assert d["postgres"][0]["body"].endswith("…")
        assert len(d["postgres"][0]["body"]) == 161  # 160 + ellipsis


class TestCompareCorpus:
    async def test_aggregates_metrics(self):
        results = [_result("o/r", "a.md", f"H{i}") for i in range(3)]
        pg = _backend_returning(results)
        os_ = _backend_returning(results)

        report = await compare_corpus(queries=["q1", "q2"], postgres=pg, opensearch=os_, limit=3)
        assert report.query_count == 2
        assert report.mean_overlap_at_10 == 3.0
        assert report.mean_rank_correlation == 1.0
        assert report.queries_with_zero_overlap == 0

    async def test_counts_zero_overlap_queries(self):
        pg = _backend_returning([_result("o/r", "a.md", "X")])
        os_ = _backend_returning([_result("o/r", "b.md", "Y")])

        report = await compare_corpus(queries=["q1", "q2"], postgres=pg, opensearch=os_)
        assert report.queries_with_zero_overlap == 2

    async def test_empty_query_list(self):
        pg = _backend_returning([])
        os_ = _backend_returning([])
        report = await compare_corpus(queries=[], postgres=pg, opensearch=os_)
        assert report.query_count == 0
        assert report.mean_overlap_at_10 == 0.0
        assert report.mean_rank_correlation is None

    async def test_per_backend_errors_count_as_failures(self):
        """A backend exception is captured into postgres_error/opensearch_error
        on the comparison; the corpus-level failures counter increments per
        comparison with at least one such error, so CLI gating sees the run
        as broken even though every comparison "succeeded"."""
        pg = MagicMock()
        pg.hybrid_search = AsyncMock(side_effect=[RuntimeError("boom"), []])
        os_ = _backend_returning([])

        report = await compare_corpus(queries=["bad", "good"], postgres=pg, opensearch=os_)
        # Both queries produced a ParityComparison object, but the first
        # has a postgres_error set → counted as a failure.
        assert report.query_count == 2
        assert report.failures == 1


class TestPerBackendErrorReporting:
    async def test_postgres_error_surfaced_when_pg_raises(self):
        pg = MagicMock()
        pg.hybrid_search = AsyncMock(side_effect=RuntimeError("connection reset"))
        os_ = MagicMock()
        os_.hybrid_search = AsyncMock(return_value=[])

        cmp = await compare_query(query="x", postgres=pg, opensearch=os_)
        assert cmp.postgres_error is not None
        assert "connection reset" in cmp.postgres_error
        assert cmp.opensearch_error is None
        # Backend gets called with raise_on_error=True so parity sees the
        # exception even though backend default-swallows.
        kwargs = pg.hybrid_search.await_args.kwargs
        assert kwargs["raise_on_error"] is True

    async def test_opensearch_error_surfaced_when_os_raises(self):
        pg = MagicMock()
        pg.hybrid_search = AsyncMock(return_value=[])
        os_ = MagicMock()
        os_.hybrid_search = AsyncMock(side_effect=RuntimeError("503 Service Unavailable"))

        cmp = await compare_query(query="x", postgres=pg, opensearch=os_)
        assert cmp.opensearch_error is not None
        assert "503" in cmp.opensearch_error
        assert cmp.postgres_error is None

    async def test_both_errors_when_both_raise(self):
        pg = MagicMock()
        pg.hybrid_search = AsyncMock(side_effect=RuntimeError("pg fail"))
        os_ = MagicMock()
        os_.hybrid_search = AsyncMock(side_effect=RuntimeError("os fail"))

        cmp = await compare_query(query="x", postgres=pg, opensearch=os_)
        assert cmp.postgres_error is not None
        assert cmp.opensearch_error is not None

    async def test_compare_corpus_counts_per_backend_errors_as_failures(self):
        pg = MagicMock()
        pg.hybrid_search = AsyncMock(side_effect=RuntimeError("pg fail"))
        os_ = MagicMock()
        os_.hybrid_search = AsyncMock(return_value=[])

        report = await compare_corpus(queries=["q1", "q2"], postgres=pg, opensearch=os_)
        # Both queries succeeded as comparisons (no raise from compare_query
        # itself) but each had postgres_error set → two failures.
        assert report.query_count == 2
        assert report.failures == 2

    async def test_to_dict_includes_error_fields(self):
        pg = MagicMock()
        pg.hybrid_search = AsyncMock(side_effect=RuntimeError("pg fail"))
        os_ = MagicMock()
        os_.hybrid_search = AsyncMock(return_value=[])

        cmp = await compare_query(query="x", postgres=pg, opensearch=os_)
        d = cmp.to_dict()
        assert "postgres_error" in d
        assert "opensearch_error" in d
        assert d["postgres_error"] is not None
        assert d["opensearch_error"] is None
