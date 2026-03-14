"""canon status — coverage dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._local import _flatten_sections, load_local_config, parse_all_local_specs


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("status", help="Show spec coverage dashboard")
    parser.add_argument("--spec", help="Show detail for a single spec file")


def run_status(*, spec: str | None = None, root: Path | None = None) -> None:
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    if not docs:
        print("No spec files found.")
        return

    # Single-spec detail view
    if spec:
        matches = [d for d in docs if spec in d.file_path]
        if not matches:
            print(f"No spec matching '{spec}' found.")
            return
        for doc in matches:
            _print_spec_detail(doc)
        return

    # Aggregate metrics
    total_specs = len(docs)
    total_sections = 0
    total_ac = 0
    done_ac = 0

    rows: list[tuple[str, str, str, str, str]] = []
    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        sec_total = len(all_sections)
        sec_done = sum(1 for s in all_sections if s.status.state == "done")
        ac_total = sum(len(s.acceptance_criteria) for s in all_sections)
        ac_done = sum(sum(1 for ac in s.acceptance_criteria if ac.checked) for s in all_sections)
        pct = f"{ac_done / ac_total * 100:.0f}%" if ac_total else "—"

        total_sections += sec_total
        total_ac += ac_total
        done_ac += ac_done

        rows.append(
            (
                doc.frontmatter.title[:25],
                doc.frontmatter.status,
                f"{sec_done}/{sec_total}",
                f"{ac_done}/{ac_total}",
                pct,
            )
        )

    overall_pct = f"{done_ac / total_ac * 100:.0f}%" if total_ac else "—"

    print("Spec Coverage Dashboard")
    print("=" * 60)
    print(
        f"Overall: {total_specs} specs | {total_sections} sections | {total_ac} ACs | {overall_pct} coverage"
    )
    print()
    print(f"  {'Spec':<27} {'Status':<14} {'Sections':<10} {'ACs':<8} {'Coverage':<8}")
    print(f"  {'-' * 27} {'-' * 14} {'-' * 10} {'-' * 8} {'-' * 8}")
    for title, status, secs, acs, pct in rows:
        print(f"  {title:<27} {status:<14} {secs:<10} {acs:<8} {pct:<8}")


def _print_spec_detail(doc):
    """Print section-level breakdown for a single spec."""
    all_sections = _flatten_sections(doc.sections)
    ac_total = sum(len(s.acceptance_criteria) for s in all_sections)
    ac_done = sum(sum(1 for ac in s.acceptance_criteria if ac.checked) for s in all_sections)

    print(f"\n{doc.frontmatter.title} ({doc.frontmatter.status})")
    print("=" * 60)
    print(f"  File: {doc.file_path}")
    print(f"  ACs: {ac_done}/{ac_total} checked")
    print()

    for section in doc.sections:
        sid = section.section_number or section.id
        indent = "  "
        total = len(section.acceptance_criteria)
        done = sum(1 for ac in section.acceptance_criteria if ac.checked)
        ac_str = f"({done}/{total} ACs)" if total else ""
        print(
            f"{indent}{sid}. {section.title} {'.' * (35 - len(section.title))} {section.status.state} {ac_str}"
        )

        for child in section.children:
            csid = child.section_number or child.id
            ctotal = len(child.acceptance_criteria)
            cdone = sum(1 for ac in child.acceptance_criteria if ac.checked)
            cac_str = f"({cdone}/{ctotal} ACs)" if ctotal else ""
            print(
                f"    {csid}. {child.title} {'.' * (31 - len(child.title))} {child.status.state} {cac_str}"
            )
