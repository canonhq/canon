"""OpenSearch client wrapping opensearch-py for spec/section indexing."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 1024

SPECS_MAPPING: dict[str, Any] = {
    "properties": {
        "repo": {"type": "keyword"},
        "owner": {"type": "keyword"},
        "path": {"type": "keyword"},
        "title": {"type": "text", "analyzer": "standard"},
        "status": {"type": "keyword"},
        "team": {"type": "keyword"},
        "tags": {"type": "keyword"},
        "doc_type": {"type": "keyword"},
        "raw_markdown": {"type": "text", "analyzer": "standard"},
        "content_hash": {"type": "keyword"},
        "synced_at": {"type": "date"},
        # Per-spec ai_exposure override from frontmatter. Allows
        # find_related_specs to filter "none"-tagged specs out of result
        # lists without a per-result content_cache lookup. Empty string
        # means "no override; falls back to repo-level default".
        "ai_exposure": {"type": "keyword"},
        # Cheap boolean derived from embedding presence at index time.
        # `get_indexed_paths` reads this instead of the full vector — fetching
        # `embedding` over the wire just to compute a flag transfers ~4KB per
        # doc and crushes scroll bandwidth at scale.
        "has_embedding": {"type": "boolean"},
        "embedding": {
            "type": "knn_vector",
            "dimension": EMBEDDING_DIMENSIONS,
            "method": {"name": "hnsw", "engine": "nmslib"},
        },
    }
}

SECTIONS_MAPPING: dict[str, Any] = {
    "properties": {
        # Foreign key to canon-specs._id. Must be `keyword` so the term
        # query in delete_sections_for_spec / delete_repo matches the
        # literal id; without an explicit mapping OpenSearch dynamic-maps
        # it as text+keyword and the term query silently no-ops.
        "_spec_doc_id": {"type": "keyword"},
        "spec_repo": {"type": "keyword"},
        "spec_path": {"type": "keyword"},
        "spec_title": {"type": "text"},
        "heading": {"type": "text", "analyzer": "standard"},
        "level": {"type": "integer"},
        "body": {"type": "text", "analyzer": "standard"},
        "status": {"type": "keyword"},
        "ticket_ref": {"type": "keyword"},
        "team": {"type": "keyword"},
        "tags": {"type": "keyword"},
        "embedding": {
            "type": "knn_vector",
            "dimension": EMBEDDING_DIMENSIONS,
            "method": {"name": "hnsw", "engine": "nmslib"},
        },
    }
}

INDEX_SETTINGS: dict[str, Any] = {"index": {"knn": True}}


class OpenSearchUnavailableError(Exception):
    """Raised when the OpenSearch client is called but not configured."""

    def __init__(self) -> None:
        super().__init__("OpenSearch is not enabled or configured")


class OpenSearchClient:
    """Async OpenSearch client for spec and section indexing.

    No-ops when ``enabled=False`` or no URL is configured. Methods that
    return data raise :class:`OpenSearchUnavailableError` in that case;
    write methods log and skip.
    """

    def __init__(
        self,
        *,
        url: str = "",
        username: str = "",
        password: str = "",
        specs_index: str = "canon-specs",
        sections_index: str = "canon-sections",
        enabled: bool = False,
        verify_certs: bool = True,
    ) -> None:
        self._client: Any = None
        self._enabled = enabled and bool(url)
        self._url = url
        self._specs_index = specs_index
        self._sections_index = sections_index

        if not self._enabled:
            return

        try:
            from opensearchpy import AsyncOpenSearch
        except ImportError:
            # Distinct error path so a deploy missing the `cloud` extra is
            # operator-visible: same flag-on-but-disabled symptom as a
            # generic init failure, but the remediation is different
            # ("install canon[cloud]" vs "check the cluster").
            logger.error(
                "OPENSEARCH_ENABLED=true but opensearch-py is not installed — "
                "install canon[cloud] or unset the flag",
                exc_info=True,
            )
            self._client = None
            self._enabled = False
            return

        try:
            auth = (username, password) if username else None
            self._client = AsyncOpenSearch(
                hosts=[url],
                http_auth=auth,
                use_ssl=url.startswith("https://"),
                verify_certs=verify_certs,
                ssl_show_warn=verify_certs,
            )
        except Exception:
            logger.warning("Failed to initialise OpenSearch client", exc_info=True)
            self._client = None
            self._enabled = False

    @property
    def is_enabled(self) -> bool:
        """Whether the client is configured and ready to make calls."""
        return self._enabled and self._client is not None

    @property
    def specs_index(self) -> str:
        return self._specs_index

    @property
    def sections_index(self) -> str:
        return self._sections_index

    async def close(self) -> None:
        # Wrapped so a teardown failure (transport already gone, network
        # error mid-shutdown) doesn't propagate and abort the rest of the
        # lifespan close chain (db_pool, github client, auth_http, etc.).
        if self._client is None:
            return
        try:
            await self._client.close()
        except Exception:
            logger.warning("OpenSearch close failed", exc_info=True)

    async def ping(self) -> bool:
        """Health check — returns True if the cluster responds."""
        if not self.is_enabled:
            return False
        try:
            return bool(await self._client.ping())
        except Exception:
            logger.debug("OpenSearch ping failed", exc_info=True)
            return False

    async def ensure_indexes(self) -> None:
        """Create canon-specs and canon-sections indexes if they don't exist.

        Idempotent — safe to call on every startup.
        """
        if not self.is_enabled:
            return

        await self._ensure_index(self._specs_index, SPECS_MAPPING)
        await self._ensure_index(self._sections_index, SECTIONS_MAPPING)

    async def _ensure_index(self, name: str, mapping: dict[str, Any]) -> None:
        try:
            exists = await self._client.indices.exists(index=name)
        except Exception:
            logger.warning("Failed to check OpenSearch index %s", name, exc_info=True)
            return

        if exists:
            return

        body = {"settings": INDEX_SETTINGS, "mappings": mapping}
        try:
            await self._client.indices.create(index=name, body=body)
            logger.info("Created OpenSearch index %s", name)
        except Exception:
            logger.warning("Failed to create OpenSearch index %s", name, exc_info=True)

    async def index_spec(self, *, doc_id: str, document: dict[str, Any]) -> None:
        """Index a single spec document. No-op when disabled."""
        if not self.is_enabled:
            return
        try:
            await self._client.index(
                index=self._specs_index,
                id=doc_id,
                body=document,
                refresh=False,
            )
        except Exception:
            logger.warning(
                "Failed to index spec %s into %s", doc_id, self._specs_index, exc_info=True
            )

    async def index_sections(self, sections: list[dict[str, Any]]) -> bool:
        """Bulk-index a list of section documents. No-op when disabled.

        Each section dict must include an ``id`` field used as the document id.

        Returns True when the bulk write completed AND every item succeeded;
        False when the bulk call raised OR any per-item operation reported
        an error. The latter is critical: OpenSearch's _bulk endpoint
        returns HTTP 200 with ``{"errors": true, "items": [...]}`` on
        partial failure — without inspecting that flag, the indexer would
        proceed to update the spec doc's content_hash, leave the missing
        sections behind, and the reconcile cron would never recover the
        spec because the hashes match.
        """
        if not self.is_enabled or not sections:
            return True

        actions: list[dict[str, Any]] = []
        for section in sections:
            section_id = section.get("id")
            if section_id is None:
                continue
            actions.append({"index": {"_index": self._sections_index, "_id": section_id}})
            actions.append({k: v for k, v in section.items() if k != "id"})

        if not actions:
            return True

        try:
            response = await self._client.bulk(body=actions, refresh=False)
        except Exception:
            logger.warning(
                "Failed to bulk-index %d sections into %s",
                len(sections),
                self._sections_index,
                exc_info=True,
            )
            return False

        if response.get("errors"):
            failed = sum(
                1
                for item in response.get("items", [])
                if next(iter(item.values()), {}).get("error") is not None
            )
            logger.warning(
                "Bulk section write reported %d item error(s) for %s",
                failed,
                self._sections_index,
            )
            return False
        return True

    async def delete_repo(self, repo: str) -> None:
        """Remove all spec and section docs for a given repo. No-op when disabled."""
        if not self.is_enabled:
            return
        for index in (self._specs_index, self._sections_index):
            field = "repo" if index == self._specs_index else "spec_repo"
            try:
                await self._client.delete_by_query(
                    index=index,
                    body={"query": {"term": {field: repo}}},
                    refresh=False,
                    conflicts="proceed",
                )
            except Exception:
                logger.warning("Failed to delete repo %s from index %s", repo, index, exc_info=True)

    async def delete_sections_for_spec(self, doc_id: str) -> bool:
        """Delete all section documents belonging to a given spec doc_id.

        Returns True when the delete completed (or the client is disabled);
        False when delete_by_query raised. Same contract as
        :meth:`index_sections` — callers use the success signal to gate
        the spec-doc write that follows.
        """
        if not self.is_enabled:
            return True
        try:
            await self._client.delete_by_query(
                index=self._sections_index,
                body={"query": {"term": {"_spec_doc_id": doc_id}}},
                refresh=False,
                conflicts="proceed",
            )
            return True
        except Exception:
            logger.warning(
                "Failed to delete sections for spec %s from %s",
                doc_id,
                self._sections_index,
                exc_info=True,
            )
            return False

    async def delete_spec(self, doc_id: str) -> None:
        """Delete a spec doc and all its sections. No-op when disabled."""
        if not self.is_enabled:
            return

        try:
            await self._client.delete(
                index=self._specs_index,
                id=doc_id,
                ignore=[404],
            )
        except Exception:
            logger.warning(
                "Failed to delete spec %s from %s", doc_id, self._specs_index, exc_info=True
            )

        await self.delete_sections_for_spec(doc_id)

    async def list_spec_hashes(self, repo: str | None = None) -> dict[str, str]:
        """Return ``{doc_id: content_hash}`` for indexed specs.

        Used by the reconcile cron to diff against Postgres. Filters by ``repo``
        when provided. Uses scroll for large result sets.
        """
        if not self.is_enabled:
            return {}

        query: dict[str, Any] = {"match_all": {}} if not repo else {"term": {"repo": repo}}
        body = {
            "size": 1000,
            "_source": ["content_hash"],
            "query": query,
            "sort": [{"_doc": "asc"}],
        }
        result: dict[str, str] = {}
        # Hoist scroll_id so `finally` can clear it even if scroll() raises
        # mid-iteration; otherwise the context leaks until its TTL expires
        # and repeated failures exhaust the open-scroll limit.
        scroll_id: str | None = None
        try:
            response = await self._client.search(index=self._specs_index, body=body, scroll="2m")
            scroll_id = response.get("_scroll_id")
            hits = response.get("hits", {}).get("hits", [])
            while hits:
                for hit in hits:
                    src = hit.get("_source") or {}
                    result[hit["_id"]] = src.get("content_hash", "")
                if not scroll_id:
                    break
                response = await self._client.scroll(scroll_id=scroll_id, scroll="2m")
                scroll_id = response.get("_scroll_id")
                hits = response.get("hits", {}).get("hits", [])
        except Exception:
            # Re-raise on any scroll failure rather than returning a partial
            # dict. The reconcile cron uses the result to compute orphans
            # (specs in OS but not in PG) — a truncated view causes mass
            # delete of valid documents. Caller should abort the reconcile
            # run on failure; @tracked_cron will record the failure.
            logger.warning("Failed to list spec hashes from OpenSearch", exc_info=True)
            raise
        finally:
            if scroll_id:
                try:
                    await self._client.clear_scroll(scroll_id=scroll_id)
                except Exception:
                    logger.warning("Failed to clear scroll context", exc_info=True)
        return result

    async def bulk_index(self, actions: list[dict[str, Any]]) -> None:
        """Generic bulk write. ``actions`` is a list of opensearch _bulk API rows.

        Caller is responsible for action/document pairs (e.g.
        ``[{"index": {"_index": "x", "_id": "1"}}, {"field": "value"}, ...]``).
        """
        if not self.is_enabled or not actions:
            return
        try:
            response = await self._client.bulk(body=actions, refresh=False)
        except Exception:
            logger.warning("OpenSearch bulk write failed (%d actions)", len(actions), exc_info=True)
            return

        if response.get("errors"):
            failed = sum(
                1
                for item in response.get("items", [])
                if next(iter(item.values()), {}).get("error") is not None
            )
            logger.warning(
                "Bulk write reported %d item error(s) out of %d actions",
                failed,
                len(actions) // 2,
            )


def build_client_from_settings(settings: Any) -> OpenSearchClient:
    """Construct an OpenSearchClient from app settings.

    Reads ``opensearch_*`` fields off the Pydantic Settings object.
    """
    password = settings.opensearch_password
    if hasattr(password, "get_secret_value"):
        password = password.get_secret_value()

    # Catch the easy misconfig where the operator flipped the flag but
    # forgot the URL — without this warning the resulting silent-disable
    # is indistinguishable from intentional disablement.
    if settings.opensearch_enabled and not settings.opensearch_url:
        logger.warning("OPENSEARCH_ENABLED=true but OPENSEARCH_URL is empty — client disabled")

    return OpenSearchClient(
        url=settings.opensearch_url,
        username=settings.opensearch_username,
        password=password or "",
        specs_index=settings.opensearch_specs_index,
        sections_index=settings.opensearch_sections_index,
        enabled=settings.opensearch_enabled,
    )
