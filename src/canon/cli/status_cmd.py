"""canon status — coverage dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ._local import _flatten_sections, load_local_config, parse_all_local_specs


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("status", help="Show spec coverage dashboard")
    parser.add_argument("--spec", help="Show detail for a single spec file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-friendly output",
    )


def run_status(
    *,
    spec: str | None = None,
    root: Path | None = None,
    json_output: bool = False,
) -> int:
    """Run status. Returns exit code (0 success, 2 unresolved spec filter)."""
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    if not docs:
        if json_output:
            print(json.dumps(_empty_payload(), indent=2))
        else:
            print("No spec files found.")
        return 0

    # Single-spec detail view
    if spec:
        matches = [d for d in docs if spec in d.file_path]
        if not matches:
            msg = f"No spec matching '{spec}' found."
            if json_output:
                print(json.dumps({"error": msg, **_empty_payload()}, indent=2))
            else:
                print(msg)
            return 2
        if json_output:
            print(json.dumps(_build_payload(matches), indent=2))
            return 0
        for doc in matches:
            _print_spec_detail(doc)
        return 0

    if json_output:
        print(json.dumps(_build_payload(docs), indent=2))
        return 0

    # Aggregate metrics (human view)
    from ._output import coverage_text, get_stdout, make_table, status_badge

    total_specs = len(docs)
    total_sections = 0
    total_ac = 0
    done_ac = 0
    in_progress_specs = 0
    sections_in_progress = 0

    table_rows: list[list] = []
    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        sec_total = len(all_sections)
        sec_done = sum(1 for s in all_sections if s.status.state == "done")
        sec_in_prog = sum(1 for s in all_sections if s.status.state == "in_progress")
        ac_total = sum(len(s.acceptance_criteria) for s in all_sections)
        ac_done = sum(sum(1 for ac in s.acceptance_criteria if ac.checked) for s in all_sections)
        pct = ac_done / ac_total * 100 if ac_total else 0.0

        total_sections += sec_total
        sections_in_progress += sec_in_prog
        total_ac += ac_total
        done_ac += ac_done
        if doc.frontmatter.status == "in_progress":
            in_progress_specs += 1

        table_rows.append(
            [
                doc.frontmatter.title[:25],
                status_badge(doc.frontmatter.status),
                f"{sec_done}/{sec_total}",
                f"{ac_done}/{ac_total}",
                coverage_text(pct) if ac_total else coverage_text(0.0, label="—"),
            ]
        )

    overall_pct = done_ac / total_ac * 100 if total_ac else 0.0
    overall_display = coverage_text(overall_pct) if total_ac else coverage_text(0.0, label="—")

    get_stdout().print("[heading]Spec Coverage Dashboard[/heading]")
    get_stdout().print(
        f"Overall: {total_specs} specs | {total_sections} sections | {total_ac} ACs | ",
        overall_display,
        " coverage",
        sep="",
    )
    get_stdout().print()

    table = make_table(
        columns=[
            {"name": "Spec", "min_width": 25},
            {"name": "Status", "min_width": 12},
            {"name": "Sections", "justify": "right"},
            {"name": "ACs", "justify": "right"},
            {"name": "Coverage", "justify": "right"},
        ],
        rows=table_rows,
    )
    get_stdout().print(table)
    return 0


def _empty_payload() -> dict:
    return {
        "summary": {
            "specs": 0,
            "sections": 0,
            "ac_total": 0,
            "ac_done": 0,
            "coverage_pct": 0.0,
        },
        "specs": [],
    }


def _build_payload(docs) -> dict:
    """Build the structured JSON payload consumed by the coverage-report action.

    Stable schema — bump a version field if anything changes.
    """
    spec_records: list[dict] = []
    total_sections = 0
    total_ac = 0
    done_ac = 0

    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        sec_total = len(all_sections)
        sec_done = sum(1 for s in all_sections if s.status.state == "done")
        ac_total = sum(len(s.acceptance_criteria) for s in all_sections)
        ac_done = sum(sum(1 for ac in s.acceptance_criteria if ac.checked) for s in all_sections)

        total_sections += sec_total
        total_ac += ac_total
        done_ac += ac_done

        spec_records.append(
            {
                "file": doc.file_path,
                "title": doc.frontmatter.title,
                "status": doc.frontmatter.status,
                "owner": doc.frontmatter.owner,
                "team": doc.frontmatter.team,
                "section_total": sec_total,
                "section_done": sec_done,
                "ac_total": ac_total,
                "ac_done": ac_done,
                "coverage_pct": round(ac_done / ac_total * 100, 1) if ac_total else 0.0,
            }
        )

    overall_pct = round(done_ac / total_ac * 100, 1) if total_ac else 0.0

    return {
        "schema_version": 1,
        "summary": {
            "specs": len(docs),
            "sections": total_sections,
            "ac_total": total_ac,
            "ac_done": done_ac,
            "coverage_pct": overall_pct,
        },
        "specs": spec_records,
    }


def _print_spec_detail(doc):
    """Print section-level breakdown for a single spec."""
    from ._output import get_stdout, status_badge

    all_sections = _flatten_sections(doc.sections)
    ac_total = sum(len(s.acceptance_criteria) for s in all_sections)
    ac_done = sum(sum(1 for ac in s.acceptance_criteria if ac.checked) for s in all_sections)

    get_stdout().print()
    get_stdout().print(f"[heading]{doc.frontmatter.title}[/heading] ({doc.frontmatter.status})")
    get_stdout().print(f"[muted]{'=' * 60}[/muted]")
    get_stdout().print(f"  File: {doc.file_path}")
    get_stdout().print(f"  ACs: {ac_done}/{ac_total} checked")
    get_stdout().print()

    for section in doc.sections:
        sid = section.section_number or section.id
        total = len(section.acceptance_criteria)
        done = sum(1 for ac in section.acceptance_criteria if ac.checked)
        ac_str = f"({done}/{total} ACs)" if total else ""
        dots = "." * max(1, 35 - len(section.title))
        badge = status_badge(section.status.state)
        get_stdout().print(f"  {sid}. {section.title} {dots} ", badge, f" {ac_str}", sep="")

        for child in section.children:
            csid = child.section_number or child.id
            ctotal = len(child.acceptance_criteria)
            cdone = sum(1 for ac in child.acceptance_criteria if ac.checked)
            cac_str = f"({cdone}/{ctotal} ACs)" if ctotal else ""
            cdots = "." * max(1, 31 - len(child.title))
            cbadge = status_badge(child.status.state)
            get_stdout().print(f"    {csid}. {child.title} {cdots} ", cbadge, f" {cac_str}", sep="")
