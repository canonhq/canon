"""Tests for the SearchBackend protocol and its two implementations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from canon.search.backend import (
    OpenSearchBackend,
    PostgresSearchBackend,
    build_backend,
)
from canon.search.index import RelatedSpec, SearchResult


class TestPostgresSearchBackend:
    async def test_hybrid_search_delegates(self):
        index = MagicMock()
        expected = [
            SearchResult(1, 1, "org/r", "p.md", "T", "H", "B", "draft", 0.5),
        ]
        index.hybrid_search = AsyncMock(return_value=expected)

        backend = PostgresSearchBackend(index)
        results = await backend.hybrid_search(
            query_embedding=[0.1] * 4,
            query_text="hello",
            repo="org/r",
            status="draft",
            limit=10,
        )
        assert results == expected
        kwargs = index.hybrid_search.await_args.kwargs
        assert kwargs["query_text"] == "hello"
        assert kwargs["repo"] == "org/r"
        assert kwargs["status"] == "draft"
        assert kwargs["limit"] == 10

    async def test_facet_counts_pads_team_and_tags(self):
        """PostgresSearchBackend has no team/tags columns, but the response shape
        must match OpenSearchBackend so consumers can rely on the keys."""
        index = MagicMock()
        index.get_facet_counts = AsyncMock(return_value={"status": {"draft": 3}, "repo": {}})
        backend = PostgresSearchBackend(index)
        result = await backend.get_facet_counts(repo="org/r")
        assert result == {
            "status": {"draft": 3},
            "repo": {},
            "team": {},
            "tags": {},
        }

    async def test_indexed_paths_delegates(self):
        index = MagicMock()
        index.get_indexed_paths = AsyncMock(return_value={"org/r/p.md": {"has_embedding": True}})
        backend = PostgresSearchBackend(index)
        assert await backend.get_indexed_paths(repo="org/r") == {
            "org/r/p.md": {"has_embedding": True}
        }

    async def test_get_related_returns_empty_when_no_pool(self):
        index = MagicMock(spec=[])  # no _pool attribute
        backend = PostgresSearchBackend(index)
        result = await backend.get_related(repo="o/r", path="p.md")
        assert result == []

    async def test_get_related_scopes_to_same_owner(self):
        """kNN must filter to the source's org. Without this filter, a
        caller in org-a could use their own spec as a pivot and discover
        org-b's spec titles/paths via vector similarity."""

        class _AsyncCM:
            def __init__(self, conn):
                self._conn = conn

            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *_args):
                return False

        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"embedding": [0.1, 0.2]})
        conn.fetch = AsyncMock(return_value=[])
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=_AsyncCM(conn))
        index = MagicMock()
        index._pool = pool

        backend = PostgresSearchBackend(index)
        await backend.get_related(repo="org-a/r", path="src.md")

        # SPLIT_PART(repo, '/', 1) = $5 — exact match on org segment.
        assert conn.fetch.await_args.args[5] == "org-a"
        assert "SPLIT_PART(repo, '/', 1) = $5" in conn.fetch.await_args.args[0]
        # LIKE wildcard would be a tenant-bypass vector ('%' would match
        # every repo containing a slash), so the SQL must NOT use LIKE.
        assert "LIKE" not in conn.fetch.await_args.args[0]

    async def test_get_related_no_like_wildcard_bypass(self):
        """Regression: if the owner contains a LIKE wildcard like '%', the
        SPLIT_PART equality must reject it as an exact match (no repo's
        owner is literally '%'). Tenant scope can't be bypassed by passing
        a wildcard in the owner argument."""

        class _AsyncCM:
            def __init__(self, conn):
                self._conn = conn

            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *_args):
                return False

        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"embedding": [0.1, 0.2]})
        conn.fetch = AsyncMock(return_value=[])
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=_AsyncCM(conn))
        index = MagicMock()
        index._pool = pool

        backend = PostgresSearchBackend(index)
        await backend.get_related(repo="%/r", path="p.md")

        # The literal '%' is passed as a value to be compared by equality
        # — there's no SQL operator that interprets it as a wildcard.
        assert conn.fetch.await_args.args[5] == "%"

    async def test_get_related_surfaces_ai_exposure_and_tags(self):
        """The MCP layer enforces per-spec ai_exposure on neighbour results;
        the PG backend MUST surface ai_exposure and tags from the columns.
        Without these, a spec with `ai_exposure: none` in its frontmatter
        would leak through find_related_specs when Postgres is the active
        backend."""

        class _AsyncCM:
            def __init__(self, conn):
                self._conn = conn

            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *_args):
                return False

        conn = MagicMock()
        # Source-spec embedding lookup
        conn.fetchrow = AsyncMock(return_value={"embedding": [0.1, 0.2]})
        # Neighbour rows include ai_exposure and tags
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "repo": "o/r",
                    "path": "hidden.md",
                    "title": "Hidden",
                    "ai_exposure": "none",
                    "tags": ["secret"],
                },
                {
                    "repo": "o/r",
                    "path": "ok.md",
                    "title": "OK",
                    "ai_exposure": "",
                    "tags": [],
                },
            ]
        )
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=_AsyncCM(conn))
        index = MagicMock()
        index._pool = pool

        backend = PostgresSearchBackend(index)
        results = await backend.get_related(repo="o/r", path="src.md")
        assert results[0].ai_exposure == "none"
        assert results[0].tags == ["secret"]
        assert results[1].ai_exposure == ""
        assert results[1].tags == []


