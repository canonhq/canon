"""Sync engine — forward sync (spec → tickets) and reverse sync (tickets → spec).

Supports configurable ticket mapping via TicketSystemConfig: custom templates,
field mapping, hierarchy (issue types + auto-parenting), and status maps.
All config is optional — when omitted, behavior matches the original hardcoded engine.
"""

from __future__ import annotations

import logging
from typing import Literal

from canon import analytics
from canon.parser.models import SpecDocument, SpecSection
from canon.parser.writer import (
    StatusUpdate,
    TicketLinkInsertion,
    insert_ticket_links,
    update_status_comments,
)
from canon.sync.adapters.base import TicketAdapter
from canon.sync.field_resolver import resolve_fields
from canon.sync.hierarchy import find_parent_ticket_id, resolve_issue_type
from canon.sync.mapping import TicketSystemConfig
from canon.sync.models import (
    CreateTicketInput,
    SyncClosed,
    SyncCreated,
    SyncError,
    SyncReopened,
    SyncResult,
    SyncSkipped,
    SyncStatusChanged,
    SyncUpdated,
    UpdateTicketInput,
)
from canon.sync.status_map import resolve_reverse
from canon.sync.templates import make_fingerprint, render_description, render_summary

logger = logging.getLogger(__name__)

# Only sections in these states are actionable work items.
_SYNCABLE_STATES = frozenset({"todo", "in_progress"})
# Sections in these states should have their tickets closed.
_CLOSABLE_STATES = frozenset({"done", "deprecated"})
# Sections in these states can have their tickets reopened.
_REOPENABLE_STATES = frozenset({"todo", "in_progress"})


def _flatten_sections(sections: list[SpecSection]) -> list[SpecSection]:
    """Recursively flatten a section tree into a pre-order list."""
    result: list[SpecSection] = []
    for section in sections:
        result.append(section)
        if section.children:
            result.extend(_flatten_sections(section.children))
    return result


def _detect_system(adapter: TicketAdapter, system_config: TicketSystemConfig | None) -> str:
    """Determine the ticket system name.

    Prefers the explicit ``system_config.system`` value when available,
    then the adapter's ``system_name`` property. Never returns ``"unknown"``
    — the adapter is the authoritative source for its system name.
    """
    if system_config and system_config.system:
        return system_config.system
    return adapter.system_name


