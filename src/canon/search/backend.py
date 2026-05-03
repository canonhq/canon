"""SearchBackend protocol — abstracts the search query path.

Two implementations:
- :class:`PostgresSearchBackend` wraps the existing :class:`SearchIndex`
  (pgvector + ParadeDB BM25). Default.
- :class:`OpenSearchBackend` wraps :class:`OpenSearchClient` (BM25 + kNN).
  Selected when ``OPENSEARCH_ENABLED`` is set.

Write operations stay on :class:`SearchIndex` directly (Postgres remains
source of truth during the migration).
"""

from __future__ import annotations

import logging
from typing import Protocol

from .index import RelatedSpec, SearchResult

logger = logging.getLogger(__name__)


class SearchBackend(Protocol):
    """Protocol for hybrid search query execution."""

    async def hybrid_search(
        self,
        *,
        query_embedding: list[float] | None,
        query_text: str,
        repo: str | None = None,
        status: str | None = None,
        limit: int = 20,
        raise_on_error: bool = False,
    ) -> list[SearchResult]: ...

    async def get_facet_counts(
        self,
        *,
        repo: str | None = None,
    ) -> dict[str, dict[str, int]]: ...

    async def get_indexed_paths(self, repo: str | None = None) -> dict[str, dict]: ...

    async def get_related(
        self,
        *,
        repo: str,
        path: str,
        limit: int = 10,
    ) -> list[RelatedSpec]: ...


class PostgresSearchBackend:
    """SearchBackend wrapper around :class:`SearchIndex`. No behavior change."""

    def __init__(self, search_index) -> None:
        self._index = search_index

    async def hybrid_search(
        self,
        *,
        query_embedding: list[float] | None,
        query_text: str,
        repo: str | None = None,
        status: str | None = None,
        limit: int = 20,
        raise_on_error: bool = False,
    ) -> list[SearchResult]:
        # SearchIndex propagates exceptions natively; raise_on_error is a no-op
        # here but kept on the signature for protocol parity with OpenSearchBackend.
        del raise_on_error
        return await self._index.hybrid_search(
            query_embedding=query_embedding,
            query_text=query_text,
            repo=repo,
            status=status,
            limit=limit,
        )

    async def get_facet_counts(
        self,
        *,
        repo: str | None = None,
    ) -> dict[str, dict[str, int]]:
        # Postgres spec_documents has no team/tags columns; we return empty
        # buckets so the response shape matches OpenSearchBackend.
        result = await self._index.get_facet_counts(repo=repo)
        result.setdefault("team", {})
        result.setdefault("tags", {})
        return result

    async def get_indexed_paths(self, repo: str | None = None) -> dict[str, dict]:
        return await self._index.get_indexed_paths(repo=repo)

    async def get_related(
        self,
        *,
        repo: str,
        path: str,
        limit: int = 10,
    ) -> list[RelatedSpec]:
        """kNN over pgvector ``spec_documents.embedding`` to find similar specs.

        Excludes the source spec from the result set. Follows the module-wide
        best-effort convention: any asyncpg failure is logged and an empty
        list returned, never raised.
        """
        pool = getattr(self._index, "_pool", None)
        if pool is None:
            logger.warning("PostgresSearchBackend.get_related: SearchIndex has no _pool attribute")
            return []

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT embedding FROM spec_documents WHERE repo = $1 AND path = $2",
                    repo,
                    path,
                )
                if row is None or row["embedding"] is None:
                    return []

                # Constrain kNN to specs in the same org so a caller can't
                # use their own spec as a pivot to discover other tenants'
                # spec titles/paths. SPLIT_PART equality is used instead of
                # `repo LIKE 'org/%'` because the LIKE pattern would treat
                # `%` in a malicious owner as a wildcard, expanding the
                # tenant scope to "any repo with a slash".
                owner = repo.split("/", 1)[0] if "/" in repo else repo
                rows = await conn.fetch(
                    """
                    SELECT repo, path, title, ai_exposure, tags
                    FROM spec_documents
                    WHERE embedding IS NOT NULL
                      AND NOT (repo = $1 AND path = $2)
                      AND SPLIT_PART(repo, '/', 1) = $5
                    ORDER BY embedding <=> $3
                    LIMIT $4
                    """,
                    repo,
                    path,
                    row["embedding"],
                    limit,
                    owner,
                )
        except Exception:
            logger.warning(
                "PostgresSearchBackend.get_related failed for %s:%s",
                repo,
                path,
                exc_info=True,
            )
            return []

        return [
            RelatedSpec(
                repo=r["repo"],
                path=r["path"],
                title=r["title"],
                ai_exposure=r["ai_exposure"] or "",
                tags=list(r["tags"] or []),
            )
            for r in rows
        ]


