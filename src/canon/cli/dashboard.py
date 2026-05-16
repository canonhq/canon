"""canon dashboard — combined spec overview."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ._local import _flatten_sections, load_local_config, parse_all_local_specs
from ._output import coverage_text, get_stdout, make_table, status_badge


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("dashboard", help="Spec overview dashboard")
    parser.add_argument("--json", action="store_true", help="JSON output")


def run_dashboard(
    *,
    json_output: bool = False,
    root: Path | None = None,
) -> int:
    """Show combined overview. Returns exit code."""
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    if not docs:
        if json_output:
            print(json.dumps({"coverage": {}, "tasks": [], "incomplete_specs": []}, indent=2))
        else:
            print("No spec files found.")
        return 0

    # Compute coverage
    total_specs = len(docs)
    total_sections = 0
    total_ac = 0
    done_ac = 0

    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        total_sections += len(all_sections)
        for s in all_sections:
            total_ac += len(s.acceptance_criteria)
            done_ac += sum(1 for ac in s.acceptance_criteria if ac.checked)

    overall_pct = (done_ac / total_ac * 100) if total_ac else 0.0

    # Collect tasks (in_progress and todo)
    tasks: list[dict] = []
    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        for s in all_sections:
            if s.status.state in ("in_progress", "todo"):
                ac_total = len(s.acceptance_criteria)
                ac_done = sum(1 for ac in s.acceptance_criteria if ac.checked)
                tasks.append(
                    {
                        "spec": doc.frontmatter.title,
                        "section": f"{s.section_number or s.id}. {s.title}",
                        "status": s.status.state,
                        "ac_done": ac_done,
                        "ac_total": ac_total,
                    }
                )

    # Sort: in_progress first, then todo
    tasks.sort(key=lambda t: (0 if t["status"] == "in_progress" else 1, t["spec"]))

    # Collect incomplete specs (specs with sections that are in_progress or todo)
    stale: list[dict] = []
    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        ac_total = sum(len(s.acceptance_criteria) for s in all_sections)
        ac_done = sum(sum(1 for ac in s.acceptance_criteria if ac.checked) for s in all_sections)
        pct = (ac_done / ac_total * 100) if ac_total else 0.0
        in_progress = sum(1 for s in all_sections if s.status.state == "in_progress")
        todo = sum(1 for s in all_sections if s.status.state == "todo")
        if todo > 0 or in_progress > 0:
            stale.append(
                {
                    "spec": doc.frontmatter.title,
                    "file": doc.file_path,
                    "coverage_pct": round(pct, 1),
                    "in_progress": in_progress,
                    "todo": todo,
                }
            )

    stale.sort(key=lambda s: s["coverage_pct"])

    if json_output:
        print(
            json.dumps(
                {
                    "coverage": {
                        "specs": total_specs,
                        "sections": total_sections,
                        "ac_total": total_ac,
                        "ac_done": done_ac,
                        "coverage_pct": round(overall_pct, 1),
                    },
                    "tasks": tasks[:10],
                    "incomplete_specs": stale[:5],
                },
                indent=2,
            )
        )
        return 0

    # Rich output
    get_stdout().print("\n[heading]Canon Dashboard[/heading]\n")

    # Coverage section
    get_stdout().print("[heading]Coverage[/heading]")
    get_stdout().print(
        f"  {total_specs} specs | {total_sections} sections | {total_ac} ACs | ", end=""
    )
    get_stdout().print(coverage_text(overall_pct))
    get_stdout().print()

    # Tasks section
    get_stdout().print(f"[heading]Active Tasks[/heading]  [muted]({len(tasks)} total)[/muted]")
    if tasks:
        table = make_table(
            columns=[
                {"name": "Spec", "style": "key", "no_wrap": True},
                {"name": "Section", "no_wrap": True},
                {"name": "Status"},
                {"name": "ACs", "justify": "right"},
            ],
        )
        for t in tasks[:10]:
            ac_str = f"{t['ac_done']}/{t['ac_total']}" if t["ac_total"] else "\u2014"
            table.add_row(
                t["spec"][:25],
                t["section"][:35],
                status_badge(t["status"]),
                ac_str,
            )
        get_stdout().print(table)
        if len(tasks) > 10:
            get_stdout().print(
                f"  [muted]{len(tasks) - 10} more — run `canon tasks` to see all[/muted]"
            )
    else:
        get_stdout().print("  [success]No active tasks — all caught up![/success]")
    get_stdout().print()

    # Incomplete specs section
    get_stdout().print(f"[heading]Incomplete Specs[/heading]  [muted]({len(stale)} total)[/muted]")
    if stale:
        table = make_table(
            columns=[
                {"name": "Spec", "style": "key", "no_wrap": True},
                {"name": "Coverage", "justify": "right"},
                {"name": "In Progress", "justify": "right"},
                {"name": "Todo", "justify": "right"},
            ],
        )
        for s in stale[:5]:
            table.add_row(
                s["spec"][:30],
                coverage_text(s["coverage_pct"]),
                str(s["in_progress"]),
                str(s["todo"]),
            )
        get_stdout().print(table)
        if len(stale) > 5:
            get_stdout().print(
                f"  [muted]{len(stale) - 5} more — run `canon status` to see all[/muted]"
            )
    else:
        get_stdout().print("  [success]All specs complete![/success]")
    get_stdout().print()

    return 0