async def forward_sync(
    doc: SpecDocument,
    adapter: TicketAdapter,
    project_key: str,
    *,
    require_review: bool = False,
    dry_run: bool = False,
    system_config: TicketSystemConfig | None = None,
    spec_url: str = "",
    lifecycle_sync: bool | Literal["close_only"] = True,
    repo: str = "",
    org: str = "",
) -> tuple[str, SyncResult]:
    """Forward sync: create tickets for sections without one.

    When ``require_review`` is True, sync is blocked unless the spec's
    frontmatter ``review_status`` is ``"approved"``.

    When ``system_config`` is provided, uses its templates, field mapping,
    hierarchy, and status map for ticket creation. When omitted, falls back
    to the default templates.

    When ``spec_url`` is provided, it's available in templates as ``{{spec_url}}``.

    Returns (updated_markdown, sync_result).
    """
    # Per-spec sync control via frontmatter `sync` field
    spec_sync = doc.frontmatter.sync
    if spec_sync == "false":
        result = SyncResult()
        result.skipped.append(
            SyncSkipped(section_id="__document__", reason="sync disabled via frontmatter")
        )
        return doc.raw, result

    # sync: "true" bypasses require_review; sync: "auto" defers to global config
    if spec_sync != "true" and require_review:
        review_status = getattr(doc.frontmatter, "review_status", None)
        if review_status != "approved":
            result = SyncResult()
            result.errors.append(
                SyncError(
                    section_id="__document__",
                    error=(
                        f"Spec requires review approval before ticket sync "
                        f"(current review_status: {review_status!r})"
                    ),
                )
            )
            return doc.raw, result

    result = SyncResult()
    insertions: list[TicketLinkInsertion] = []
    all_sections = _flatten_sections(doc.sections)

    # Pre-extract config sub-objects (None-safe)
    templates_cfg = system_config.templates if system_config else None
    field_map_cfg = system_config.field_map if system_config else None
    hierarchy_cfg = system_config.hierarchy if system_config else None

    # Track processed sections for auto-parenting
    processed_sections: list[SpecSection] = []

    for section in all_sections:
        if not section.section_number:
            continue

        # Only create tickets for actionable sections (todo, in_progress).
        # Draft, done, blocked, deprecated sections are not work items.
        if section.status.state not in _SYNCABLE_STATES and not section.ticket_link:
            result.skipped.append(
                SyncSkipped(
                    section_id=section.id,
                    reason=f"status is {section.status.state!r} (only todo/in_progress are synced)",
                )
            )
            continue

        if not section.ticket_link:
            # Resolve issue type via hierarchy config
            issue_type = resolve_issue_type(section, hierarchy_cfg)

            # Resolve summary and description via templates (always uses templates now)
            spec_url_value = spec_url if spec_url else ""
            summary = render_summary(section, doc, templates_cfg, spec_url_value)
            description = render_description(section, doc, templates_cfg, spec_url_value)

            # Prepend issue type to summary when hierarchy is active
            if hierarchy_cfg and hierarchy_cfg.depth_to_type:
                summary = f"[{issue_type}] {summary}"

            # Resolve auto-parent ticket ID
            parent_ticket_id = find_parent_ticket_id(section, processed_sections, hierarchy_cfg)

            # Resolve field mappings
            standard_fields, custom_fields = resolve_fields(section, doc, field_map_cfg)

            # Extract assignees and milestone from standard field mappings
            assignees: list[str] = []
            mapped_assignee = standard_fields.get("assignee")
            if mapped_assignee:
                assignees = (
                    [str(mapped_assignee)]
                    if isinstance(mapped_assignee, str)
                    else list(mapped_assignee)
                )
            milestone = standard_fields.get("milestone")
            if milestone is not None:
                milestone = str(milestone)

            # Build labels: field-mapped labels + issue type label
            labels: list[str] = []
            mapped_labels = standard_fields.get("labels")
            if isinstance(mapped_labels, (list, tuple)):
                labels.extend(str(lb) for lb in mapped_labels)
            if hierarchy_cfg and hierarchy_cfg.depth_to_type:
                labels.append(f"type:{issue_type.lower()}")

            if dry_run:
                result.created.append(
                    SyncCreated(
                        section_id=section.id,
                        ticket_id="(dry-run)",
                        ticket_url="",
                    )
                )
                processed_sections.append(section)
                continue

            # Dedup: search for existing tickets before creating.
            # Primary: fingerprint match (stable across renames).
            # Fallback: title match (original behavior).
            dedup_on = system_config.dedup_enabled if system_config else True
            if dedup_on:
                dedup_match = None
                dedup_method = None

                # 1. Fingerprint-based dedup (preferred)
                # Note: GitHub Search API is rate-limited to 30 req/min.
                # Large specs (40+ sections) may hit this limit.
                if section.section_number and adapter.capabilities.supports_fingerprint_search:
                    try:
                        fingerprint = make_fingerprint(doc, section)
                        fp_results = await adapter.search_by_fingerprint(project_key, fingerprint)
                        if fp_results:
                            dedup_match = fp_results[0]
                            dedup_method = "fingerprint"
                    except Exception:
                        logger.warning(
                            "Fingerprint dedup search failed for section %s, trying title",
                            section.id,
                            exc_info=True,
                        )

                # 2. Title-based dedup (fallback)
                if not dedup_match:
                    try:
                        existing = await adapter.search_tickets(project_key, section.title)
                        if existing:
                            dedup_match = existing[0]
                            dedup_method = "title"
                    except Exception:
                        logger.warning(
                            "Title dedup search failed for section %s, proceeding with create",
                            section.id,
                            exc_info=True,
                        )

                if dedup_match:
                    logger.info(
                        "Dedup (%s): found existing ticket %s for section %s, linking instead of creating",
                        dedup_method,
                        dedup_match.ticket_id,
                        section.id,
                    )
                    insertions.append(
                        TicketLinkInsertion(
                            heading_line=section.start_line,
                            system=_detect_system(adapter, system_config),
                            ticket_id=dedup_match.ticket_id,
                        )
                    )
                    result.updated.append(
                        SyncUpdated(
                            section_id=section.id,
                            ticket_id=dedup_match.ticket_id,
                        )
                    )
                    analytics.track(
                        "ticket_deduped",
                        properties={
                            "repo": repo,
                            "spec_path": doc.file_path,
                            "section_id": section.id,
                            "ticket_id": dedup_match.ticket_id,
                            "dedup_method": dedup_method,
                        },
                        groups={"organization": org} if org else None,
                    )
                    processed_sections.append(section)
                    continue

            try:
                ticket = await adapter.create_ticket(
                    CreateTicketInput(
                        project_key=project_key,
                        summary=summary,
                        description=description,
                        status=section.status,
                        issue_type=issue_type,
                        parent_ticket_id=parent_ticket_id,
                        custom_fields=custom_fields,
                        labels=labels,
                        assignees=assignees,
                        milestone=milestone,
                    )
                )
                insertions.append(
                    TicketLinkInsertion(
                        heading_line=section.start_line,
                        system=_detect_system(adapter, system_config),
                        ticket_id=ticket.ticket_id,
                    )
                )
                result.created.append(
                    SyncCreated(
                        section_id=section.id,
                        ticket_id=ticket.ticket_id,
                        ticket_url=ticket.ticket_url,
                    )
                )
                analytics.track(
                    "ticket_created",
                    properties={
                        "repo": repo,
                        "spec_path": doc.file_path,
                        "section_id": section.id,
                        "ticket_system": _detect_system(adapter, system_config),
                        "ticket_id": ticket.ticket_id,
                        "issue_type": issue_type,
                    },
                    groups={"organization": org} if org else None,
                )
            except Exception as err:
                result.errors.append(SyncError(section_id=section.id, error=str(err)))
        else:
            result.updated.append(
                SyncUpdated(
                    section_id=section.id,
                    ticket_id=section.ticket_link.ticket_id,
                )
            )

        # Track section even on error — it still occupies a position in the
        # hierarchy. Auto-parenting gates on ticket_link, so children of a
        # failed parent won't get a spurious parent ID.
        processed_sections.append(section)

    markdown = insert_ticket_links(doc, insertions) if insertions else doc.raw

    # Post-sync: update parent issues with sub-task lists
    if hierarchy_cfg and hierarchy_cfg.auto_parent and result.created and not dry_run:
        await _update_parent_task_lists(adapter, result, all_sections, insertions)

    # Lifecycle sync: close/reopen tickets based on section state transitions.
    # Only checks sections in actionable states (_CLOSABLE or _REOPENABLE)
    # to avoid unnecessary API calls for draft/blocked/todo sections.
    if lifecycle_sync:
        for section in all_sections:
            if not section.ticket_link or not section.section_number:
                continue

            # Close tickets for done/deprecated sections
            if section.status.state in _CLOSABLE_STATES:
                if lifecycle_sync is True or lifecycle_sync == "close_only":
                    try:
                        current = await adapter.get_ticket_status(section.ticket_link.ticket_id)
                        is_closed = current.status.state in ("done", "deprecated")

                        if not is_closed:
                            if not dry_run:
                                await adapter.update_ticket(
                                    UpdateTicketInput(
                                        ticket_id=section.ticket_link.ticket_id,
                                        status=section.status,
                                    )
                                )
                            result.closed.append(
                                SyncClosed(
                                    section_id=section.id,
                                    ticket_id=section.ticket_link.ticket_id,
                                )
                            )
                            analytics.track(
                                "ticket_closed",
                                properties={
                                    "repo": repo,
                                    "spec_path": doc.file_path,
                                    "section_id": section.id,
                                    "ticket_id": section.ticket_link.ticket_id,
                                    "reason": section.status.state,
                                },
                                groups={"organization": org} if org else None,
                            )
                    except Exception as err:
                        result.errors.append(SyncError(section_id=section.id, error=str(err)))

            # Reopen tickets for sections that moved back to todo/in_progress
            elif section.status.state in _REOPENABLE_STATES and lifecycle_sync is True:
                try:
                    current = await adapter.get_ticket_status(section.ticket_link.ticket_id)
                    is_closed = current.status.state in ("done", "deprecated")
                    if is_closed:
                        if not dry_run:
                            await adapter.update_ticket(
                                UpdateTicketInput(
                                    ticket_id=section.ticket_link.ticket_id,
                                    status=section.status,
                                )
                            )
                        result.reopened.append(
                            SyncReopened(
                                section_id=section.id,
                                ticket_id=section.ticket_link.ticket_id,
                            )
                        )
                        analytics.track(
                            "ticket_reopened",
                            properties={
                                "repo": repo,
                                "spec_path": doc.file_path,
                                "section_id": section.id,
                                "ticket_id": section.ticket_link.ticket_id,
                            },
                            groups={"organization": org} if org else None,
                        )
                except Exception as err:
                    result.errors.append(SyncError(section_id=section.id, error=str(err)))

    return markdown, result


