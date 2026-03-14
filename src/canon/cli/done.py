"""canon done <section-id> — mark a section complete."""

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


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("done", help="Mark a section as done")
    parser.add_argument("section_id", help="Section ID, number, or partial slug")
    parser.add_argument(
        "--issue",
        action="store_true",
        help="Update/close GitHub Issue if ticket link exists",
    )


def run_done(
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

    if current == "done":
        print(f"Section '{section.title}' is already done.")
        return

    if current == "draft":
        print(f"Warning: marking '{section.title}' done from 'draft' (expected in_progress/todo).")

    # Update markdown
    import re

    from canon.parser.writer import StatusUpdate, insert_status_comment, update_status_comments

    spec_path = root / doc.file_path
    raw = spec_path.read_text()

    # Check if status comment exists
    has_status_comment = False
    if section.section_number:
        pattern = re.compile(
            rf"<!--\s*(?:specwright|canon):system:{re.escape(section.section_number)}\s+status:\S+\s*-->"
        )
        has_status_comment = bool(pattern.search(raw))

    if has_status_comment and section.section_number:
        updated = update_status_comments(
            doc, [StatusUpdate(section_number=section.section_number, new_state="done")]
        )
    else:
        updated = insert_status_comment(
            raw,
            heading_line=section.start_line,
            section_number=section.section_number or section.id,
            state="done",
        )

    spec_path.write_text(updated)
    print(f"Done: {section.title} → done")

    if issue and section.ticket_link:
        _close_issue(config, root, section)


def _close_issue(config, root, section):
    """Update/close the linked GitHub Issue."""
    adapter = create_github_adapter_local(config, root)
    if not adapter:
        print("Warning: GitHub token or remote not available. Skipping issue update.")
        return

    from canon.parser.models import SectionStatus
    from canon.sync.models import UpdateTicketInput

    asyncio.run(
        adapter.update_ticket(
            UpdateTicketInput(
                ticket_id=section.ticket_link.ticket_id,
                status=SectionStatus(state="done"),
            )
        )
    )
    print(f"Closed issue {section.ticket_link.ticket_id}")
