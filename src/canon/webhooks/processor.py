"""Webhook event processor — updates spec statuses from ticket system events.

Flow:
1. Extract ticket ID and new status from the webhook payload
2. Find spec files in the affected repo that link to this ticket
3. Update the section status via reverse sync
4. Commit the updated spec file via GitHub API
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from canon.github.client import GitHubClient
from canon.github.spec_utils import (
    extract_directories,
    load_repo_config,
    matches_doc_patterns,
)
from canon.parser.models import ParseOptions, SpecDocument, SpecSection, flatten_sections
from canon.parser.parse import parse_spec
from canon.parser.writer import StatusUpdate, update_status_comments
from canon.sync.mapping import (
    TicketSystemConfig,
    deep_merge_configs,
    synthesize_mapping_config,
)
from canon.sync.org_config import load_org_mapping_config
from canon.sync.status_map import resolve_reverse, resolve_reverse_github

logger = logging.getLogger(__name__)


@dataclass
class TicketEvent:
    """A normalized ticket status change event from any ticket system."""

    system: str  # "github", "jira", "linear", "asana"
    ticket_id: str  # e.g. "42", "PROJ-123", "LIN-abc"
    # The raw status string from the ticket system. Not used for GitHub events
    # (which dispatch on github_state + github_labels instead).
    raw_status: str = ""
    # For GitHub Issues: the issue state + labels
    github_state: str | None = None  # "open" or "closed"
    github_labels: list[str] | None = None
    # Source repo (known for GitHub, discovered for others)
    owner: str | None = None
    repo: str | None = None


@dataclass
class ProcessResult:
    """Result of processing a webhook event."""

    processed: bool
    spec_file: str | None = None
    section_id: str | None = None
    old_state: str | None = None
    new_state: str | None = None
    error: str | None = None
    # "infrastructure" for transient failures (API errors, network) that
    # warrant a retry; None for business outcomes (no linked section, etc.).
    error_kind: str | None = None
    owner: str | None = None


def _find_linked_section(doc: SpecDocument, system: str, ticket_id: str) -> SpecSection | None:
    """Find the section in a spec document linked to a specific ticket."""
    for section in flatten_sections(doc.sections):
        if (
            section.ticket_link
            and section.ticket_link.system == system
            and section.ticket_link.ticket_id == ticket_id
        ):
            return section
    return None


def _resolve_new_state(event: TicketEvent, system_config: TicketSystemConfig | None) -> str:
    """Resolve the new spec state from a ticket event."""
    status_map_cfg = system_config.status_map if system_config else None

    if event.system == "github":
        result = resolve_reverse_github(
            event.github_state or "open",
            event.github_labels or [],
            status_map_cfg,
        )
        return result.state

    result = resolve_reverse(event.system, event.raw_status, status_map_cfg)
    return result.state


async def process_ticket_event(
    client: GitHubClient,
    event: TicketEvent,
) -> ProcessResult:
    """Process a single ticket status change event.

    Finds the spec file containing the ticket link, resolves the new status,
    and commits the update. Idempotent: if the status is already correct,
    no commit is made.
    """
    if not event.owner or not event.repo:
        return ProcessResult(processed=False, error="Missing owner/repo in event")

    owner = event.owner
    repo = event.repo

    try:
        # Load repo config for doc_paths and ticket mapping
        repo_config = await load_repo_config(client, owner, repo)
        doc_paths = repo_config.specs.doc_paths

        # Synthesize mapping config
        mapping, _deprecated = synthesize_mapping_config(
            ticket_system=repo_config.ticket_system,
            project_key=repo_config.project_key,
            ticket_mapping=repo_config.ticket_mapping,
        )

        # Merge org-level defaults if available
        org_mapping = await load_org_mapping_config(client, owner)
        if org_mapping:
            mapping = deep_merge_configs(org_mapping, mapping)

        # Determine which system config to use for status resolution
        system_config: TicketSystemConfig | None = None
        if not mapping.is_empty():
            for _name, sys_cfg in mapping.ticket_systems.items():
                if sys_cfg.system == event.system:
                    system_config = sys_cfg
                    break

        # List spec files
        directories = extract_directories(doc_paths)
        entries: list[dict] = []
        for directory, _is_recursive in directories:
            entries.extend(await client.list_directory(owner, repo, directory))

        spec_files = [
            e.get("path", e.get("name", ""))
            for e in entries
            if e.get("type") == "file"
            and e.get("name", "").endswith(".md")
            and not e.get("name", "").startswith("_")
            and matches_doc_patterns(e.get("path", e.get("name", "")), doc_paths)
        ]

        # Scan spec files for the ticket link
        for file_path in spec_files:
            try:
                content, file_sha = await client.get_file_content(owner, repo, file_path)
                result = parse_spec(content, ParseOptions(file_path=file_path))
            except Exception:
                logger.exception(
                    "Error reading/parsing %s for ticket %s:%s",
                    file_path,
                    event.system,
                    event.ticket_id,
                )
                continue

            section = _find_linked_section(result.document, event.system, event.ticket_id)

            if section is None:
                continue

            # Found the linked section — resolve new state
            new_state = _resolve_new_state(event, system_config)
            old_state = section.status.state

            # Idempotent: skip if already at target state
            if new_state == old_state:
                logger.info(
                    "Ticket %s:%s already at state %r — skipping",
                    event.system,
                    event.ticket_id,
                    new_state,
                )
                return ProcessResult(
                    processed=True,
                    spec_file=file_path,
                    section_id=section.id,
                    old_state=old_state,
                    new_state=new_state,
                    owner=owner,
                )

            # Update the status comment in the spec
            if not section.section_number:
                logger.warning(
                    "Section %s in %s has no section_number — cannot update status",
                    section.id,
                    file_path,
                )
                return ProcessResult(
                    processed=False,
                    spec_file=file_path,
                    section_id=section.id,
                    error=f"Section {section.id} has no section_number",
                )

            updates = [
                StatusUpdate(
                    section_number=section.section_number,
                    new_state=new_state,
                )
            ]
            updated_md = update_status_comments(result.document, updates)

            # Fetch default branch only when we need to commit
            default_branch = await client.get_default_branch(owner, repo)

            # Commit the update with retry on stale SHA (409 Conflict).
            # Multiple webhook events for the same spec file can race,
            # causing all but the first to fail. On 409, re-fetch the
            # file to get the latest SHA and re-apply the update.
            max_attempts = 3
            commit_msg = (
                f"chore(canon): {event.system} ticket {event.ticket_id} "
                f"→ {new_state} in {file_path}"
            )
            for attempt in range(max_attempts):
                try:
                    await client.create_or_update_file(
                        owner,
                        repo,
                        file_path,
                        updated_md,
                        commit_msg,
                        file_sha,
                        branch=default_branch,
                    )
                    break  # Success
                except Exception as commit_err:
                    err_str = str(commit_err)
                    is_conflict = "409" in err_str or "conflict" in err_str.lower()
                    if is_conflict and attempt < max_attempts - 1:
                        logger.warning(
                            "Stale SHA conflict committing %s (ticket %s:%s), "
                            "attempt %d/%d — retrying",
                            file_path,
                            event.system,
                            event.ticket_id,
                            attempt + 1,
                            max_attempts,
                        )
                        await asyncio.sleep(0.5 * (attempt + 1))
                        # Re-fetch file to get fresh SHA and content
                        content, file_sha = await client.get_file_content(owner, repo, file_path)
                        fresh = parse_spec(content, ParseOptions(file_path=file_path))
                        updated_md = update_status_comments(fresh.document, updates)
                        continue
                    if is_conflict:
                        logger.warning(
                            "Stale SHA conflict committing %s (ticket %s:%s) — "
                            "exhausted %d retries",
                            file_path,
                            event.system,
                            event.ticket_id,
                            max_attempts,
                        )
                    raise

            logger.info(
                "Updated %s section %s: %s → %s (ticket %s:%s)",
                file_path,
                section.id,
                old_state,
                new_state,
                event.system,
                event.ticket_id,
            )

            return ProcessResult(
                processed=True,
                spec_file=file_path,
                section_id=section.id,
                old_state=old_state,
                new_state=new_state,
                owner=owner,
            )

        # No spec file found with this ticket link
        logger.info(
            "No spec section linked to ticket %s:%s in %s/%s",
            event.system,
            event.ticket_id,
            owner,
            repo,
        )
        return ProcessResult(processed=False, error="No linked spec section found")

    except Exception as err:
        logger.exception("Error processing ticket event %s:%s", event.system, event.ticket_id)
        return ProcessResult(processed=False, error=str(err), error_kind="infrastructure")
