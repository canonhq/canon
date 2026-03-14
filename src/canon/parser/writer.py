"""Spec writer — inserts/updates canon comments in raw markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import frontmatter
from pydantic import BaseModel

from .models import SpecDocument


def update_frontmatter_field(raw: str, field: str, value: str) -> str:
    """Update or insert a field in YAML frontmatter. Returns updated markdown.

    Preserves existing field order; new fields are appended to the end.
    """
    post = frontmatter.loads(raw)
    post.metadata[field] = value
    return frontmatter.dumps(post)


class TicketLinkInsertion(BaseModel):
    heading_line: int  # 1-based
    system: str
    ticket_id: str


class StatusUpdate(BaseModel):
    section_number: str
    new_state: str


_STATUS_COMMENT_RE = re.compile(r"^<!--\s*(?:specwright|canon):system:(\S+)\s+status:(\S+)\s*-->$")


def insert_ticket_links(doc: SpecDocument, insertions: list[TicketLinkInsertion]) -> str:
    """Insert ticket link comments after section headings."""
    if not insertions:
        return doc.raw

    lines = doc.raw.split("\n")
    sorted_insertions = sorted(insertions, key=lambda ins: ins.heading_line)

    offset = 0
    for ins in sorted_insertions:
        comment = f"<!-- canon:ticket:{ins.system}:{ins.ticket_id} -->"
        heading_idx = ins.heading_line - 1 + offset

        # Skip past heading, blank lines, and existing canon/specwright comments
        insert_idx = heading_idx + 1
        while insert_idx < len(lines):
            line = lines[insert_idx].strip()
            if line == "" or line.startswith("<!-- specwright:") or line.startswith("<!-- canon:"):
                insert_idx += 1
            else:
                break

        lines.insert(insert_idx, comment)
        offset += 1  # noqa: SIM113 — offset tracks insertions, not enumeration index

    return "\n".join(lines)


def insert_status_comment(raw: str, heading_line: int, section_number: str, state: str) -> str:
    """Insert a status comment after a section heading that lacks one.

    Uses the same insertion pattern as ``insert_ticket_links()``: skips past
    blank lines and existing canon/specwright comments after the heading, then
    inserts the new status comment.

    Args:
        raw: Full markdown text.
        heading_line: 1-based line number of the section heading.
        section_number: Section number (e.g. "1.1").
        state: Status state (e.g. "todo", "in_progress", "done").

    Returns:
        Updated markdown text.
    """
    lines = raw.split("\n")
    comment = f"<!-- canon:system:{section_number} status:{state} -->"
    heading_idx = heading_line - 1

    # Skip past heading, blank lines, and existing canon/specwright comments
    insert_idx = heading_idx + 1
    while insert_idx < len(lines):
        line = lines[insert_idx].strip()
        if line == "" or line.startswith("<!-- specwright:") or line.startswith("<!-- canon:"):
            insert_idx += 1
        else:
            break

    lines.insert(insert_idx, comment)
    return "\n".join(lines)


def update_status_comments(doc: SpecDocument, updates: list[StatusUpdate]) -> str:
    """Find and replace status comments in-place."""
    if not updates:
        return doc.raw

    update_map = {u.section_number: u.new_state for u in updates}
    lines = doc.raw.split("\n")

    for i, line in enumerate(lines):
        match = _STATUS_COMMENT_RE.match(line.strip())
        if not match:
            continue
        section_num = match.group(1)
        new_state = update_map.get(section_num)
        if new_state is not None:
            lines[i] = f"<!-- canon:system:{section_num} status:{new_state} -->"
            del update_map[section_num]

    return "\n".join(lines)


@dataclass
class RealizationInsertion:
    """A realization evidence comment to insert after an AC checkbox."""

    ac_text: str
    pr_number: int | None = None
    file_path: str = ""
    lines: str = ""  # e.g. "42-60"


_CHECKBOX_RE = re.compile(r"^(\s*)-\s*\[([ xX])\]\s+(.+)$")
_REALIZATION_COMMENT_RE = re.compile(
    r"^<!--\s*(?:specwright|canon):realized-in:(?:PR#\d+|audit)\s+file:\S+\s*-->$"
)


def insert_realization_comments(
    doc: SpecDocument,
    insertions: list[RealizationInsertion],
) -> str:
    """Insert realization evidence comments after matching AC checkboxes."""
    if not insertions:
        return doc.raw

    # Build lookup: normalized AC text -> list of insertions
    ac_map: dict[str, list[RealizationInsertion]] = {}
    for ins in insertions:
        key = ins.ac_text.strip().lower()
        ac_map.setdefault(key, []).append(ins)

    lines = doc.raw.split("\n")
    result: list[str] = []
    i = 0

    while i < len(lines):
        result.append(lines[i])
        match = _CHECKBOX_RE.match(lines[i])
        if match:
            ac_text = match.group(3).strip().lower()
            pending = ac_map.get(ac_text, [])
            if pending:
                # Skip past existing realization comments
                while i + 1 < len(lines) and _REALIZATION_COMMENT_RE.match(lines[i + 1].strip()):
                    i += 1
                    result.append(lines[i])

                # Insert new comments
                for ins in pending:
                    file_ref = ins.file_path
                    if ins.lines:
                        file_ref += f":{ins.lines}"
                    source = f"PR#{ins.pr_number}" if ins.pr_number is not None else "audit"
                    comment = f"<!-- canon:realized-in:{source} file:{file_ref} -->"
                    # Don't duplicate (check both canon: and legacy specwright: forms)
                    legacy_comment = comment.replace(
                        "canon:realized-in:", "specwright:realized-in:"
                    )
                    if comment not in result and legacy_comment not in result:
                        result.append(comment)
                del ac_map[ac_text]
        i += 1

    return "\n".join(result)


def check_off_acs(raw: str, ac_texts: list[str]) -> str:
    """Check off acceptance criteria by flipping ``- [ ]`` → ``- [x]``.

    Matching is case-insensitive on the AC text.  Already-checked items are
    left unchanged (idempotent).  Indentation is preserved.
    """
    if not ac_texts:
        return raw

    targets = {t.strip().lower() for t in ac_texts}
    lines = raw.split("\n")

    for i, line in enumerate(lines):
        match = _CHECKBOX_RE.match(line)
        if match and match.group(3).strip().lower() in targets and match.group(2) == " ":
            indent = match.group(1)
            text = match.group(3)
            lines[i] = f"{indent}- [x] {text}"

    return "\n".join(lines)


# ─── Delta Comments ─────────────────────────────────────


class DeltaInsertion(BaseModel):
    heading_line: int  # 1-based
    delta_type: Literal["added", "modified", "removed"]


# Anchored — used with match() on stripped lines for in-place replacement.
# See also parse.py::DELTA_RE (unanchored, for search()).
_DELTA_COMMENT_RE = re.compile(
    r"^<!--\s*(?:specwright|canon):delta:(added|modified|removed)\s*-->$"
)
# Permissive version for removal — matches hand-written comments with extra whitespace.
# Used on unstripped lines to catch leading/trailing whitespace around comments.
_DELTA_COMMENT_STRIP_RE = re.compile(
    r"^\s*<!--\s*(?:specwright|canon):delta:(added|modified|removed)\s*-->\s*$"
)


def insert_delta_comments(doc: SpecDocument, insertions: list[DeltaInsertion]) -> str:
    """Insert or replace delta annotation comments after section headings.

    If a section already has a delta comment, it is replaced with the new value.
    Raises ValueError if duplicate heading_line values are provided.
    """
    if not insertions:
        return doc.raw

    # Guard against duplicate heading_line values — each heading should have
    # at most one delta annotation.
    heading_lines = [ins.heading_line for ins in insertions]
    if len(heading_lines) != len(set(heading_lines)):
        raise ValueError(f"Duplicate heading_line values in delta insertions: {heading_lines}")

    lines = doc.raw.split("\n")
    sorted_insertions = sorted(insertions, key=lambda ins: ins.heading_line)

    offset = 0
    for ins in sorted_insertions:
        comment = f"<!-- canon:delta:{ins.delta_type} -->"
        heading_idx = ins.heading_line - 1 + offset

        # Scan past heading, blank lines, and existing canon/specwright comments.
        # Collect all existing delta comment indices so we can replace the first
        # and remove any extras (possible from manual editing or prior bugs).
        insert_idx = heading_idx + 1
        existing_delta_indices: list[int] = []
        while insert_idx < len(lines):
            line = lines[insert_idx].strip()
            if _DELTA_COMMENT_RE.match(line):
                existing_delta_indices.append(insert_idx)
                insert_idx += 1
            elif (
                line == "" or line.startswith("<!-- specwright:") or line.startswith("<!-- canon:")
            ):
                insert_idx += 1
            else:
                break

        if existing_delta_indices:
            # Replace the first existing delta, remove any extras
            lines[existing_delta_indices[0]] = comment
            for extra_idx in reversed(existing_delta_indices[1:]):
                del lines[extra_idx]
                offset -= 1
        else:
            lines.insert(insert_idx, comment)
            offset += 1

    return "\n".join(lines)


def remove_delta_comments(raw: str) -> str:
    """Strip all canon/specwright delta comments from raw markdown.

    Uses a permissive regex to also match hand-written comments with extra whitespace.
    """
    lines = raw.split("\n")
    return "\n".join(line for line in lines if not _DELTA_COMMENT_STRIP_RE.match(line))
