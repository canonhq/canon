"""Resolve hierarchy templates — section depth to issue type and auto-parenting."""

from __future__ import annotations

import logging

from canon.parser.models import SpecSection
from canon.sync.mapping import HierarchyConfig

logger = logging.getLogger(__name__)


def resolve_issue_type(
    section: SpecSection,
    config: HierarchyConfig | None = None,
) -> str:
    """Resolve the issue type for a section based on its depth.

    Falls back to ``config.default_type`` or "Task" when no mapping exists.
    """
    if config and config.depth_to_type:
        return config.depth_to_type.get(section.depth, config.default_type)
    if config:
        return config.default_type
    return "Task"


def find_parent_ticket_id(
    section: SpecSection,
    parent_sections: list[SpecSection],
    config: HierarchyConfig | None = None,
) -> str | None:
    """Find the parent section's ticket ID for auto-parenting.

    When ``config.auto_parent`` is True, searches ``parent_sections``
    (which should be already-processed sections at a shallower depth)
    for the nearest parent with a ticket link.

    Returns the ticket_id or None.
    """
    if not config or not config.auto_parent:
        return None

    # Walk parent sections in reverse to find nearest ancestor
    for parent in reversed(parent_sections):
        if parent.depth < section.depth and parent.ticket_link:
            return parent.ticket_link.ticket_id

    # Only warn when a shallower ancestor exists that the hierarchy config
    # actually maps to an issue type — avoids noisy warnings for sections
    # whose parent depths aren't part of the hierarchy.
    if config.depth_to_type:
        for parent in reversed(parent_sections):
            if parent.depth < section.depth and parent.depth in config.depth_to_type:
                logger.warning(
                    "auto_parent: section %s has ancestor at depth %d but no "
                    "ticket link — parent ticket may have been created in this "
                    "same run. Re-running sync will link them.",
                    section.id,
                    parent.depth,
                )
                break

    return None