def _opensearch_backend_with_response(response: dict) -> tuple[OpenSearchBackend, MagicMock]:
    """Construct an OpenSearchBackend with a mocked underlying client."""
    raw = MagicMock()
    raw.search = AsyncMock(return_value=response)
    raw.scroll = AsyncMock(return_value={"hits": {"hits": []}})
    raw.clear_scroll = AsyncMock()

    client = MagicMock()
    client.is_enabled = True
    client._client = raw
    client.specs_index = "canon-specs"
    client.sections_index = "canon-sections"
    return OpenSearchBackend(client), raw


class TestOpenSearchBackendDisabled:
    async def test_hybrid_search_returns_empty_when_disabled(self):
        client = MagicMock()
        client.is_enabled = False
        backend = OpenSearchBackend(client)
        results = await backend.hybrid_search(query_embedding=None, query_text="x")
        assert results == []

    async def test_facet_counts_returns_empty_when_disabled(self):
        client = MagicMock()
        client.is_enabled = False
        backend = OpenSearchBackend(client)
        result = await backend.get_facet_counts()
        assert result == {"status": {}, "repo": {}, "team": {}, "tags": {}}

    async def test_indexed_paths_returns_empty_when_disabled(self):
        client = MagicMock()
        client.is_enabled = False
        backend = OpenSearchBackend(client)
        assert await backend.get_indexed_paths() == {}


