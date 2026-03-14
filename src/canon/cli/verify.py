"""canon verify — static verification of spec ACs against codebase."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from ._keywords import extract_keywords
from ._local import (
    _flatten_sections,
    find_section_by_id,
    load_local_config,
    parse_all_local_specs,
)


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("verify", help="Verify ACs against codebase")
    parser.add_argument("--section", help="Filter to a single section ID")


def run_verify(
    *,
    section: str | None = None,
    root: Path | None = None,
) -> None:
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    if not docs:
        print("No spec files found.")
        return

    if section:
        match = find_section_by_id(docs, section)
        if not match:
            print(f"Section '{section}' not found.")
            return
        doc, sec = match
        _verify_section(root, sec)
        return

    # All unchecked ACs across all specs
    total = 0
    likely = 0
    not_started = 0
    unknown = 0

    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        for sec in all_sections:
            unchecked = [ac for ac in sec.acceptance_criteria if not ac.checked]
            if not unchecked:
                continue

            print(f"\n{doc.frontmatter.title} > {sec.title}")
            for ac in unchecked:
                total += 1
                status = _check_ac(root, ac.text)
                if status == "likely":
                    likely += 1
                elif status == "not_started":
                    not_started += 1
                else:
                    unknown += 1
                icon = {"likely": "+", "not_started": "-", "unknown": "?"}[status]
                print(f"  [{icon}] {ac.text}")

    if total == 0:
        print("All ACs are checked. Nothing to verify.")
        return

    print(f"\nSummary: {total} unchecked ACs")
    print(f"  Likely realized: {likely}")
    print(f"  Not started:     {not_started}")
    print(f"  Unknown:         {unknown}")


def _verify_section(root: Path, section) -> None:
    """Verify all ACs in a single section."""
    print(f"\n{section.title}")
    print("-" * 40)
    for ac in section.acceptance_criteria:
        status_label = "checked" if ac.checked else _check_ac(root, ac.text)
        icon = {"checked": "x", "likely": "+", "not_started": "-", "unknown": "?"}[status_label]
        print(f"  [{icon}] {ac.text}")


def _check_ac(root: Path, ac_text: str) -> str:
    """Grep codebase for keywords from AC text. Returns likely/not_started/unknown."""
    keywords = _extract_keywords(ac_text)
    if not keywords:
        return "unknown"

    for kw in keywords:
        if _grep_codebase(root, kw):
            return "likely"
    return "not_started"


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from AC text for grep.

    Delegates to :func:`canon.cli._keywords.extract_keywords`.
    Kept as a local alias for backward compatibility.
    """
    return extract_keywords(text)


def _grep_codebase(root: Path, keyword: str) -> bool:
    """Check if keyword exists in source files."""
    try:
        result = subprocess.run(
            [
                "grep",
                "-rl",
                "--include=*.py",
                "--include=*.ts",
                "--include=*.vue",
                "--include=*.js",
                "--include=*.yaml",
                "--include=*.yml",
                keyword,
                str(root / "src"),
                str(root / "frontend/src"),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False