class OpenSearchBackend:
    """SearchBackend backed by an :class:`OpenSearchClient`.

    Implements hybrid BM25 + kNN search via an OpenSearch ``bool`` query that
    combines a ``match`` (BM25) clause with a ``knn`` clause; the cluster's
    native scoring sums the two, so we don't need a Postgres-style RRF shim.
    """

    # k for kNN; over-fetched so the bool query has more candidates to combine
    # with BM25 hits before returning ``size`` results.
    KNN_K = 100

    def __init__(self, client) -> None:
        self._client = client

    async def hybrid_search(
        self,
        *,
        query_embedding: list[float] | None,
        query_text: str,
        repo: str | None = None,
        status: str | None = None,
        limit: int = 20,
        raise_on_error: bool = False,
    ) -> list[SearchResult]:
        if not self._client.is_enabled:
            return []

        filters: list[dict] = []
        if repo:
            filters.append({"term": {"spec_repo": repo}})
        if status:
            filters.append({"term": {"status": status}})

        should: list[dict] = []
        if query_text:
            should.append({"match": {"body": {"query": query_text}}})
            should.append({"match": {"heading": {"query": query_text, "boost": 1.5}}})
        if query_embedding:
            should.append(
                {
                    "knn": {
                        "embedding": {
                            "vector": query_embedding,
                            "k": self.KNN_K,
                        }
                    }
                }
            )

        # A filter-only query (no should clauses) would degrade to filter+
        # match-all and return arbitrary documents with no scoring. Hybrid
        # search without a query has no defined semantics; bail.
        if not should:
            return []

        body = {
            "size": limit,
            "query": {
                "bool": {
                    "filter": filters,
                    "should": should,
                    "minimum_should_match": 1,
                }
            },
            "highlight": {
                # encoder=html escapes all HTML in fragment content before
                # the pre/post tags are wrapped, preventing XSS via spec
                # text containing literal <script>, </mark>, etc. Required
                # because the `highlights` field is propagated to MCP tool
                # responses and the admin parity API, where downstream
                # callers may render via innerHTML / v-html.
                "encoder": "html",
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
                "fields": {
                    "body": {"fragment_size": 160, "number_of_fragments": 2},
                    "heading": {"fragment_size": 80, "number_of_fragments": 1},
                },
            },
        }

        try:
            response = await self._client._client.search(  # type: ignore[attr-defined]
                index=self._client.sections_index, body=body
            )
        except Exception:
            logger.warning("OpenSearch hybrid_search failed", exc_info=True)
            if raise_on_error:
                raise
            return []

        results: list[SearchResult] = []
        for hit in response.get("hits", {}).get("hits", []):
            highlights: list[str] = []
            for field_hits in (hit.get("highlight") or {}).values():
                highlights.extend(field_hits)
            results.append(
                SearchResult(
                    section_id=_synth_int(hit["_id"]),
                    document_id=_synth_int(hit["_source"].get("_spec_doc_id", "")),
                    repo=hit["_source"].get("spec_repo", ""),
                    path=hit["_source"].get("spec_path", ""),
                    doc_title=hit["_source"].get("spec_title", ""),
                    heading=hit["_source"].get("heading", ""),
                    body=hit["_source"].get("body", ""),
                    status=hit["_source"].get("status", ""),
                    rrf_score=float(hit.get("_score", 0.0)),
                    highlights=highlights or None,
                )
            )
        return results

    async def get_facet_counts(
        self,
        *,
        repo: str | None = None,
    ) -> dict[str, dict[str, int]]:
        empty: dict[str, dict[str, int]] = {
            "status": {},
            "repo": {},
            "team": {},
            "tags": {},
        }
        if not self._client.is_enabled:
            return empty

        filters: list[dict] = []
        if repo:
            filters.append({"term": {"repo": repo}})

        body = {
            "size": 0,
            "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
            "aggs": {
                "status": {"terms": {"field": "status", "size": 100}},
                "repo": {"terms": {"field": "repo", "size": 200}},
                "team": {"terms": {"field": "team", "size": 100}},
                "tags": {"terms": {"field": "tags", "size": 200}},
            },
        }

        try:
            response = await self._client._client.search(  # type: ignore[attr-defined]
                index=self._client.specs_index, body=body
            )
        except Exception:
            logger.warning("OpenSearch get_facet_counts failed", exc_info=True)
            return empty

        aggs = response.get("aggregations", {})

        def _buckets(name: str) -> dict[str, int]:
            return {
                b["key"]: b["doc_count"]
                for b in aggs.get(name, {}).get("buckets", [])
                if b.get("key") not in (None, "")
            }

        return {
            "status": _buckets("status"),
            "repo": _buckets("repo"),
            "team": _buckets("team"),
            "tags": _buckets("tags"),
        }

    async def get_related(
        self,
        *,
        repo: str,
        path: str,
        limit: int = 10,
    ) -> list[RelatedSpec]:
        """kNN over the ``canon-specs`` ``embedding`` field.

        Fetches the source spec's embedding from the index, runs a kNN
        query, and excludes the source itself from the result set.
        """
        if not self._client.is_enabled:
            return []

        spec_id = f"{repo}:{path}"
        try:
            source_doc = await self._client._client.get(  # type: ignore[attr-defined]
                index=self._client.specs_index,
                id=spec_id,
                _source=["embedding"],
                ignore=[404],
            )
        except Exception:
            logger.warning(
                "OpenSearch get_related: source spec lookup failed for %s",
                spec_id,
                exc_info=True,
            )
            return []

        if not source_doc or not source_doc.get("found"):
            return []
        embedding = (source_doc.get("_source") or {}).get("embedding")
        if not embedding:
            return []

        # Constrain kNN to specs in the same org. The owner filter goes
        # INSIDE the knn clause (OpenSearch 2.4+ pre-filter) rather than
        # alongside it in `bool.filter`, which would post-filter the k
        # candidates and could return zero results when the source's
        # nearest neighbours all happen to belong to other tenants.
        owner = repo.split("/", 1)[0] if "/" in repo else repo
        body = {
            "size": limit,
            "query": {
                "bool": {
                    "must": [
                        {
                            "knn": {
                                "embedding": {
                                    "vector": embedding,
                                    "k": limit + 1,
                                    "filter": {"term": {"owner": owner}},
                                }
                            }
                        }
                    ],
                    "must_not": [{"ids": {"values": [spec_id]}}],
                }
            },
            "_source": ["repo", "path", "title", "ai_exposure", "tags"],
        }

        try:
            response = await self._client._client.search(  # type: ignore[attr-defined]
                index=self._client.specs_index, body=body
            )
        except Exception:
            logger.warning("OpenSearch get_related kNN search failed", exc_info=True)
            return []

        return [
            RelatedSpec(
                repo=hit["_source"].get("repo", ""),
                path=hit["_source"].get("path", ""),
                title=hit["_source"].get("title", ""),
                ai_exposure=hit["_source"].get("ai_exposure", "") or "",
                tags=list(hit["_source"].get("tags", []) or []),
            )
            for hit in response.get("hits", {}).get("hits", [])
        ]

    async def get_indexed_paths(self, repo: str | None = None) -> dict[str, dict]:
        if not self._client.is_enabled:
            return {}

        query: dict = {"term": {"repo": repo}} if repo else {"match_all": {}}
        body = {
            "size": 1000,
            # Read the materialised `has_embedding` flag instead of the full
            # vector — the vector is ~4KB per doc and we only need a boolean.
            "_source": ["repo", "path", "synced_at", "has_embedding"],
            "query": query,
            "sort": [{"_doc": "asc"}],
        }
        result: dict[str, dict] = {}
        # Hoist scroll_id so `finally` can clear it even if scroll()/search()
        # raises mid-iteration. Without this the leaked scroll context pins
        # OpenSearch cluster memory until its TTL expires (2m) and repeated
        # failures (e.g. during a re-index storm) exhaust the open-scroll
        # limit.
        scroll_id: str | None = None
        try:
            response = await self._client._client.search(  # type: ignore[attr-defined]
                index=self._client.specs_index, body=body, scroll="2m"
            )
            scroll_id = response.get("_scroll_id")
            hits = response.get("hits", {}).get("hits", [])
            while hits:
                for hit in hits:
                    src = hit.get("_source") or {}
                    repo_name = src.get("repo", "")
                    path = src.get("path", "")
                    if not repo_name or not path:
                        continue
                    result[f"{repo_name}/{path}"] = {
                        "indexed_at": src.get("synced_at"),
                        "has_embedding": bool(src.get("has_embedding")),
                    }
                if not scroll_id:
                    break
                response = await self._client._client.scroll(  # type: ignore[attr-defined]
                    scroll_id=scroll_id, scroll="2m"
                )
                scroll_id = response.get("_scroll_id")
                hits = response.get("hits", {}).get("hits", [])
        except Exception:
            logger.warning("OpenSearch get_indexed_paths failed", exc_info=True)
        finally:
            if scroll_id:
                try:
                    await self._client._client.clear_scroll(scroll_id=scroll_id)  # type: ignore[attr-defined]
                except Exception:
                    logger.warning("Failed to clear scroll context", exc_info=True)
        return result


def _synth_int(value: str) -> int:
    """Map an OpenSearch document _id (string) to a stable positive int.

    Used for the SearchResult.section_id / document_id fields, which are
    typed as ``int`` for legacy pgvector compatibility. Consumers do not
    use these as foreign keys; they exist for trace correlation only.
    """
    if not value:
        return 0
    return abs(hash(value)) % (2**31 - 1)


def build_backend(
    *, search_index, opensearch_client, opensearch_enabled: bool
) -> SearchBackend | None:
    """Pick the active SearchBackend based on configuration.

    Returns None if neither backend is available.
    """
    if opensearch_enabled and opensearch_client is not None and opensearch_client.is_enabled:
        return OpenSearchBackend(opensearch_client)
    if search_index is not None:
        return PostgresSearchBackend(search_index)
    return None