class TestOpenSearchBackendHybridSearch:
    async def test_returns_search_results_from_hits(self):
        backend, _raw = _opensearch_backend_with_response(
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "org/r:specs/a.md:0",
                            "_score": 1.5,
                            "_source": {
                                "_spec_doc_id": "org/r:specs/a.md",
                                "spec_repo": "org/r",
                                "spec_path": "specs/a.md",
                                "spec_title": "Spec A",
                                "heading": "Auth",
                                "body": "Login flow",
                                "status": "draft",
                            },
                        }
                    ]
                }
            }
        )
        results = await backend.hybrid_search(query_embedding=[0.1] * 4, query_text="auth")
        assert len(results) == 1
        r = results[0]
        assert r.repo == "org/r"
        assert r.path == "specs/a.md"
        assert r.heading == "Auth"
        assert r.body == "Login flow"
        assert r.status == "draft"
        assert r.rrf_score == 1.5

    async def test_includes_knn_clause_when_embedding_provided(self):
        backend, raw = _opensearch_backend_with_response({"hits": {"hits": []}})
        await backend.hybrid_search(query_embedding=[0.1, 0.2], query_text="auth")
        body = raw.search.await_args.kwargs["body"]
        clauses = body["query"]["bool"]["should"]
        assert any("knn" in c for c in clauses)
        assert any("match" in c for c in clauses)

    async def test_omits_knn_when_no_embedding(self):
        backend, raw = _opensearch_backend_with_response({"hits": {"hits": []}})
        await backend.hybrid_search(query_embedding=None, query_text="auth")
        body = raw.search.await_args.kwargs["body"]
        clauses = body["query"]["bool"]["should"]
        assert not any("knn" in c for c in clauses)

    async def test_repo_and_status_filter_to_term_clauses(self):
        backend, raw = _opensearch_backend_with_response({"hits": {"hits": []}})
        await backend.hybrid_search(
            query_embedding=None,
            query_text="x",
            repo="org/r",
            status="draft",
        )
        filters = raw.search.await_args.kwargs["body"]["query"]["bool"]["filter"]
        keys = {next(iter(f["term"].keys())) for f in filters}
        assert keys == {"spec_repo", "status"}

    async def test_swallows_search_errors(self):
        backend, raw = _opensearch_backend_with_response({})
        raw.search = AsyncMock(side_effect=RuntimeError("boom"))
        results = await backend.hybrid_search(query_embedding=None, query_text="x")
        assert results == []

    async def test_returns_empty_when_no_query_and_no_embedding(self):
        """Filter-only query with no scoring clauses must NOT fall through to
        an OpenSearch match-all — would return arbitrary documents. Same
        semantics as Postgres backend: no query → no results."""
        backend, raw = _opensearch_backend_with_response({"hits": {"hits": []}})
        results = await backend.hybrid_search(
            query_embedding=None,
            query_text="",
            repo="org/r",  # filter present but no scoring clause
        )
        assert results == []
        # Critical: must not have called the underlying search at all.
        raw.search.assert_not_called()

    async def test_minimum_should_match_is_one(self):
        """Once we have at least one scoring clause, the bool query requires
        a match — not a filter-pass-through."""
        backend, raw = _opensearch_backend_with_response({"hits": {"hits": []}})
        await backend.hybrid_search(query_embedding=None, query_text="auth")
        body = raw.search.await_args.kwargs["body"]
        assert body["query"]["bool"]["minimum_should_match"] == 1


class TestOpenSearchBackendFacets:
    async def test_returns_status_and_repo_buckets(self):
        backend, _raw = _opensearch_backend_with_response(
            {
                "aggregations": {
                    "status": {
                        "buckets": [
                            {"key": "draft", "doc_count": 3},
                            {"key": "in_progress", "doc_count": 2},
                        ]
                    },
                    "repo": {
                        "buckets": [
                            {"key": "org/r1", "doc_count": 5},
                            {"key": "org/r2", "doc_count": 1},
                        ]
                    },
                }
            }
        )
        result = await backend.get_facet_counts()
        assert result == {
            "status": {"draft": 3, "in_progress": 2},
            "repo": {"org/r1": 5, "org/r2": 1},
            "team": {},
            "tags": {},
        }

    async def test_repo_filter_applied(self):
        backend, raw = _opensearch_backend_with_response({"aggregations": {}})
        await backend.get_facet_counts(repo="org/r1")
        body = raw.search.await_args.kwargs["body"]
        assert body["query"] == {"bool": {"filter": [{"term": {"repo": "org/r1"}}]}}


