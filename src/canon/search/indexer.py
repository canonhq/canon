"""Bridge between parsed SpecDocuments and the search index."""

from __future__ import annotations

import logging

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


async def index_spec(
    *,
    doc,
    repo: str,
    search_index,
    embed_client=None,
    commit_sha: str = "",
) -> int:
    """Embed and upsert a single SpecDocument into the search index.

    Args:
        doc: SpecDocument from the parser.
        repo: Full repo name (e.g. "org/repo").
        search_index: SearchIndex instance.
        embed_client: Optional EmbeddingClient. If None or unavailable,
            upserts with None embeddings (BM25 still works).
        commit_sha: Git commit SHA for tracking.

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
    )

    logger.info(
        "Indexed %s:%s (doc_id=%d, sections=%d, embeddings=%s)",
        repo,
        doc.file_path,
        doc_id,
        len(flat_sections),
        "yes" if doc_embedding is not None else "no",
    )

    return doc_id