async def _update_parent_task_lists(
    adapter: TicketAdapter,
    result: SyncResult,
    sections: list[SpecSection],
    insertions: list[TicketLinkInsertion],
) -> None:
    """Update parent issues with sub-task references.

    After creating child tickets, finds their parent sections and updates
    the parent issue body with a "## Sub-tasks" section listing child tickets.
    """
    # Build ticket_id lookup from newly created tickets
    created_map: dict[str, str] = {}  # section_id → ticket_id
    for created in result.created:
        created_map[created.section_id] = created.ticket_id

    # Build insertion lookup for ticket IDs of newly created tickets
    insertion_by_line: dict[int, str] = {ins.heading_line: ins.ticket_id for ins in insertions}

    # Group children by parent
    parent_children: dict[str, list[tuple[str, str]]] = {}  # parent_ticket_id → [(child_id, title)]

    for section in sections:
        if not section.section_number or section.id not in created_map:
            continue

        child_ticket_id = created_map[section.id]

        # Find parent section (nearest section at shallower depth)
        for parent_candidate in reversed(sections[: sections.index(section)]):
            if parent_candidate.depth < section.depth:
                parent_ticket_id = None
                if parent_candidate.ticket_link:
                    parent_ticket_id = parent_candidate.ticket_link.ticket_id
                elif parent_candidate.start_line in insertion_by_line:
                    parent_ticket_id = insertion_by_line[parent_candidate.start_line]

                if parent_ticket_id:
                    parent_children.setdefault(parent_ticket_id, []).append(
                        (child_ticket_id, section.title)
                    )
                break

    # Update each parent issue
    for parent_id, children in parent_children.items():
        try:
            if hasattr(adapter, "update_task_list"):
                await adapter.update_task_list(parent_id, children)
        except Exception:
            logger.debug(
                "Failed to update task list for parent %s",
                parent_id,
                exc_info=True,
            )