class TestOpenSearchBackendIndexedPaths:
    async def test_groups_by_repo_path(self):
        backend, _raw = _opensearch_backend_with_response(
            {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "repo": "org/r",
                                "path": "specs/a.md",
                                "synced_at": "2026-04-30T00:00:00Z",
                                "has_embedding": True,
                            }
                        }
                    ]
                }
            }
        )
        result = await backend.get_indexed_paths()
        assert "org/r/specs/a.md" in result
        assert result["org/r/specs/a.md"]["has_embedding"] is True
        assert result["org/r/specs/a.md"]["indexed_at"] == "2026-04-30T00:00:00Z"

    async def test_request_does_not_fetch_embedding_vector(self):
        """Regression: get_indexed_paths must NOT include the embedding field
        in _source — it ships ~4KB per doc just to compute a boolean. The
        materialised has_embedding flag is what we read instead."""
        backend, raw = _opensearch_backend_with_response({"hits": {"hits": []}})
        await backend.get_indexed_paths()
        body = raw.search.await_args.kwargs["body"]
        assert "embedding" not in body["_source"]
        assert "has_embedding" in body["_source"]

    async def test_empty_response(self):
        backend, _raw = _opensearch_backend_with_response({"hits": {"hits": []}})
        assert await backend.get_indexed_paths() == {}

    async def test_clear_scroll_called_when_scroll_raises_midway(self):
        """Regression: scroll() failure mid-iteration must still clear the
        scroll context. Otherwise it pins cluster memory until TTL expires
        and repeated failures exhaust the open-scroll limit."""
        raw = MagicMock()
        # Initial search returns a scroll_id and a full page of hits, so the
        # loop will call scroll() to fetch the next page.
        raw.search = AsyncMock(
            return_value={
                "_scroll_id": "scroll-123",
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "repo": "org/r",
                                "path": "a.md",
                                "synced_at": "2026-04-30T00:00:00Z",
                                "has_embedding": False,
                            }
                        }
                    ]
                },
            }
        )
        # scroll() blows up — must not prevent clear_scroll from running.
        raw.scroll = AsyncMock(side_effect=RuntimeError("network reset"))
        raw.clear_scroll = AsyncMock()

        client = MagicMock()
        client.is_enabled = True
        client._client = raw
        client.specs_index = "canon-specs"

        backend = OpenSearchBackend(client)
        # Must not raise — backend swallows.
        result = await backend.get_indexed_paths()
        # We got the one page that was returned before scroll() exploded.
        assert result == {
            "org/r/a.md": {
                "indexed_at": "2026-04-30T00:00:00Z",
                "has_embedding": False,
            }
        }
        # The leak fix is the critical assertion:
        raw.clear_scroll.assert_awaited_once_with(scroll_id="scroll-123")


class TestBuildBackend:
    def test_returns_opensearch_when_enabled(self):
        index = MagicMock()
        os_client = MagicMock()
        os_client.is_enabled = True
        backend = build_backend(
            search_index=index,
            opensearch_client=os_client,
            opensearch_enabled=True,
        )
        assert isinstance(backend, OpenSearchBackend)

    def test_returns_postgres_when_opensearch_disabled(self):
        index = MagicMock()
        os_client = MagicMock()
        os_client.is_enabled = False
        backend = build_backend(
            search_index=index,
            opensearch_client=os_client,
            opensearch_enabled=False,
        )
        assert isinstance(backend, PostgresSearchBackend)

    def test_falls_back_to_postgres_when_opensearch_unconfigured(self):
        index = MagicMock()
        os_client = MagicMock()
        os_client.is_enabled = False
        backend = build_backend(
            search_index=index,
            opensearch_client=os_client,
            opensearch_enabled=True,  # flag on but client not enabled
        )
        assert isinstance(backend, PostgresSearchBackend)

    def test_returns_none_when_no_index_or_opensearch(self):
        backend = build_backend(
            search_index=None,
            opensearch_client=None,
            opensearch_enabled=False,
        )
        assert backend is None


