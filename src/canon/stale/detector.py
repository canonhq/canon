"""Staleness detection — finds docs that may be outdated relative to code changes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class StaleDoc:
    """A document that may be stale."""

    repo: str
    path: str
    title: str
    last_doc_change: datetime | None = None
    last_code_change: datetime | None = None
    stale_since: datetime | None = None
    related_prs: list[int] = field(default_factory=list)
    confidence: str = "medium"  # "high" | "medium"


async def detect_stale_docs(
    search_index,
    repo: str,
    *,
    threshold_days: int = 30,
) -> list[StaleDoc]:
    """Detect documents that are stale relative to code changes.

    A doc is stale if last_code_change_at - last_doc_change_at > threshold_days.
    """
    pool = search_index._pool

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT path, title, last_doc_change_at, last_code_change_at, stale_since
            FROM spec_documents
            WHERE repo = $1
              AND stale_since IS NOT NULL
            ORDER BY stale_since ASC
            """,
            repo,
        )

    stale_docs: list[StaleDoc] = []
    for row in rows:
        doc_change = row["last_doc_change_at"]
        code_change = row["last_code_change_at"]

        # Determine confidence
        confidence = "medium"
        if doc_change and code_change:
            gap_days = (code_change - doc_change).total_seconds() / 86400
            if gap_days > threshold_days * 2:
                confidence = "high"

        stale_docs.append(
            StaleDoc(
                repo=repo,
                path=row["path"],
                title=row["title"],
                last_doc_change=doc_change,
                last_code_change=code_change,
                stale_since=row["stale_since"],
                confidence=confidence,
            )
        )

    return stale_docs


async def assess_staleness(
    claude_client,
    doc_content: str,
    code_changes_summary: str,
) -> bool:
    """Use a lightweight Claude prompt to assess if code changes affect doc content.

    Returns True if the doc is likely stale.
    """
    if not claude_client or not claude_client.is_available:
        return True  # Default to stale when Claude unavailable

    prompt = (
        "You are checking if recent code changes have made a document outdated.\n\n"
        f"Document excerpt:\n{doc_content[:2000]}\n\n"
        f"Code changes:\n{code_changes_summary[:2000]}\n\n"
        "Answer YES if the code changes likely make the document inaccurate or outdated. "
        "Answer NO if the document is still accurate. Respond with only YES or NO."
    )

    try:
        from ..agent.client import AgentConfig

        config = AgentConfig(
            model="claude-haiku-4-5-20251001", max_tokens=10, max_input_tokens=4000
        )
        result = claude_client.complete(
            "You are a staleness checker. Answer YES or NO only.",
            prompt,
            config,
        )
        return result.text.strip().upper().startswith("YES")
    except Exception:
        logger.warning("Staleness assessment failed", exc_info=True)
        return True  # Default to stale on failure
