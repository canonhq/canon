"""canon plan <spec-file> — task decomposition from a spec."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._local import _flatten_sections, load_local_config, parse_all_local_specs


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("plan", help="Generate task plan from a spec")
    parser.add_argument("spec_file", help="Spec file path or partial match")
    parser.add_argument("--output", help="Write plan to file instead of stdout")


def run_plan(
    *,
    spec_file: str,
    output: str | None = None,
    root: Path | None = None,
) -> None:
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    matches = [d for d in docs if spec_file in d.file_path]
    if not matches:
        print(f"No spec matching '{spec_file}' found.")
        sys.exit(1)

    doc = matches[0]
    lines = _generate_plan(doc)

    text = "\n".join(lines)
    if output:
        Path(output).write_text(text + "\n")
        print(f"Plan written to {output}")
    else:
        print(text)


def _generate_plan(doc) -> list[str]:
    """Generate a structured task plan from a spec document."""
    lines: list[str] = []
    lines.append(f"# Task Plan: {doc.frontmatter.title}")
    lines.append("")

    # Dependencies from frontmatter
    if doc.frontmatter.depends_on:
        lines.append("## Dependencies")
        for dep in doc.frontmatter.depends_on:
            lines.append(f"- {dep}")
        lines.append("")

    # Tasks from sections
    all_sections = _flatten_sections(doc.sections)
    actionable = [s for s in all_sections if s.status.state in ("todo", "in_progress")]

    if not actionable:
        lines.append("No actionable tasks (all sections are done, draft, or blocked).")
        return lines

    lines.append("## Tasks")
    lines.append("")

    for task_num, section in enumerate(actionable, 1):
        status_icon = ">" if section.status.state == "in_progress" else " "
        sid = section.section_number or section.id
        lines.append(
            f"{task_num}. [{status_icon}] **{sid} {section.title}** ({section.status.state})"
        )

        # Blocked info
        if section.status.blocked_by:
            lines.append(f"   Blocked by: {section.status.blocked_by}")

        # Ticket link
        if section.ticket_link:
            lines.append(f"   Ticket: {section.ticket_link.system}:{section.ticket_link.ticket_id}")

        # ACs as subtasks
        if section.acceptance_criteria:
            for ac in section.acceptance_criteria:
                check = "x" if ac.checked else " "
                lines.append(f"   - [{check}] {ac.text}")

        lines.append("")

    # Summary
    done_count = sum(1 for s in all_sections if s.status.state == "done")
    total_count = len(all_sections)
    lines.append("## Summary")
    lines.append(f"- Sections: {done_count}/{total_count} done")
    lines.append(f"- Actionable tasks: {len(actionable)}")
    in_progress = sum(1 for s in actionable if s.status.state == "in_progress")
    if in_progress:
        lines.append(f"- In progress: {in_progress}")

    return lines