class TestOpenSearchHighlighting:
    async def test_request_includes_highlight_block(self):
        backend, raw = _opensearch_backend_with_response({"hits": {"hits": []}})
        await backend.hybrid_search(query_embedding=None, query_text="auth")
        body = raw.search.await_args.kwargs["body"]
        assert "highlight" in body
        assert "body" in body["highlight"]["fields"]
        assert "heading" in body["highlight"]["fields"]
        assert body["highlight"]["pre_tags"] == ["<mark>"]

    async def test_request_uses_html_encoder_for_xss_safety(self):
        """encoder=html ensures fragment content is HTML-escaped before the
        sentinel <mark> tags are wrapped, so a spec body containing literal
        <script> or </mark> can't break out into the consumer's DOM."""
        backend, raw = _opensearch_backend_with_response({"hits": {"hits": []}})
        await backend.hybrid_search(query_embedding=None, query_text="auth")
        body = raw.search.await_args.kwargs["body"]
        assert body["highlight"]["encoder"] == "html"

    async def test_highlights_surfaced_on_results(self):
        backend, _raw = _opensearch_backend_with_response(
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "x",
                            "_score": 1.0,
                            "_source": {
                                "_spec_doc_id": "o/r:p.md",
                                "spec_repo": "o/r",
                                "spec_path": "p.md",
                                "spec_title": "T",
                                "heading": "Auth",
                                "body": "login flow",
                                "status": "draft",
                            },
                            "highlight": {
                                "body": [
                                    "a <mark>match</mark> here",
                                    "another <mark>match</mark>",
                                ],
                                "heading": ["<mark>Auth</mark>"],
                            },
                        }
                    ]
                }
            }
        )
        results = await backend.hybrid_search(query_embedding=None, query_text="match")
        # All fragments from both fields are surfaced (2 body + 1 heading = 3).
        assert results[0].highlights is not None
        assert len(results[0].highlights) == 3
        assert "a <mark>match</mark> here" in results[0].highlights
        assert "another <mark>match</mark>" in results[0].highlights
        assert "<mark>Auth</mark>" in results[0].highlights

    async def test_highlights_none_when_no_field_matches(self):
        backend, _raw = _opensearch_backend_with_response(
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "x",
                            "_score": 1.0,
                            "_source": {
                                "_spec_doc_id": "o/r:p.md",
                                "spec_repo": "o/r",
                                "spec_path": "p.md",
                                "spec_title": "T",
                                "heading": "Auth",
                                "body": "login flow",
                                "status": "draft",
                            },
                        }
                    ]
                }
            }
        )
        results = await backend.hybrid_search(query_embedding=None, query_text="x")
        assert results[0].highlights is None


class TestOpenSearchTeamTagFacets:
    async def test_request_includes_team_and_tags_aggs(self):
        backend, raw = _opensearch_backend_with_response({"aggregations": {}})
        await backend.get_facet_counts()
        aggs = raw.search.await_args.kwargs["body"]["aggs"]
        assert "team" in aggs
        assert "tags" in aggs

    async def test_returns_team_and_tags_buckets(self):
        backend, _raw = _opensearch_backend_with_response(
            {
                "aggregations": {
                    "status": {"buckets": []},
                    "repo": {"buckets": []},
                    "team": {
                        "buckets": [
                            {"key": "platform", "doc_count": 4},
                            {"key": "growth", "doc_count": 1},
                        ]
                    },
                    "tags": {
                        "buckets": [
                            {"key": "infra", "doc_count": 3},
                            {"key": "auth", "doc_count": 2},
                        ]
                    },
                }
            }
        )
        result = await backend.get_facet_counts()
        assert result["team"] == {"platform": 4, "growth": 1}
        assert result["tags"] == {"infra": 3, "auth": 2}