async def backfill_fingerprints(
    doc: SpecDocument,
    adapter: TicketAdapter,
    *,
    dry_run: bool = False,
) -> SyncResult:
    """Add fingerprints to existing issue bodies that lack them.

    Scans all spec sections with ticket links. For each linked issue,
    checks if the body already contains a fingerprint. If not, appends one.
    This is a one-time migration; subsequent syncs add fingerprints automatically.
    """
    result = SyncResult()

    if not adapter.capabilities.supports_body_read:
        result.errors.append(
            SyncError(
                section_id="__document__",
                error="Adapter does not support get_ticket (required for backfill)",
            )
        )
        return result

    all_sections = _flatten_sections(doc.sections)

    for section in all_sections:
        if not section.ticket_link or not section.section_number:
            continue

        fingerprint = make_fingerprint(doc, section)

        try:
            ticket = await adapter.get_ticket(section.ticket_link.ticket_id)
            body = str(ticket.get("body", "") or "")

            if fingerprint in body:
                result.skipped.append(
                    SyncSkipped(
                        section_id=section.id,
                        reason="fingerprint already present",
                    )
                )
                continue

            if dry_run:
                result.updated.append(
                    SyncUpdated(
                        section_id=section.id,
                        ticket_id=section.ticket_link.ticket_id,
                    )
                )
                continue

            updated_body = body + "\n\n" + fingerprint
            await adapter.update_ticket(
                UpdateTicketInput(
                    ticket_id=section.ticket_link.ticket_id,
                    description=updated_body,
                )
            )
            result.updated.append(
                SyncUpdated(
                    section_id=section.id,
                    ticket_id=section.ticket_link.ticket_id,
                )
            )
        except Exception as err:
            result.errors.append(SyncError(section_id=section.id, error=str(err)))

    return result


async def reverse_sync(
    doc: SpecDocument,
    adapter: TicketAdapter,
    *,
    system_config: TicketSystemConfig | None = None,
    repo: str = "",
    org: str = "",
) -> tuple[str, SyncResult]:
    """Reverse sync: poll ticket statuses and update spec status comments.

    When ``system_config`` is provided, uses its ``status_map`` to resolve
    ticket statuses to spec states. When omitted, uses default mappings.

    Returns (updated_markdown, sync_result).
    """
    result = SyncResult()
    updates: list[StatusUpdate] = []
    all_sections = _flatten_sections(doc.sections)

    system = _detect_system(adapter, system_config)
    status_map_cfg = system_config.status_map if system_config else None

    for section in all_sections:
        if not section.ticket_link or not section.section_number:
            continue

        try:
            ticket_status = await adapter.get_ticket_status(section.ticket_link.ticket_id)

            # Use configurable status resolution when available
            if status_map_cfg and status_map_cfg.reverse:
                resolved = resolve_reverse(system, ticket_status.raw_status, status_map_cfg)
                new_state = resolved.state
            else:
                new_state = ticket_status.status.state

            if new_state != section.status.state:
                updates.append(
                    StatusUpdate(
                        section_number=section.section_number,
                        new_state=new_state,
                    )
                )
                result.status_changed.append(
                    SyncStatusChanged(
                        section_id=section.id,
                        ticket_id=section.ticket_link.ticket_id,
                        old_state=section.status.state,
                        new_state=new_state,
                    )
                )
                analytics.track(
                    "ticket_status_synced",
                    properties={
                        "repo": repo,
                        "spec_path": doc.file_path,
                        "section_id": section.id,
                        "ticket_id": section.ticket_link.ticket_id,
                        "old_state": section.status.state,
                        "new_state": new_state,
                        "ticket_system": system,
                    },
                    groups={"organization": org} if org else None,
                )
        except Exception as err:
            result.errors.append(SyncError(section_id=section.id, error=str(err)))

    markdown = update_status_comments(doc, updates) if updates else doc.raw
    return markdown, result
