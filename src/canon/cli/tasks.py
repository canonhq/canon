"""canon tasks — list actionable work items from specs."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._local import _flatten_sections, load_local_config, parse_all_local_specs

ACTIVE_STATUSES = {"todo", "in_progress", "blocked"}
ALL_STATUSES = {"draft", "todo", "in_progress", "done", "blocked", "deprecated"}


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("tasks", help="List actionable work items from specs")
    parser.add_argument("--status", help="Filter by specific status")
    parser.add_argument("--spec", help="Filter to a single spec file")
    parser.add_argument(
        "--all", action="store_true", dest="show_all", help="Include done/deprecated/draft"
    )


def run_tasks(
    *,
    status: str | None = None,
    spec: str | None = None,
    show_all: bool = False,
    root: Path | None = None,
) -> None:
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    if spec:
        docs = [d for d in docs if spec in d.file_path]

    if not docs:
        print("No spec files found.")
        return

    statuses = ALL_STATUSES if show_all else ACTIVE_STATUSES
    if status:
        statuses = {status}

    found = False
    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        matching = [s for s in all_sections if s.status.state in statuses]
        if not matching:
            continue

        found = True
        print(f"\n{doc.frontmatter.title} ({doc.file_path})")
        print("-" * 60)

        for section in matching:
            total_ac = len(section.acceptance_criteria)
            done_ac = sum(1 for ac in section.acceptance_criteria if ac.checked)
            ac_str = f"{done_ac}/{total_ac} ACs" if total_ac else "no ACs"

            ticket = ""
            if section.ticket_link:
                ticket = f"  [{section.ticket_link.system}:{section.ticket_link.ticket_id}]"

            sid = section.section_number or section.id
            state = section.status.state
            blocked = f" (by: {section.status.blocked_by})" if section.status.blocked_by else ""
            print(f"  {sid:<10} {section.title:<30} {state}{blocked:<14} {ac_str}{ticket}")

    if not found:
        print("No matching tasks found.")
