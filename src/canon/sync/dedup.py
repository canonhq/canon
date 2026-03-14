"""Dedup — find and resolve duplicate tickets for spec sections."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from canon.parser.models import SpecDocument
from canon.sync.adapters.base import TicketAdapter
from canon.sync.engine import _flatten_sections
from canon.sync.models import SearchResult

logger = logging.getLogger(__name__)

# Matches canon/specwright ticket link comments
_TICKET_COMMENT_RE = re.compile(r"(<!--\s*(?:specwright|canon):ticket:)(\w+)(:\S+\s*-->)")


@dataclass
class DuplicateGroup:
    """A group of tickets that all map to the same spec section."""

    section_id: str
    section_title: str
    tickets: list[SearchResult] = field(default_factory=list)
    keep: SearchResult | None = None


@dataclass
class DedupResult:
    """Result of a dedup operation."""

    groups: list[DuplicateGroup] = field(default_factory=list)
    unknown_rewritten: int = 0
    issues_closed: int = 0
    errors: list[str] = field(default_factory=list)


async def find_duplicates(
    doc: SpecDocument,
    adapter: TicketAdapter,
    project_key: str,
) -> DedupResult:
    """Find duplicate tickets for each spec section.

    Searches for existing tickets matching each section's title pattern.
    Returns groups where multiple tickets exist for the same section.
    """
    result = DedupResult()
    all_sections = _flatten_sections(doc.sections)

    for section in all_sections:
        if not section.section_number:
            continue

        try:
            matches = await adapter.search_tickets(project_key, section.title)
            if len(matches) > 1:
                group = DuplicateGroup(
                    section_id=section.id,
                    section_title=section.title,
                    tickets=matches,
                    keep=matches[0],  # keep oldest (first in ASC order)
                )
                result.groups.append(group)
        except Exception as err:
            result.errors.append(f"Search failed for section {section.id}: {err}")

    return result


def rewrite_unknown_systems(markdown: str) -> tuple[str, int]:
    """Rewrite ticket:unknown:NNN → ticket:github:NNN in markdown.

    Returns (updated_markdown, count_of_rewrites).
    """
    count = 0

    def _replace(m: re.Match) -> str:
        nonlocal count
        if m.group(2) == "unknown":
            count += 1
            return f"{m.group(1)}github{m.group(3)}"
        return m.group(0)

    updated = _TICKET_COMMENT_RE.sub(_replace, markdown)
    return updated, count
