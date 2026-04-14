"""canon export — emit a compliance-grade audit trail of every AC.

Walks every spec in the repo and emits one row per acceptance
criterion, capturing the spec path, section coordinates, AC text and
status, all realization references, owner, team, and the file's last-
updated date. Designed for regulated environments where auditors need
to see "for every requirement, here's the code that realizes it and
when it was last touched."

Output formats:

- ``json`` — schema-versioned ``{schema_version, generated_at, rows[]}``
  payload, easy to feed into downstream pipelines
- ``csv`` — flat one-row-per-AC table for spreadsheet import; lists
  are joined with semicolons since CSV doesn't have nested fields

The action wrapper uploads the result as a workflow artifact and
optionally commits it to a long-lived ``compliance/`` branch for
retention.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from canon.parser.models import SpecDocument

from ._local import _flatten_sections, load_local_config, parse_all_local_specs

logger = logging.getLogger(__name__)


# ─── Data model ───────────────────────────────────────────


@dataclass
class ExportRow:
    spec: str
    spec_title: str
    spec_status: str
    owner: str
    team: str
    section_id: str
    section_number: str
    section_title: str
    section_status: str
    ac_text: str
    ac_checked: bool
    ac_line: int
    realizations: list[str] = field(default_factory=list)
    spec_last_modified: str = ""

    def to_csv_row(self) -> dict[str, str]:
        """Flatten for CSV — list fields are semicolon-joined."""
        d = asdict(self)
        d["ac_checked"] = "true" if self.ac_checked else "false"
        d["realizations"] = "; ".join(self.realizations)
        return d


CSV_FIELDS = [
    "spec",
    "spec_title",
    "spec_status",
    "owner",
    "team",
    "section_id",
    "section_number",
    "section_title",
    "section_status",
    "ac_text",
    "ac_checked",
    "ac_line",
    "realizations",
    "spec_last_modified",
]


# ─── CLI registration ────────────────────────────────────


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "export",
        help="Emit a compliance audit trail of every AC across every spec",
    )
    parser.add_argument(
        "--format",
        dest="export_format",
        default="json",
        choices=["json", "csv"],
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--output",
        help="Write to file instead of stdout",
    )
    parser.add_argument(
        "--spec",
        help="Filter to a single spec file (substring match)",
    )


def run_export(
    *,
    export_format: str = "json",
    output: str | None = None,
    spec: str | None = None,
    root: Path | None = None,
) -> int:
    """Walk specs and emit a compliance audit trail. Returns exit code."""
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    if spec:
        docs = [d for d in docs if spec in d.file_path]

    rows = list(build_rows(docs, root))
    text = _render(rows, export_format)

    if output:
        Path(output).write_text(text)
        print(f"Wrote {len(rows)} row(s) to {output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")

    return 0


# ─── Core walk ───────────────────────────────────────────


def build_rows(docs: list[SpecDocument], root: Path):
    """Yield one ExportRow per AC across every spec."""
    for doc in docs:
        last_mod = _file_last_modified(root, doc.file_path)
        for section in _flatten_sections(doc.sections):
            for ac in section.acceptance_criteria:
                yield ExportRow(
                    spec=doc.file_path,
                    spec_title=doc.frontmatter.title,
                    spec_status=doc.frontmatter.status,
                    owner=doc.frontmatter.owner,
                    team=doc.frontmatter.team,
                    section_id=section.id,
                    section_number=section.section_number or "",
                    section_title=section.title,
                    section_status=section.status.state,
                    ac_text=ac.text,
                    ac_checked=ac.checked,
                    ac_line=ac.line,
                    realizations=[_format_realization(r) for r in ac.realized_in],
                    spec_last_modified=last_mod,
                )


def _format_realization(ref) -> str:
    """Stable string form for an evidence reference, used in both JSON and CSV."""
    pr = f"PR#{ref.pr_number}" if ref.pr_number else "audit"
    if ref.lines:
        return f"{pr} {ref.file_path}:{ref.lines}"
    return f"{pr} {ref.file_path}"


# ─── Rendering ───────────────────────────────────────────


def _render(rows: list[ExportRow], export_format: str) -> str:
    if export_format == "json":
        return _render_json(rows)
    if export_format == "csv":
        return _render_csv(rows)
    raise ValueError(f"unknown format: {export_format}")


def _render_json(rows: list[ExportRow]) -> str:
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "rows": len(rows),
            "specs": len({r.spec for r in rows}),
            "checked": sum(1 for r in rows if r.ac_checked),
            "unchecked": sum(1 for r in rows if not r.ac_checked),
        },
        "rows": [
            {
                "spec": r.spec,
                "spec_title": r.spec_title,
                "spec_status": r.spec_status,
                "owner": r.owner,
                "team": r.team,
                "section_id": r.section_id,
                "section_number": r.section_number,
                "section_title": r.section_title,
                "section_status": r.section_status,
                "ac_text": r.ac_text,
                "ac_checked": r.ac_checked,
                "ac_line": r.ac_line,
                "realizations": r.realizations,
                "spec_last_modified": r.spec_last_modified,
            }
            for r in rows
        ],
    }
    return json.dumps(payload, indent=2)


def _render_csv(rows: list[ExportRow]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row.to_csv_row())
    return buffer.getvalue()


# ─── Git helpers ─────────────────────────────────────────


def _file_last_modified(root: Path, rel_path: str) -> str:
    """Return the ISO-8601 commit date of the most recent change to ``rel_path``.

    Returns an empty string when git can't find any commits for the path.
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
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()
