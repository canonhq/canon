"""canon release-notes — generate spec-driven release notes from git history.

Walks the spec files at two git refs (typically the previous and
current release tags), diffs them at the section level, and reports
which sections transitioned to ``done`` or accumulated new realization
evidence comments. Used by the release-notes GitHub Action to populate
the GitHub Release body, but also runnable standalone for ad-hoc
release prep.

Notes-worthy events for V1:

- Section status transition into ``done`` (the headline event)
- New ``<!-- canon:realized-in -->`` evidence on a checked AC that
  was already done (informational, grouped under "Additional realization
  evidence")
- Newly added spec files between the two refs (informational, listed
  separately under "New specs")
- Removed spec files (rare but worth mentioning under "Removed")

Out of scope for V1:

- Status transitions other than into done (e.g. todo → in_progress).
  These are routine work, not release notes.
- Re-grouping by tags or labels — adopters can post-process the JSON.
- Spec changes that are pure content edits with no status change.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from canon.parser.models import ParseOptions, SpecDocument
from canon.parser.parse import parse_spec

from ._local import _flatten_sections, discover_spec_files, load_local_config

logger = logging.getLogger(__name__)


# ─── Data model ───────────────────────────────────────────


@dataclass
class CompletedSection:
    spec: str
    spec_title: str
    section_id: str
    section_number: str
    section_title: str
    previous_status: str
    new_realizations: list[str] = field(default_factory=list)


@dataclass
class NewSpec:
    spec: str
    title: str
    status: str


@dataclass
class RemovedSpec:
    spec: str
    title: str


@dataclass
class ReleaseNotes:
    from_ref: str
    to_ref: str
    completed: list[CompletedSection] = field(default_factory=list)
    new_specs: list[NewSpec] = field(default_factory=list)
    removed_specs: list[RemovedSpec] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "from_ref": self.from_ref,
            "to_ref": self.to_ref,
            "summary": {
                "completed": len(self.completed),
                "new_specs": len(self.new_specs),
                "removed_specs": len(self.removed_specs),
            },
            "completed": [
                {
                    "spec": c.spec,
                    "spec_title": c.spec_title,
                    "section_id": c.section_id,
                    "section_number": c.section_number,
                    "section_title": c.section_title,
                    "previous_status": c.previous_status,
                    "new_realizations": c.new_realizations,
                }
                for c in self.completed
            ],
            "new_specs": [
                {"spec": n.spec, "title": n.title, "status": n.status} for n in self.new_specs
            ],
            "removed_specs": [{"spec": r.spec, "title": r.title} for r in self.removed_specs],
        }


# ─── CLI registration ────────────────────────────────────


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "release-notes",
        help="Generate spec-driven release notes between two git refs",
    )
    parser.add_argument(
        "--from",
        dest="from_ref",
        help=(
            "Git ref (tag, branch, or SHA) to compare from. Defaults to the "
            "previous tag returned by `git describe --tags --abbrev=0 HEAD^` "
            "when run inside a repo."
        ),
    )
    parser.add_argument(
        "--to",
        dest="to_ref",
        default="HEAD",
        help="Git ref to compare to (default: HEAD)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-friendly markdown",
    )
    parser.add_argument(
        "--output",
        help="Write output to file instead of stdout",
    )


def run_release_notes(
    *,
    from_ref: str | None,
    to_ref: str = "HEAD",
    json_output: bool = False,
    output: str | None = None,
    root: Path | None = None,
) -> int:
    """Generate release notes between two refs. Returns exit code."""
    root = root or Path.cwd()
    config = load_local_config(root)

    resolved_from = from_ref or _detect_previous_tag(root)
    if not resolved_from:
        msg = (
            "No --from ref provided and could not detect a previous tag. "
            "Pass --from <ref> explicitly."
        )
        if json_output:
            print(json.dumps({"error": msg, **ReleaseNotes("", "").to_dict()}))
        else:
            print(msg, file=sys.stderr)
        return 2

    notes = compute_release_notes(
        from_ref=resolved_from,
        to_ref=to_ref,
        root=root,
        config=config,
    )

    text = json.dumps(notes.to_dict(), indent=2) if json_output else render_markdown(notes)

    if output:
        Path(output).write_text(text + "\n")
        if not json_output:
            print(f"Release notes written to {output}", file=sys.stderr)
    else:
        print(text)

    return 0


# ─── Core logic ──────────────────────────────────────────


def compute_release_notes(
    *,
    from_ref: str,
    to_ref: str,
    root: Path,
    config,
) -> ReleaseNotes:
    """Compare specs at two refs and return a ReleaseNotes payload.

    Walks the union of spec files visible at both refs. For each spec
    that exists at both refs, parses both versions and compares
    section-level status transitions and realization-comment growth.
    Specs that only exist at one ref are reported as new/removed.
    """
    spec_files = discover_spec_files(root, config)
    relative_paths = [str(p.relative_to(root)) for p in spec_files]

    # Also discover specs that exist at from_ref but no longer at to_ref —
    # `discover_spec_files` only sees the working tree, so we need to ask git.
    from_paths = _list_specs_at_ref(root, from_ref, config)

    all_paths = sorted(set(relative_paths) | set(from_paths))

    notes = ReleaseNotes(from_ref=from_ref, to_ref=to_ref)

    for path in all_paths:
        from_doc = _parse_at_ref(root, from_ref, path)
        to_doc = _parse_at_ref(root, to_ref, path)

        if from_doc is None and to_doc is not None:
            notes.new_specs.append(
                NewSpec(
                    spec=path,
                    title=to_doc.frontmatter.title,
                    status=to_doc.frontmatter.status,
                )
            )
            continue

        if from_doc is not None and to_doc is None:
            notes.removed_specs.append(RemovedSpec(spec=path, title=from_doc.frontmatter.title))
            continue

        if from_doc is None or to_doc is None:
            continue

        notes.completed.extend(_diff_sections(from_doc, to_doc))

    return notes


def _diff_sections(from_doc: SpecDocument, to_doc: SpecDocument) -> list[CompletedSection]:
    """Find sections that transitioned to done between two parsed docs."""
    completed: list[CompletedSection] = []

    from_sections = {s.id: s for s in _flatten_sections(from_doc.sections)}
    to_sections = {s.id: s for s in _flatten_sections(to_doc.sections)}

    for section_id, to_section in to_sections.items():
        if to_section.status.state != "done":
            continue
        from_section = from_sections.get(section_id)
        if from_section is None:
            # New section that's already done — count as completed
            previous = "(new)"
        elif from_section.status.state == "done":
            # Already done — not a transition
            continue
        else:
            previous = from_section.status.state

        # Collect realization references that exist on the to-side but not on
        # the from-side. These are the new pieces of evidence that landed in
        # this release window. Use a set comparison so identical comments
        # don't double-report.
        from_realizations: set[str] = set()
        if from_section is not None:
            for ac in from_section.acceptance_criteria:
                for r in ac.realized_in:
                    from_realizations.add(_realization_key(r))

        new_realizations: list[str] = []
        for ac in to_section.acceptance_criteria:
            for r in ac.realized_in:
                key = _realization_key(r)
                if key and key not in from_realizations:
                    new_realizations.append(key)

        completed.append(
            CompletedSection(
                spec=to_doc.file_path,
                spec_title=to_doc.frontmatter.title,
                section_id=section_id,
                section_number=to_section.section_number or "",
                section_title=to_section.title,
                previous_status=previous,
                new_realizations=new_realizations,
            )
        )

    return completed


def _realization_key(ref) -> str:
    """Stable string key for a RealizationRef so set membership works."""
    pr = f"PR#{ref.pr_number}" if ref.pr_number else "audit"
    if ref.lines:
        return f"{pr} {ref.file_path}:{ref.lines}"
    return f"{pr} {ref.file_path}"


# ─── Markdown rendering ──────────────────────────────────


def render_markdown(notes: ReleaseNotes) -> str:
    """Render release notes as a GitHub Release body."""
    lines: list[str] = []
    lines.append(f"# Release notes — {notes.to_ref}")
    lines.append("")
    lines.append(f"_Comparing `{notes.from_ref}` → `{notes.to_ref}`_")
    lines.append("")

    if not notes.completed and not notes.new_specs and not notes.removed_specs:
        lines.append("No spec-level changes in this release.")
        return "\n".join(lines)

    if notes.completed:
        lines.append(f"## Completed ({len(notes.completed)})")
        lines.append("")
        # Group by spec for readability
        by_spec: dict[str, list[CompletedSection]] = {}
        for c in notes.completed:
            by_spec.setdefault(c.spec, []).append(c)

        for spec_path, sections in sorted(by_spec.items()):
            spec_title = sections[0].spec_title or spec_path
            lines.append(f"### `{spec_path}` — {spec_title}")
            lines.append("")
            for c in sections:
                section_label = (
                    f"§{c.section_number} {c.section_title}"
                    if c.section_number
                    else c.section_title
                )
                lines.append(f"- **{section_label}** _(was: {c.previous_status})_")
                if c.new_realizations:
                    for ev in c.new_realizations[:5]:
                        lines.append(f"  - {ev}")
                    if len(c.new_realizations) > 5:
                        lines.append(f"  - …and {len(c.new_realizations) - 5} more")
            lines.append("")

    if notes.new_specs:
        lines.append(f"## New specs ({len(notes.new_specs)})")
        lines.append("")
        for n in notes.new_specs:
            lines.append(f"- `{n.spec}` — {n.title} _(status: {n.status})_")
        lines.append("")

    if notes.removed_specs:
        lines.append(f"## Removed specs ({len(notes.removed_specs)})")
        lines.append("")
        for r in notes.removed_specs:
            lines.append(f"- `{r.spec}` — {r.title}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ─── Git helpers ─────────────────────────────────────────


def _detect_previous_tag(root: Path) -> str | None:
    """Try to find the previous git tag relative to HEAD^.

    Returns None when not in a git repo or no prior tag exists.
    """
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "HEAD^"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _list_specs_at_ref(root: Path, ref: str, config) -> list[str]:
    """List spec file paths visible at a given git ref.

    Mirrors the discover_spec_files glob patterns from CANON.yaml,
    but reads the file list from `git ls-tree` so it sees specs that
    have since been deleted from the working tree.
    """
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ref],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []
    if result.returncode != 0:
        return []

    all_files = set(result.stdout.splitlines())

    # Apply the glob patterns from CANON.yaml manually using fnmatch
    import fnmatch

    matched: list[str] = []
    for pattern in config.specs.doc_paths:
        # patterns from CANON.yaml are repo-relative globs
        for path in all_files:
            if fnmatch.fnmatch(path, pattern):
                # skip _template files
                name = Path(path).name
                if name.startswith("_"):
                    continue
                matched.append(path)
    return sorted(set(matched))


def _parse_at_ref(root: Path, ref: str, rel_path: str) -> SpecDocument | None:
    """Parse a spec file as it existed at a specific git ref.

    Returns None if the file does not exist at that ref or cannot be
    read.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{rel_path}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout
    if not raw:
        return None
    try:
        return parse_spec(raw, ParseOptions(file_path=rel_path, include_content=True)).document
    except Exception as exc:
        logger.warning("Could not parse %s at ref %s: %s", rel_path, ref, exc)
        return None
