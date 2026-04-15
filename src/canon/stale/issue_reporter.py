"""GitHub issue reporter for stale documents — find-or-create a tracking issue."""

from __future__ import annotations

import logging
from datetime import datetime

from .detector import StaleDoc

logger = logging.getLogger(__name__)

STALE_MARKER = "<!-- canon:stale-report -->"


def format_stale_issue_body(stale_docs: list[StaleDoc]) -> str:
    """Format a markdown issue body from a list of stale documents."""
    lines: list[str] = [
        STALE_MARKER,
        "",
        "# Stale Documentation Report",
        "",
        "The following documents may be outdated relative to recent code changes.",
        "",
        "| Document | Last Updated | Last Code Change | Stale Since | Confidence |",
        "|----------|-------------|-----------------|-------------|------------|",
    ]

    for doc in stale_docs:
        doc_change = _format_date(doc.last_doc_change)
        code_change = _format_date(doc.last_code_change)
        stale_since = _format_date(doc.stale_since)
        confidence_badge = ":red_circle:" if doc.confidence == "high" else ":yellow_circle:"

        lines.append(
            f"| `{doc.path}` | {doc_change} | {code_change} | {stale_since} | {confidence_badge} {doc.confidence} |"
        )

    lines.extend(
        [
            "",
            "---",
            "_This issue is automatically updated by Canon. "
            "Update the relevant docs to clear items from this list._",
        ]
    )

    return "\n".join(lines)


async def upsert_stale_issue(
    client,
    owner: str,
    repo: str,
    stale_docs: list[StaleDoc],
) -> int | None:
    """Find or create a stale-docs tracking issue. Returns the issue number."""
    # Search for existing tracking issue
    existing_number = await _find_stale_issue(client, owner, repo)

    body = format_stale_issue_body(stale_docs)

    if not stale_docs:
        # If no stale docs and issue exists, close it
        if existing_number:
            try:
                await client.update_issue(
                    owner,
                    repo,
                    existing_number,
                    state="closed",
                    body=body + "\n\n_All documents are up to date. Closing._",
                )
                logger.info("Closed stale-report issue #%d (no stale docs)", existing_number)
            except Exception:
                logger.warning("Failed to close stale-report issue", exc_info=True)
        return existing_number

    if existing_number:
        # Update existing issue
        try:
            await client.update_issue(
                owner,
                repo,
                existing_number,
                body=body,
            )
            logger.info("Updated stale-report issue #%d", existing_number)
            return existing_number
        except Exception:
            logger.warning("Failed to update stale-report issue", exc_info=True)
            return existing_number

    # Create new issue
    try:
        issue = await client.create_issue(
            owner,
            repo,
            title="Canon: Stale documentation detected",
            body=body,
            labels=["documentation", "canon"],
        )
        number = issue.get("number")
        logger.info("Created stale-report issue #%s", number)
        return number
    except Exception:
        logger.warning("Failed to create stale-report issue", exc_info=True)
        return None


async def _find_stale_issue(client, owner: str, repo: str) -> int | None:
    """Find an existing open stale-report issue by marker comment."""
    try:
        issues = await client.list_issues(
            owner,
            repo,
            labels="canon",
            state="open",
        )
        for issue in issues:
            body = issue.get("body") or ""
            if STALE_MARKER in body:
                return issue["number"]
    except Exception:
        logger.warning("Failed to search for existing stale-report issue", exc_info=True)
    return None


def _format_date(dt: datetime | None) -> str:
    """Format a datetime as a short date string."""
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d")
