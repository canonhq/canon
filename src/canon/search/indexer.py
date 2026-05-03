"""Bridge between parsed SpecDocuments and the search index."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from ..parser.classify import classify_doc_type
from ..parser.models import SpecSection

logger = logging.getLogger(__name__)


def flatten_sections(sections: list[SpecSection]) -> list[dict]:
    """Recursively flatten nested SpecSections into flat dicts.

    Returns dicts with keys: heading, level, body, status, ticket_ref.
    """
    result: list[dict] = []
    for section in sections:
        ticket_ref = ""
        if section.ticket_link:
            ticket_ref = section.ticket_link.ticket_id

        entry: dict = {
            "heading": section.title,
            "level": section.depth,
            "body": section.content,
            "status": section.status.state,
            "ticket_ref": ticket_ref,
        }
        if section.delta:
            entry["delta"] = section.delta

        result.append(entry)

        if section.children:
            result.extend(flatten_sections(section.children))

    return result


def opensearch_doc_id(repo: str, path: str) -> str:
    """Stable OpenSearch document id for a spec."""
    return f"{repo}:{path}"


async def index_spec(
    *,
    doc,
    repo: str,
    search_index,
    embed_client=None,
    commit_sha: str = "",
    opensearch_client=None,
) -> int:
    """Embed and upsert a single SpecDocument into the search index.

    Args:
        doc: SpecDocument from the parser.
        repo: Full repo name (e.g. "org/repo").
        search_index: SearchIndex instance.
        embed_client: Optional EmbeddingClient. If None or unavailable,
            upserts with None embeddings (BM25 still works).
        commit_sha: Git commit SHA for tracking.
        opensearch_client: Optional OpenSearchClient. When enabled, the
            spec and its sections are also dual-written to OpenSearch.
            Failures are logged + swallowed; the reconcile cron catches up.

    Returns:
        The document ID from upsert_spec.
    """
    flat_sections = flatten_sections(doc.sections)

    # Build texts for embedding: doc summary + each section
    doc_text = doc.frontmatter.title
    if flat_sections:
        headings = [s["heading"] for s in flat_sections if s["heading"]]
        if headings:
            doc_text += "\n" + "\n".join(headings)

    section_texts = [
        f"{s['heading']}\n{s['body']}" if s["heading"] else s["body"] for s in flat_sections
    ]

    # Try to compute embeddings
    doc_embedding: list[float] | None = None
    section_embeddings: list[list[float] | None] = [None] * len(flat_sections)

    if embed_client is not None and getattr(embed_client, "is_available", False):
        try:
            all_texts = [doc_text, *section_texts]
            all_embeddings = embed_client.embed_documents(all_texts)
            doc_embedding = all_embeddings[0]
            section_embeddings = all_embeddings[1:]
        except Exception:
            logger.warning(
                "Embedding failed for %s:%s — upserting without embeddings",
                repo,
                doc.file_path,
                exc_info=True,
            )

    # Attach embeddings to sections
    sections_with_embeddings = []
    for i, s in enumerate(flat_sections):
        s_copy = dict(s)
        s_copy["embedding"] = section_embeddings[i] if i < len(section_embeddings) else None
        sections_with_embeddings.append(s_copy)

    doc_type = classify_doc_type(doc.file_path)

    doc_id = await search_index.upsert_spec(
        repo=repo,
        path=doc.file_path,
        title=doc.frontmatter.title,
        status=doc.frontmatter.status,
        content=doc.raw,
        doc_embedding=doc_embedding,
        sections=sections_with_embeddings,
        commit_sha=commit_sha,
        doc_type=doc_type,
        ai_exposure=getattr(doc.frontmatter, "ai_exposure", None) or "",
        tags=list(getattr(doc.frontmatter, "tags", []) or []),
    )

    logger.info(
        "Indexed %s:%s (doc_id=%d, sections=%d, embeddings=%s)",
        repo,
        doc.file_path,
        doc_id,
        len(flat_sections),
        "yes" if doc_embedding is not None else "no",
    )

    if opensearch_client is not None and getattr(opensearch_client, "is_enabled", False):
        await _index_spec_in_opensearch(
            client=opensearch_client,
            doc=doc,
            repo=repo,
            doc_type=doc_type,
            doc_embedding=doc_embedding,
            flat_sections=flat_sections,
            section_embeddings=section_embeddings,
        )

    return doc_id


async def _index_spec_in_opensearch(
    *,
    client,
    doc,
    repo: str,
    doc_type: str,
    doc_embedding: list[float] | None,
    flat_sections: list[dict],
    section_embeddings: list[list[float] | None],
) -> None:
    """Dual-write a spec and its sections into OpenSearch.

    Uses delete-then-bulk-write for sections so removed sections don't linger.
    All exceptions are swallowed by the underlying client methods.
    """
    spec_id = opensearch_doc_id(repo, doc.file_path)
    owner = repo.split("/", 1)[0] if "/" in repo else repo
    raw = doc.raw or ""
    # Same 16-char truncation that ContentSyncEngine.sync_spec writes into
    # spec_documents.content_hash. The reconcile cron compares OS vs PG
    # hashes for equality — they must agree on length or every run reindexes
    # every spec.
    content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    synced_at = datetime.now(UTC).isoformat()

    spec_doc = {
        "repo": repo,
        "owner": owner,
        "path": doc.file_path,
        "title": doc.frontmatter.title,
        "status": doc.frontmatter.status,
        "team": getattr(doc.frontmatter, "team", "") or "",
        "tags": list(getattr(doc.frontmatter, "tags", []) or []),
        "doc_type": doc_type,
        "raw_markdown": raw,
        "content_hash": content_hash,
        "synced_at": synced_at,
        # Per-spec ai_exposure override (frontmatter) — used by
        # find_related_specs result filtering so a spec with
        # `ai_exposure: none` doesn't leak title/path through neighbour
        # lists. Empty string → no override; falls back to repo default.
        "ai_exposure": getattr(doc.frontmatter, "ai_exposure", None) or "",
        # Materialised flag so get_indexed_paths can avoid fetching the
        # full vector just to compute presence.
        "has_embedding": doc_embedding is not None,
    }
    if doc_embedding is not None:
        spec_doc["embedding"] = doc_embedding

    section_docs = []
    for i, section in enumerate(flat_sections):
        section_doc = {
            "id": f"{spec_id}:{i}",
            "_spec_doc_id": spec_id,
            "spec_repo": repo,
            "spec_path": doc.file_path,
            "spec_title": doc.frontmatter.title,
            "heading": section["heading"],
            "level": section["level"],
            "body": section["body"],
            "status": section["status"],
            "ticket_ref": section.get("ticket_ref", ""),
            "team": spec_doc["team"],
            "tags": spec_doc["tags"],
        }
        embedding = section_embeddings[i] if i < len(section_embeddings) else None
        if embedding is not None:
            section_doc["embedding"] = embedding
        section_docs.append(section_doc)

    # Section writes happen BEFORE the spec-doc write that updates
    # content_hash. If the bulk section write (or the section delete) fails,
    # the OS spec doc retains its OLD content_hash — the reconcile cron
    # then sees a Postgres-vs-OpenSearch mismatch and retries on the next
    # run. The previous spec-doc-first ordering allowed a "matched hash,
    # missing sections" state that reconcile would never recover.
    delete_ok = await client.delete_sections_for_spec(spec_id)
    sections_ok = await client.index_sections(section_docs)
    if not (delete_ok and sections_ok):
        logger.warning(
            "OpenSearch sections write failed for %s — skipping spec-doc "
            "update so reconcile can retry",
            spec_id,
        )
        return

    await client.index_spec(doc_id=spec_id, document=spec_doc)