class TestOpenSearchGetRelated:
    async def test_returns_empty_when_disabled(self):
        client = MagicMock()
        client.is_enabled = False
        backend = OpenSearchBackend(client)
        assert await backend.get_related(repo="o/r", path="p.md") == []

    async def test_returns_empty_when_source_missing(self):
        raw = MagicMock()
        raw.get = AsyncMock(return_value={"found": False})
        client = MagicMock()
        client.is_enabled = True
        client._client = raw
        client.specs_index = "canon-specs"
        backend = OpenSearchBackend(client)
        assert await backend.get_related(repo="o/r", path="p.md") == []

    async def test_returns_empty_when_source_lacks_embedding(self):
        raw = MagicMock()
        raw.get = AsyncMock(return_value={"found": True, "_source": {}})
        client = MagicMock()
        client.is_enabled = True
        client._client = raw
        client.specs_index = "canon-specs"
        backend = OpenSearchBackend(client)
        assert await backend.get_related(repo="o/r", path="p.md") == []

    async def test_runs_knn_and_excludes_source(self):
        raw = MagicMock()
        raw.get = AsyncMock(return_value={"found": True, "_source": {"embedding": [0.1, 0.2]}})
        raw.search = AsyncMock(
            return_value={
                "hits": {
                    "hits": [
                        {
                            "_score": 0.92,
                            "_source": {
                                "repo": "o/r",
                                "path": "other.md",
                                "title": "Other Spec",
                            },
                        }
                    ]
                }
            }
        )
        client = MagicMock()
        client.is_enabled = True
        client._client = raw
        client.specs_index = "canon-specs"

        backend = OpenSearchBackend(client)
        results = await backend.get_related(repo="o/r", path="p.md", limit=5)

        assert len(results) == 1
        assert isinstance(results[0], RelatedSpec)
        assert results[0].path == "other.md"
        assert results[0].title == "Other Spec"

        body = raw.search.await_args.kwargs["body"]
        knn = body["query"]["bool"]["must"][0]["knn"]
        assert knn["embedding"]["vector"] == [0.1, 0.2]
        must_not = body["query"]["bool"]["must_not"]
        assert {"ids": {"values": ["o/r:p.md"]}} in must_not
        # Tenant scope: owner filter sits INSIDE the knn block so it acts
        # as a pre-filter during ANN traversal, not a post-filter that
        # could leave zero results when nearest k all belong to other orgs.
        assert knn["embedding"]["filter"] == {"term": {"owner": "o"}}

    async def test_knn_filtered_to_source_owner(self):
        """Cross-tenant guard: a caller in org-a using their own spec as a
        kNN pivot must NOT receive org-b results. Owner filter must be a
        knn pre-filter (not a bool post-filter) so we don't get zero
        results when the unfiltered nearest k all belong to other orgs."""
        raw = MagicMock()
        raw.get = AsyncMock(return_value={"found": True, "_source": {"embedding": [0.1, 0.2]}})
        raw.search = AsyncMock(return_value={"hits": {"hits": []}})
        client = MagicMock()
        client.is_enabled = True
        client._client = raw
        client.specs_index = "canon-specs"

        backend = OpenSearchBackend(client)
        await backend.get_related(repo="org-a/r", path="p.md")

        body = raw.search.await_args.kwargs["body"]
        knn = body["query"]["bool"]["must"][0]["knn"]
        assert knn["embedding"]["filter"] == {"term": {"owner": "org-a"}}
        # The owner filter must NOT also live in bool.filter — that would
        # be redundant at best, post-filter at worst.
        assert "filter" not in body["query"]["bool"]

    async def test_returns_empty_when_knn_filters_to_zero_hits(self):
        """Small corpus where the only candidate is the source spec itself
        — must_not excludes it, so the post-filter result is empty."""
        raw = MagicMock()
        raw.get = AsyncMock(return_value={"found": True, "_source": {"embedding": [0.1, 0.2]}})
        raw.search = AsyncMock(return_value={"hits": {"hits": []}})
        client = MagicMock()
        client.is_enabled = True
        client._client = raw
        client.specs_index = "canon-specs"

        backend = OpenSearchBackend(client)
        assert await backend.get_related(repo="o/r", path="p.md") == []
