"""canon stale — find specs whose code has churned but the spec hasn't.

Heuristic complement to ``canon audit``. Where audit asks "did the
code drift away from the spec?" via Claude, ``canon stale`` asks the
cheaper git-only question: "is the spec older than the files it
claims to be realized in?" — purely from `git log` timestamps and
line-count deltas.

A spec is flagged as **stale** when:

1. Its file has not been touched in N days (default 90), AND
2. At least one file referenced in its ``<!-- canon:realized-in -->``
   comments has been touched within those same N days, AND
3. The combined number of changed lines across the realization
   files exceeds the configured churn threshold (default 50)

The output is intended to feed the ``stale-spec-check`` GitHub
Action, which opens a rolling tracking issue listing stale specs
with their owners @-mentioned.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from canon.parser.models import SpecDocument

from ._local import _flatten_sections, load_local_config, parse_all_local_specs

logger = logging.getLogger(__name__)


# ─── Data model ───────────────────────────────────────────


@dataclass
class StaleFinding:
    spec: str
    title: str
    owner: str
    spec_age_days: int
    realization_files: list[str] = field(default_factory=list)
    realization_churn_lines: int = 0
    most_recent_realization_age_days: int = 0


# ─── CLI registration ────────────────────────────────────


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "stale",
        help="Find specs whose realization code has churned but the spec hasn't",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=90,
        help="Spec is candidate-stale when not touched in this many days (default: 90)",
    )
    parser.add_argument(
        "--code-churn-threshold",
        type=int,
        default=50,
        help="Combined changed lines across realization files required to flag (default: 50)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-friendly output",
    )


def run_stale(
    *,
    stale_days: int = 90,
    code_churn_threshold: int = 50,
    json_output: bool = False,
    root: Path | None = None,
) -> int:
    """Run stale-spec detection. Returns exit code."""
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    if not docs:
        if json_output:
            print(json.dumps(_empty_payload(stale_days, code_churn_threshold), indent=2))
        else:
            print("No spec files found.")
        return 0

    findings = compute_stale(
        docs=docs,
        root=root,
        stale_days=stale_days,
        code_churn_threshold=code_churn_threshold,
    )

    if json_output:
        print(json.dumps(_to_payload(findings, stale_days, code_churn_threshold), indent=2))
    else:
        _print_human(findings, stale_days, code_churn_threshold)

    return 0


# ─── Core logic ──────────────────────────────────────────


def compute_stale(
    *,
    docs: list[SpecDocument],
    root: Path,
    stale_days: int,
    code_churn_threshold: int,
) -> list[StaleFinding]:
    """Walk every spec and return findings that satisfy all stale criteria."""
    findings: list[StaleFinding] = []
    now = datetime.now(UTC)

    for doc in docs:
        spec_path = doc.file_path
        spec_age = _file_age_days(root, spec_path, now)
        if spec_age is None or spec_age < stale_days:
            continue

        # Collect realization file paths from every AC across the spec.
        realization_files = _collect_realization_files(doc)
        if not realization_files:
            continue

        # For each realization file, find churn within the staleness window.
        # We sum the line counts across files and track the most recent age.
        total_churn = 0
        most_recent_age = stale_days  # cap at the window
        churned_files: list[str] = []
        for rel_file in realization_files:
            churn, age = _file_churn_within(root, rel_file, days=stale_days)
            if churn <= 0:
                continue
            total_churn += churn
            if age is not None and age < most_recent_age:
                most_recent_age = age
            churned_files.append(rel_file)

        if total_churn < code_churn_threshold:
            continue

        findings.append(
            StaleFinding(
                spec=spec_path,
                title=doc.frontmatter.title,
                owner=doc.frontmatter.owner,
                spec_age_days=spec_age,
                realization_files=churned_files,
                realization_churn_lines=total_churn,
                most_recent_realization_age_days=most_recent_age,
            )
        )

    return findings


def _collect_realization_files(doc: SpecDocument) -> list[str]:
    """Return the unique set of file paths referenced by realized-in comments."""
    seen: set[str] = set()
    files: list[str] = []
    for section in _flatten_sections(doc.sections):
        for ac in section.acceptance_criteria:
            for ref in ac.realized_in:
                if ref.file_path and ref.file_path not in seen:
                    seen.add(ref.file_path)
                    files.append(ref.file_path)
    return files


# ─── Git helpers ─────────────────────────────────────────


def _file_age_days(root: Path, rel_path: str, now: datetime) -> int | None:
    """Days since the most recent commit that touched ``rel_path``.

    Returns ``None`` when git can't find any commits for the path
    (file is uncommitted, path doesn't exist, or git isn't available).
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", rel_path],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        last = datetime.fromisoformat(result.stdout.strip())
    except ValueError:
        return None
    delta = now - last
    return max(int(delta.total_seconds() // 86400), 0)


def _file_churn_within(root: Path, rel_path: str, *, days: int) -> tuple[int, int | None]:
    """Compute (changed_lines, most_recent_age_days) for ``rel_path`` within the window.

    Uses ``git log --numstat --since=<days>.days`` to sum added+removed
    lines across every commit that touched the file in the window.
    Returns ``(0, None)`` if the file has no recent activity.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"--since={days}.days",
                "--numstat",
                "--format=%cI",
                "--",
                rel_path,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return 0, None
    if result.returncode != 0:
        return 0, None

    total_added = 0
    total_removed = 0
    most_recent: datetime | None = None
    now = datetime.now(UTC)

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # Heuristic: timestamp lines start with the year, numstat lines start
        # with a digit followed by tab/space.
        if "T" in line[:25] and ":" in line[:25]:
            if most_recent is None:
                with contextlib.suppress(ValueError):
                    most_recent = datetime.fromisoformat(line.strip())
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            total_added += int(parts[0])
            total_removed += int(parts[1])

    age = None
    if most_recent is not None:
        delta = now - most_recent
        age = max(int(delta.total_seconds() // 86400), 0)

    return total_added + total_removed, age


# ─── Output ──────────────────────────────────────────────


def _empty_payload(stale_days: int, churn: int) -> dict:
    return {
        "schema_version": 1,
        "thresholds": {"stale_days": stale_days, "code_churn_threshold": churn},
        "summary": {"stale_count": 0},
        "findings": [],
    }


def _to_payload(findings: list[StaleFinding], stale_days: int, churn: int) -> dict:
    return {
        "schema_version": 1,
        "thresholds": {"stale_days": stale_days, "code_churn_threshold": churn},
        "summary": {"stale_count": len(findings)},
        "findings": [
            {
                "spec": f.spec,
                "title": f.title,
                "owner": f.owner,
                "spec_age_days": f.spec_age_days,
                "realization_files": f.realization_files,
                "realization_churn_lines": f.realization_churn_lines,
                "most_recent_realization_age_days": f.most_recent_realization_age_days,
            }
            for f in findings
        ],
    }


def _print_human(findings: list[StaleFinding], stale_days: int, churn: int) -> None:
    if not findings:
        print(f"No stale specs (threshold: {stale_days} days, {churn}+ churned lines).")
        return

    print(f"Stale specs ({len(findings)}):")
    print(f"  Threshold: spec untouched ≥{stale_days} days, realization churn ≥{churn} lines")
    print()
    for f in findings:
        owner = f"@{f.owner}" if f.owner else "(no owner)"
        print(f"  {f.spec} — {f.title}")
        print(f"    Owner: {owner}")
        print(
            f"    Spec untouched for {f.spec_age_days} days; "
            f"realization files churned {f.realization_churn_lines} lines "
            f"({f.most_recent_realization_age_days} days ago)"
        )
        for rel_file in f.realization_files[:5]:
            print(f"      - {rel_file}")
        if len(f.realization_files) > 5:
            print(f"      …and {len(f.realization_files) - 5} more")
        print()
