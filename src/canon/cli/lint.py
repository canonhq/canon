"""canon lint — static structural validation of spec files.

Fast, network-free, Claude-free. Checks spec file shape:
frontmatter schema, section numbering monotonicity, acceptance criteria
format, status comment syntax, and depends_on resolvability.

Unlike ``canon verify`` (static AC vs. code) and ``canon audit`` (AI-evaluated
drift), ``canon lint`` only looks at spec file structure. It is the cheapest
layer in the lint → verify → audit ladder and is safe to run on every PR.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from canon.parser.models import Diagnostic, ParseOptions, SpecDocument
from canon.parser.parse import parse_spec

from ._local import discover_spec_files, load_local_config

# ─── Data model ───────────────────────────────────────────

Severity = str  # "error" | "warning" | "info"


@dataclass
class LintIssue:
    """A single lint finding tied to a file and optional line."""

    file_path: str
    severity: Severity
    rule: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict:
        return {
            "file": self.file_path,
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
            "line": self.line,
        }

    def format_human(self) -> str:
        loc = f"{self.file_path}:{self.line}" if self.line else self.file_path
        return f"{loc}: {self.severity}: [{self.rule}] {self.message}"


# ─── CLI registration ────────────────────────────────────


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "lint",
        help="Validate spec file structure (frontmatter, sections, ACs)",
    )
    parser.add_argument(
        "--spec",
        help="Lint a single spec by partial path match (default: all discovered specs)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-friendly output",
    )
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Treat warnings as errors (affects exit code)",
    )


def run_lint(
    *,
    spec: str | None = None,
    json_output: bool = False,
    warnings_as_errors: bool = False,
    root: Path | None = None,
) -> int:
    """Run lint across discovered specs. Returns exit code."""
    root = root or Path.cwd()
    config = load_local_config(root)
    all_spec_files = discover_spec_files(root, config)

    # `--spec` narrows what gets *reported*, but cross-file checks like
    # depends_on.unresolved still need to see the full spec set so a
    # filtered run doesn't false-positive on dependencies that exist
    # outside the filter.
    if spec:
        spec_files = [p for p in all_spec_files if spec in str(p)]
        if not spec_files:
            msg = f"No spec matching '{spec}' found."
            if json_output:
                print(json.dumps({"error": msg, "issues": []}))
            else:
                print(msg, file=sys.stderr)
            return 2
    else:
        spec_files = all_spec_files

    if not spec_files:
        msg = "No spec files found."
        if json_output:
            print(json.dumps({"issues": [], "summary": {"files": 0}}))
        else:
            print(msg)
        return 0

    all_issues: list[LintIssue] = []
    parsed_docs: list[SpecDocument] = []

    # First pass: parse each filtered spec and collect per-file issues.
    for path in spec_files:
        rel = str(path.relative_to(root))
        raw = path.read_text()
        result = parse_spec(raw, ParseOptions(file_path=rel, include_content=True))
        parsed_docs.append(result.document)

        # Parser-emitted diagnostics become lint issues directly.
        for diag in result.diagnostics:
            all_issues.append(_diagnostic_to_issue(rel, diag))

        # Additional lint-specific checks the parser doesn't do.
        all_issues.extend(_check_frontmatter(rel, result.document))
        all_issues.extend(_check_section_numbering(rel, result.document))
        all_issues.extend(_check_acceptance_criteria(rel, result.document))
        all_issues.extend(_check_status_comments(rel, raw))

    # Second pass: cross-file checks (depends_on resolvability). Use the
    # FULL spec_files set so a filtered run can still resolve dependencies
    # against the rest of the repo.
    all_issues.extend(_check_depends_on(parsed_docs, all_spec_files, root))

    # Report.
    return _report(all_issues, spec_files, json_output, warnings_as_errors)


# ─── Rules ────────────────────────────────────────────────


def _diagnostic_to_issue(file_path: str, diag: Diagnostic) -> LintIssue:
    """Wrap a parser diagnostic as a lint issue under the 'parser' rule family."""
    return LintIssue(
        file_path=file_path,
        severity=diag.severity,
        rule="parser",
        message=diag.message,
        line=diag.line,
    )


def _check_frontmatter(file_path: str, doc: SpecDocument) -> list[LintIssue]:
    """Validate frontmatter required fields beyond what the parser catches."""
    issues: list[LintIssue] = []
    fm = doc.frontmatter

    if not fm.title.strip():
        issues.append(LintIssue(file_path, "error", "frontmatter.title", "title is empty"))
    if not fm.owner.strip():
        issues.append(
            LintIssue(
                file_path,
                "warning",
                "frontmatter.owner",
                "owner is empty — every spec should name a responsible owner",
            )
        )
    if not fm.team.strip():
        issues.append(
            LintIssue(
                file_path,
                "warning",
                "frontmatter.team",
                "team is empty — every spec should name an owning team",
            )
        )
    if fm.created and not _is_iso_date(fm.created):
        issues.append(
            LintIssue(
                file_path,
                "warning",
                "frontmatter.created",
                f"created='{fm.created}' is not a YYYY-MM-DD date",
            )
        )
    if fm.updated and not _is_iso_date(fm.updated):
        issues.append(
            LintIssue(
                file_path,
                "warning",
                "frontmatter.updated",
                f"updated='{fm.updated}' is not a YYYY-MM-DD date",
            )
        )

    return issues


def _check_section_numbering(file_path: str, doc: SpecDocument) -> list[LintIssue]:
    """Top-level sections should be numbered monotonically starting from 1."""
    issues: list[LintIssue] = []

    numbered_top = [s for s in doc.sections if s.section_number]
    if not numbered_top:
        return issues

    prev_major = 0
    for section in numbered_top:
        # section_number is like "1" or "1.2"; we care about the top-level integer.
        head = section.section_number.split(".")[0]
        try:
            major = int(head)
        except ValueError:
            continue
        if major <= prev_major:
            issues.append(
                LintIssue(
                    file_path,
                    "warning",
                    "section.numbering",
                    f"section {section.section_number} not monotonically increasing from {prev_major}",
                    line=section.start_line,
                )
            )
        else:
            prev_major = major

    return issues


def _check_acceptance_criteria(file_path: str, doc: SpecDocument) -> list[LintIssue]:
    """Flag sections that are todo/in_progress but have no acceptance criteria."""
    issues: list[LintIssue] = []

    def walk(sections):
        for section in sections:
            if section.status.state in ("todo", "in_progress"):
                # Check self first, then recurse — parent with no direct ACs
                # may legitimately have them on children.
                has_acs = bool(section.acceptance_criteria) or any(
                    _has_any_acs(child) for child in section.children
                )
                if not has_acs and not section.children:
                    issues.append(
                        LintIssue(
                            file_path,
                            "warning",
                            "ac.missing",
                            f"section '{section.title}' is {section.status.state} but has no acceptance criteria",
                            line=section.start_line,
                        )
                    )
            walk(section.children)

    walk(doc.sections)
    return issues


def _has_any_acs(section) -> bool:
    if section.acceptance_criteria:
        return True
    return any(_has_any_acs(c) for c in section.children)


def _check_status_comments(file_path: str, raw: str) -> list[LintIssue]:
    """Flag malformed <!-- canon:... --> comments that the parser couldn't handle.

    The parser silently ignores malformed comments. Lint surfaces them as
    explicit warnings so authors notice typos.

    Skips inline code spans (text between single backticks) and fenced code
    blocks (text between triple backticks) so documentation specs that
    describe the comment syntax don't false-positive.
    """
    issues: list[LintIssue] = []
    import re

    # Look for comments that *look* like canon/specwright directives but don't match
    # the expected patterns.
    candidate = re.compile(r"<!--\s*(canon|specwright):([^>]*?)-->")
    valid_keywords = {"system", "ticket", "realized-in", "delta"}

    in_fenced_block = False
    fence_re = re.compile(r"^\s*```")

    for i, line in enumerate(raw.splitlines(), start=1):
        if fence_re.match(line):
            in_fenced_block = not in_fenced_block
            continue
        if in_fenced_block:
            continue

        # Strip inline code spans before matching. Markdown inline code is
        # any text between single backticks on the same line.
        stripped = re.sub(r"`[^`\n]*`", "", line)

        for match in candidate.finditer(stripped):
            body = match.group(2).strip()
            keyword = body.split(":", 1)[0] if ":" in body else body
            if keyword not in valid_keywords:
                issues.append(
                    LintIssue(
                        file_path,
                        "warning",
                        "comment.unknown",
                        f"unknown canon comment keyword '{keyword}' — expected one of: {', '.join(sorted(valid_keywords))}",
                        line=i,
                    )
                )

    return issues


def _check_depends_on(
    docs: list[SpecDocument],
    spec_files: list[Path],
    root: Path,
) -> list[LintIssue]:
    """Every depends_on entry should resolve to another discovered spec file.

    Matching rule: depends_on value matches the basename without extension
    (e.g. ``changelog-automation``) against any discovered spec file's stem.
    """
    issues: list[LintIssue] = []
    stems = {p.stem for p in spec_files}

    for doc in docs:
        for dep in doc.frontmatter.depends_on:
            dep_clean = dep.strip()
            if not dep_clean:
                continue
            # Allow depends_on entries to reference stems or full paths.
            dep_stem = Path(dep_clean).stem
            if dep_stem not in stems:
                issues.append(
                    LintIssue(
                        file_path=doc.file_path,
                        severity="warning",
                        rule="depends_on.unresolved",
                        message=f"depends_on '{dep_clean}' does not resolve to any discovered spec file",
                    )
                )

    return issues


def _is_iso_date(value: str) -> bool:
    """Loose YYYY-MM-DD check — does not validate actual calendar correctness."""
    import re

    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()))


# ─── Reporting ────────────────────────────────────────────


def _report(
    issues: list[LintIssue],
    spec_files: list[Path],
    json_output: bool,
    warnings_as_errors: bool,
) -> int:
    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    info_count = sum(1 for i in issues if i.severity == "info")

    if json_output:
        payload = {
            "issues": [i.to_dict() for i in issues],
            "summary": {
                "files": len(spec_files),
                "errors": error_count,
                "warnings": warning_count,
                "info": info_count,
            },
        }
        print(json.dumps(payload, indent=2))
    else:
        for issue in issues:
            print(issue.format_human())

        if issues:
            print()
        print(
            f"canon lint: {len(spec_files)} file(s) checked, "
            f"{error_count} error(s), {warning_count} warning(s), {info_count} info"
        )

    if error_count > 0:
        return 1
    if warnings_as_errors and warning_count > 0:
        return 1
    return 0
