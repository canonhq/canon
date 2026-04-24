"""canon start <section-id> — start working on a section."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from ._local import (
    create_github_adapter_local,
    find_section_by_id,
    load_local_config,
    parse_all_local_specs,
)

VALID_FROM = {"draft", "todo"}


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("start", help="Mark a section as in_progress")
    parser.add_argument("section_id", help="Section ID, number, or partial slug")
    parser.add_argument(
        "--issue",
        action="store_true",
        help="Create/update GitHub Issue for this section",
    )


def run_start(
    *,
    section_id: str,
    issue: bool = False,
    root: Path | None = None,
) -> None:
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    match = find_section_by_id(docs, section_id)
    if not match:
        print(f"Section '{section_id}' not found.")
        sys.exit(1)

    doc, section = match
    current = section.status.state

    if current == "in_progress":
        print(f"Section '{section.title}' is already in_progress.")
        return

    if current not in VALID_FROM:
        print(f"Warning: transitioning from '{current}' to 'in_progress' (expected draft/todo).")

    # Update markdown
    from canon.parser.writer import StatusUpdate, insert_status_comment, update_status_comments

    spec_path = root / doc.file_path
    raw = spec_path.read_text()

    # Check if status comment exists
    has_status_comment = False
    if section.section_number:
        import re

        pattern = re.compile(
            rf"<!--\s*(?:specwright|canon):system:{re.escape(section.section_number)}\s+status:\S+\s*-->"
        )
        has_status_comment = bool(pattern.search(raw))

    if has_status_comment and section.section_number:
        updated = update_status_comments(
            doc, [StatusUpdate(section_number=section.section_number, new_state="in_progress")]
        )
    else:
        updated = insert_status_comment(
            raw,
            heading_line=section.start_line,
            section_number=section.section_number or section.id,
            state="in_progress",
        )

    spec_path.write_text(updated)
    print(f"Started: {section.title} → in_progress")

    if issue:
        _handle_issue(config, root, doc, section)


def _handle_issue(config, root, doc, section):
    """Create or update GitHub Issue for the section."""
    adapter = create_github_adapter_local(config, root)
    if not adapter:
        print("Warning: GitHub token or remote not available. Skipping issue creation.")
        return

    if section.ticket_link:
        # Update existing issue
        from canon.parser.models import SectionStatus
        from canon.sync.models import UpdateTicketInput

        asyncio.run(
            adapter.update_ticket(
                UpdateTicketInput(
                    ticket_id=section.ticket_link.ticket_id,
                    status=SectionStatus(state="in_progress"),
                )
            )
        )
        print(f"Updated issue {section.ticket_link.ticket_id} → in_progress")
    else:
        # Create new issue
        from canon.parser.models import SectionStatus
        from canon.parser.writer import TicketLinkInsertion, insert_ticket_links
        from canon.sync.models import CreateTicketInput

        ticket = asyncio.run(
            adapter.create_ticket(
                CreateTicketInput(
                    project_key=config.project_key or "",
                    summary=f"[{section.section_number or section.id}] {section.title}",
                    description=section.content[:2000],
                    status=SectionStatus(state="in_progress"),
                )
            )
        )
        print(f"Created issue #{ticket.ticket_id}: {ticket.ticket_url}")

        # Insert ticket link in markdown
        spec_path = root / doc.file_path
        raw = spec_path.read_text()
        # Re-parse to get updated line numbers
        from canon.parser.models import ParseOptions
        from canon.parser.parse import parse_spec

        result = parse_spec(raw, ParseOptions(file_path=doc.file_path, include_content=True))
        updated_doc = result.document

        updated = insert_ticket_links(
            updated_doc,
            [
                TicketLinkInsertion(
                    heading_line=section.start_line,
                    system="github",
                    ticket_id=ticket.ticket_id,
                    url=ticket.ticket_url,
                )
            ],
        )
        spec_path.write_text(updated)
        print(f"Linked issue in {doc.file_path}")
