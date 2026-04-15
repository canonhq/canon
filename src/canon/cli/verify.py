"""canon verify — static verification of spec ACs against codebase."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from ._keywords import extract_keywords
from ._local import (
    _flatten_sections,
    find_section_by_id,
    load_local_config,
    parse_all_local_specs,
)

logger = logging.getLogger(__name__)

VERIFY_LOG_MAX_BYTES = 1_000_000  # 1 MB rotation threshold


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser("verify", help="Verify ACs against codebase")
    parser.add_argument("--section", help="Filter to a single section ID")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-friendly output",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Gate mode — exit nonzero if any in-scope ACs are unchecked",
    )


def run_verify(
    *,
    section: str | None = None,
    gate: bool = False,
    root: Path | None = None,
    json_output: bool = False,
) -> int:
    """Run verify. Returns exit code (0 = success, 2 = filter unresolved)."""
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    if not docs:
        if json_output:
            _emit_json(
                unchecked=[], summary={"total": 0, "likely": 0, "not_started": 0, "unknown": 0}
            )
        else:
            print("No spec files found.")
            if gate:
                print("PASS: no specs in scope")
                _record_gate_run(root, config, section=section, unchecked=0)
        return 0

    if section:
        match = find_section_by_id(docs, section)
        if not match:
            msg = f"Section '{section}' not found."
            if json_output:
                print(json.dumps({"error": msg, "unchecked": [], "summary": {}}))
            else:
                print(msg, file=sys.stderr)
            if gate:
                return 1
            return 2
        doc, sec = match
        if json_output:
            return _verify_section_json(root, doc, sec, gate=gate, config=config)
        unchecked_in_section = _verify_section(root, sec)
        if gate:
            _record_gate_run(root, config, section=section, unchecked=unchecked_in_section)
            return _emit_gate_summary(unchecked_in_section)
        return 0

    # All unchecked ACs across all specs.
    unchecked_records: list[dict] = []
    total = likely = not_started = unknown = 0

    for doc in docs:
        all_sections = _flatten_sections(doc.sections)
        for sec in all_sections:
            unchecked = [ac for ac in sec.acceptance_criteria if not ac.checked]
            if not unchecked:
                continue

            if not json_output:
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

                unchecked_records.append(
                    {
                        "spec": doc.file_path,
                        "section_id": sec.id,
                        "section_title": sec.title,
                        "ac_text": ac.text,
                        "ac_line": ac.line,
                        "status": status,
                    }
                )

                if not json_output:
                    icon = {"likely": "+", "not_started": "-", "unknown": "?"}[status]
                    print(f"  [{icon}] {ac.text}")

    summary = {
        "total": total,
        "likely": likely,
        "not_started": not_started,
        "unknown": unknown,
    }

    if json_output:
        _emit_json(unchecked=unchecked_records, summary=summary)
        if gate:
            _record_gate_run(root, config, section=None, unchecked=total)
            return 1 if total > 0 else 0
        return 0

    if total == 0:
        print("All ACs are checked. Nothing to verify.")
        if gate:
            print("PASS: all in-scope ACs are checked")
            _record_gate_run(root, config, section=None, unchecked=0)
        return 0

    print(f"\nSummary: {total} unchecked ACs")
    print(f"  Likely realized: {likely}")
    print(f"  Not started:     {not_started}")
    print(f"  Unknown:         {unknown}")

    if gate:
        _record_gate_run(root, config, section=None, unchecked=total)
        return _emit_gate_summary(total)
    return 0


def _emit_json(*, unchecked: list[dict], summary: dict) -> None:
    print(json.dumps({"unchecked": unchecked, "summary": summary}, indent=2))


def _verify_section_json(root: Path, doc, section, *, gate: bool = False, config=None) -> int:
    """JSON variant of single-section verify."""
    records = []
    summary = {"total": 0, "likely": 0, "not_started": 0, "unknown": 0, "checked": 0}
    unchecked_count = 0
    for ac in section.acceptance_criteria:
        status = "checked" if ac.checked else _check_ac(root, ac.text)
        if status != "checked":
            unchecked_count += 1
        summary[status] = summary.get(status, 0) + 1
        summary["total"] += 1
        records.append(
            {
                "spec": doc.file_path,
                "section_id": section.id,
                "section_title": section.title,
                "ac_text": ac.text,
                "ac_line": ac.line,
                "status": status,
            }
        )
    print(json.dumps({"unchecked": records, "summary": summary}, indent=2))
    if gate:
        if config is not None:
            _record_gate_run(root, config, section=section.id, unchecked=unchecked_count)
        return 1 if unchecked_count > 0 else 0
    return 0


def _emit_gate_summary(unchecked_count: int) -> int:
    """Emit gate result. Returns exit code (0 = pass, 1 = fail)."""
    if unchecked_count == 0:
        print("\nPASS: all in-scope ACs are checked")
        return 0
    print(f"\nFAIL: {unchecked_count} in-scope ACs lack realization (must be checked)")
    return 1


def _record_gate_run(
    root: Path,
    config,  # CanonConfig
    *,
    section: str | None,
    unchecked: int,
) -> None:
    """Append a VerifyRun record to .canon/verify-log.jsonl when evidence pipeline is enabled.

    Best-effort: any failure here is silently swallowed so verify never breaks
    because of trail logging. Catches `Exception` (not just `OSError`) so a
    future change that could raise `TypeError` from `json.dumps` or
    `ValueError` from `datetime.strftime` doesn't crash verify either.
    """
    if not config.ide.evidence_pipeline.enabled:
        return

    try:
        log_dir = root / ".canon"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / "verify-log.jsonl"

        # Rotate if oversized
        if log_path.exists() and log_path.stat().st_size >= VERIFY_LOG_MAX_BYTES:
            rotated = log_dir / "verify-log.jsonl.1"
            log_path.rename(rotated)

        record = {
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "section": section,
            "mode": "gate",
            "result": "pass" if unchecked == 0 else "fail",
            "gaps": unchecked,
            "conflicts": 0,
        }
        with log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        logger.debug("_record_gate_run failed (best-effort)", exc_info=True)


def _verify_section(root: Path, section) -> int:
    """Verify all ACs in a single section. Returns the number of unchecked ACs."""
    print(f"\n{section.title}")
    print("-" * 40)
    unchecked = 0
    for ac in section.acceptance_criteria:
        if not ac.checked:
            unchecked += 1
        status_label = "checked" if ac.checked else _check_ac(root, ac.text)
        icon = {"checked": "x", "likely": "+", "not_started": "-", "unknown": "?"}[status_label]
        print(f"  [{icon}] {ac.text}")
    return unchecked


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
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        logger.debug("grep failed for keyword %r: %s", keyword, exc)
        return False
