"""Parity comparison between Postgres and OpenSearch search backends.

Used during the Phase 2 cutover to validate that OpenSearch results match
Postgres for the same query. Compares top-N overlap (Jaccard-style) and
rank correlation over the intersection.

This module is read-only — neither backend is mutated.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from .backend import OpenSearchBackend, PostgresSearchBackend
from .index import SearchResult

logger = logging.getLogger(__name__)


def _result_key(r: SearchResult) -> str:
    """Stable cross-backend identity for a SearchResult.

    ``section_id`` differs across backends (Postgres int vs OpenSearch hash),
    so we key by ``(repo, path, heading)`` which is stable as long as the
    same source spec is indexed in both.
    """
    return f"{r.repo}::{r.path}::{r.heading}"


def _overlap_at(n: int, pg_keys: list[str], os_keys: list[str]) -> int:
    """Count keys present in both top-N slices."""
    pg_top = set(pg_keys[:n])
    os_top = set(os_keys[:n])
    return len(pg_top & os_top)


def _rank_correlation(pg_keys: list[str], os_keys: list[str]) -> float | None:
    """Spearman rank correlation over keys present in both result sets.

    The standard `rho = 1 - 6 * sum(d^2) / (n * (n^2 - 1))` formula expects
    ranks within the common subset (1..n), not positions in the full result
    lists. We re-rank the intersection in each backend's order before
    computing differences, so partial-overlap cases produce values bounded
    to [-1, 1].

    Returns None when there are fewer than two overlapping keys (correlation
    is undefined).
    """
    os_index = {k: i for i, k in enumerate(os_keys)}
    common = [k for k in pg_keys if k in os_index]
    if len(common) < 2:
        return None

    pg_rank = {k: i for i, k in enumerate(common)}
    os_rank = {k: i for i, k in enumerate(sorted(common, key=lambda k: os_index[k]))}

    n = len(common)
    d_squared_sum = sum((pg_rank[k] - os_rank[k]) ** 2 for k in common)
    return 1.0 - (6.0 * d_squared_sum) / (n * (n * n - 1))


@dataclass
class ParityComparison:
    """Result of comparing a single query across both backends.

    ``postgres_error`` and ``opensearch_error`` capture exception text from
    the corresponding backend call. When set, the metrics for that side
    are not meaningful — a zero overlap with one error means "the other
    backend errored," not "the backends disagree."
    """

    query: str
    repo: str | None
    status: str | None
    limit: int
    postgres: list[SearchResult]
    opensearch: list[SearchResult]
    overlap_at_5: int
    overlap_at_10: int
    overlap_at_20: int
    rank_correlation: float | None
    postgres_error: str | None = None
    opensearch_error: str | None = None

    def to_dict(self) -> dict:
        """Serialise for logging / JSON reports.

        Truncates each result body to 160 chars to keep reports compact.
        """
        return {
            "query": self.query,
            "repo": self.repo,
            "status": self.status,
            "limit": self.limit,
            "overlap_at_5": self.overlap_at_5,
            "overlap_at_10": self.overlap_at_10,
            "overlap_at_20": self.overlap_at_20,
            "rank_correlation": self.rank_correlation,
            "postgres_error": self.postgres_error,
            "opensearch_error": self.opensearch_error,
            "postgres": [_serialise_result(r) for r in self.postgres],
            "opensearch": [_serialise_result(r) for r in self.opensearch],
        }


@dataclass
class CorpusReport:
    """Aggregate parity report across a batch of queries.

    ``failures`` counts queries where ``compare_query`` itself raised plus
    queries where either backend reported an ``error`` field. CLI callers
    should treat ``failures > 0`` as a non-zero exit so cutover gating
    doesn't pass a run where validation infrastructure was broken.
    """

    query_count: int
    mean_overlap_at_5: float
    mean_overlap_at_10: float
    mean_overlap_at_20: float
    mean_rank_correlation: float | None
    queries_with_zero_overlap: int
    failures: int = 0
    per_query: list[ParityComparison] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query_count": self.query_count,
            "mean_overlap_at_5": self.mean_overlap_at_5,
            "mean_overlap_at_10": self.mean_overlap_at_10,
            "mean_overlap_at_20": self.mean_overlap_at_20,
            "mean_rank_correlation": self.mean_rank_correlation,
            "queries_with_zero_overlap": self.queries_with_zero_overlap,
            "failures": self.failures,
            "per_query": [c.to_dict() for c in self.per_query],
        }


def _serialise_result(r: SearchResult) -> dict:
    d = asdict(r)
    body = d.get("body") or ""
    if len(body) > 160:
        d["body"] = body[:160] + "…"
    return d


async def compare_query(
    *,
    query: str,
    postgres: PostgresSearchBackend,
    opensearch: OpenSearchBackend,
    embed_client=None,
    repo: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> ParityComparison:
    """Run the same query against both backends and compute parity metrics.

    Both backends receive identical filters. When ``embed_client`` is
    available, the same embedding is fed to both — so any difference is
    purely in the index content / scoring, not the query vector.
    """
    embedding: list[float] | None = None
    if embed_client is not None and getattr(embed_client, "is_available", False):
        try:
            embedding = embed_client.embed_query(query)
        except Exception:
            # Operator-visible: silent text-only fallback would skew
            # correlation values during validation runs.
            logger.warning("Embedding failed during parity check", exc_info=True)

    # Use raise_on_error so per-backend failures surface as explicit errors
    # in the report rather than masquerading as "zero overlap".
    pg_results: list[SearchResult] = []
    pg_error: str | None = None
    try:
        pg_results = await postgres.hybrid_search(
            query_embedding=embedding,
            query_text=query,
            repo=repo,
            status=status,
            limit=limit,
            raise_on_error=True,
        )
    except Exception as exc:
        pg_error = f"{type(exc).__name__}: {exc}"

    os_results: list[SearchResult] = []
    os_error: str | None = None
    try:
        os_results = await opensearch.hybrid_search(
            query_embedding=embedding,
            query_text=query,
            repo=repo,
            status=status,
            limit=limit,
            raise_on_error=True,
        )
    except Exception as exc:
        os_error = f"{type(exc).__name__}: {exc}"

    pg_keys = [_result_key(r) for r in pg_results]
    os_keys = [_result_key(r) for r in os_results]

    return ParityComparison(
        query=query,
        repo=repo,
        status=status,
        limit=limit,
        postgres=pg_results,
        opensearch=os_results,
        overlap_at_5=_overlap_at(5, pg_keys, os_keys),
        overlap_at_10=_overlap_at(10, pg_keys, os_keys),
        overlap_at_20=_overlap_at(20, pg_keys, os_keys),
        rank_correlation=_rank_correlation(pg_keys, os_keys),
        postgres_error=pg_error,
        opensearch_error=os_error,
    )


async def compare_corpus(
    *,
    queries: list[str],
    postgres: PostgresSearchBackend,
    opensearch: OpenSearchBackend,
    embed_client=None,
    repo: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> CorpusReport:
    """Run a batch of queries through both backends and aggregate the report."""
    per_query: list[ParityComparison] = []
    failures = 0
    for q in queries:
        try:
            cmp = await compare_query(
                query=q,
                postgres=postgres,
                opensearch=opensearch,
                embed_client=embed_client,
                repo=repo,
                status=status,
                limit=limit,
            )
        except Exception:
            logger.warning("Parity comparison failed for query %r", q, exc_info=True)
            failures += 1
            continue
        if cmp.postgres_error or cmp.opensearch_error:
            failures += 1
        per_query.append(cmp)

    n = len(per_query)
    if n == 0:
        return CorpusReport(
            query_count=0,
            mean_overlap_at_5=0.0,
            mean_overlap_at_10=0.0,
            mean_overlap_at_20=0.0,
            mean_rank_correlation=None,
            queries_with_zero_overlap=0,
            failures=failures,
            per_query=[],
        )

    correlations = [c.rank_correlation for c in per_query if c.rank_correlation is not None]
    mean_corr = sum(correlations) / len(correlations) if correlations else None

    return CorpusReport(
        query_count=n,
        mean_overlap_at_5=sum(c.overlap_at_5 for c in per_query) / n,
        mean_overlap_at_10=sum(c.overlap_at_10 for c in per_query) / n,
        mean_overlap_at_20=sum(c.overlap_at_20 for c in per_query) / n,
        mean_rank_correlation=mean_corr,
        queries_with_zero_overlap=sum(1 for c in per_query if c.overlap_at_20 == 0),
        failures=failures,
        per_query=per_query,
    )
