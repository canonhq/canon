"""Spec markdown parser — frontmatter, sections, comments, acceptance criteria."""

from __future__ import annotations

import re
from typing import Literal, cast

import frontmatter

from .models import (
    VALID_AI_EXPOSURES,
    VALID_DOC_TYPES,
    VALID_REVIEW_STATUSES,
    AcceptanceCriterion,
    Diagnostic,
    ParseOptions,
    ParseResult,
    RealizationRef,
    Scenario,
    ScenarioStep,
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
    TicketLink,
)

# ─── Regex patterns ───────────────────────────────────────

NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")

STATUS_RE = re.compile(r"<!--\s*(?:specwright|canon):system:(\S+)\s+status:(\S+)\s*-->")
TICKET_RE = re.compile(r"<!--\s*(?:specwright|canon):ticket:(\w+):(\S+)\s*-->")
REALIZATION_RE = re.compile(
    r"<!--\s*(?:specwright|canon):realized-in:(?:PR#(\d+)|(audit))\s+file:([^\s]+?)(?::(\S+))?\s*-->"
)
CHECKBOX_RE = re.compile(r"^(\s*)-\s*\[([ xX])\]\s+(.+)$")
# Unanchored — used with search() on content lines.
# See also writer.py::_DELTA_COMMENT_RE (anchored) and _DELTA_COMMENT_STRIP_RE (permissive).
DELTA_RE = re.compile(r"<!--\s*(?:specwright|canon):delta:(added|modified|removed)\s*-->")
SCENARIO_HEADING_RE = re.compile(r"^####\s+Scenario:\s*(.+)$", re.IGNORECASE)
BDD_STEP_RE = re.compile(r"^-\s+(GIVEN|WHEN|THEN|AND|BUT)\s+(.+)$", re.IGNORECASE)
STRENGTH_RE = re.compile(r"\b(MUST NOT|MUST|SHOULD NOT|SHOULD|MAY)\b")

VALID_STATUSES = {"draft", "todo", "in_progress", "done", "deprecated"}
SKIP_HEADINGS = {"Acceptance Criteria"}


# ─── Public API ───────────────────────────────────────────


def parse_spec(raw: str, options: ParseOptions | None = None) -> ParseResult:
    """Parse a raw markdown spec file into a structured SpecDocument."""
    opts = options or ParseOptions()
    file_path = opts.file_path
    diagnostics: list[Diagnostic] = []

    # Step 1: Extract frontmatter
    fm, content, fm_diags = _parse_frontmatter(raw, file_path)
    diagnostics.extend(fm_diags)

    # Count frontmatter lines for offset
    fm_line_count = _count_frontmatter_lines(raw)

    # Step 2: Parse sections
    sections, sec_diags = _parse_sections(content, fm_line_count, file_path)
    diagnostics.extend(sec_diags)

    # Step 3: Optionally strip content
    if not opts.include_content:
        sections = _strip_content(sections)

    return ParseResult(
        document=SpecDocument(
            file_path=file_path or "",
            frontmatter=fm,
            sections=sections,
            raw=raw,
        ),
        diagnostics=diagnostics,
    )


def parse_frontmatter(
    raw: str, file_path: str | None = None
) -> tuple[SpecFrontmatter, str, list[Diagnostic]]:
    """Parse frontmatter — public wrapper for tests."""
    return _parse_frontmatter(raw, file_path)


def parse_status_comment(text: str) -> SectionStatus | None:
    """Parse a canon/specwright status comment string."""
    match = STATUS_RE.search(text)
    if not match:
        return None
    return _parse_status_string(match.group(2))


def parse_ticket_comment(text: str) -> TicketLink | None:
    """Parse a canon/specwright ticket comment string.

    Recognizes ``jira``, ``linear``, and ``github`` system names.
    Unrecognized systems (e.g. ``unknown``) return None but are logged
    as warnings to help diagnose stale or misconfigured ticket links.
    """
    match = TICKET_RE.search(text)
    if not match:
        return None
    system = match.group(1).lower()
    if system not in ("jira", "linear", "github"):
        import logging

        logging.getLogger(__name__).warning(
            "Unrecognized ticket system %r in comment: %s "
            "(expected jira, linear, or github — this link will be ignored, "
            "which may cause duplicate ticket creation)",
            system,
            text.strip(),
        )
        return None
    return TicketLink(system=system, ticket_id=match.group(2))  # type: ignore[arg-type]


def extract_comments_from_content(
    content: str, section_number: str | None
) -> tuple[SectionStatus, TicketLink | None]:
    """Extract status and ticket comments from a block of content.

    Returns (status, ticket_link). Use `extract_delta_comment` separately
    to retrieve delta annotations.
    """
    status = SectionStatus(state="draft")
    ticket_link: TicketLink | None = None

    for line in content.split("\n"):
        status_match = STATUS_RE.search(line)
        if status_match:
            comment_section_id = status_match.group(1)
            if section_number is None or comment_section_id == section_number:
                status = _parse_status_string(status_match.group(2))

        ticket_result = parse_ticket_comment(line)
        if ticket_result:
            ticket_link = ticket_result

    return status, ticket_link


def extract_delta_comment(content: str) -> str | None:
    """Extract a delta annotation from content.

    Returns "added", "modified", "removed", or None.
    """
    m = DELTA_RE.search(content)
    return m.group(1) if m else None


def parse_acceptance_criteria(content: str, start_line_offset: int) -> list[AcceptanceCriterion]:
    """Parse markdown checkboxes from content, attaching realization refs."""
    criteria: list[AcceptanceCriterion] = []
    lines = content.split("\n")
    for i, line in enumerate(lines):
        match = CHECKBOX_RE.match(line)
        if match:
            # Collect realization comments that follow this checkbox
            realized_in: list[RealizationRef] = []
            for j in range(i + 1, len(lines)):
                r_match = REALIZATION_RE.search(lines[j])
                if r_match:
                    pr_num = int(r_match.group(1)) if r_match.group(1) else None
                    realized_in.append(
                        RealizationRef(
                            pr_number=pr_num,
                            file_path=r_match.group(3),
                            lines=r_match.group(4) or "",
                        )
                    )
                elif (
                    lines[j].strip() == ""
                    or lines[j].strip().startswith("<!-- specwright:")
                    or lines[j].strip().startswith("<!-- canon:")
                ):
                    continue
                else:
                    break

            ac_text = match.group(3).strip()
            criteria.append(
                AcceptanceCriterion(
                    text=ac_text,
                    checked=match.group(2) != " ",
                    line=start_line_offset + i,
                    realized_in=realized_in,
                    strength=_extract_strength(ac_text),
                )
            )
    return criteria


def parse_scenarios(content: str, start_line_offset: int) -> list[Scenario]:
    """Parse BDD scenarios from section content.

    Looks for `#### Scenario: Name` headings (case-insensitive, h4 only)
    followed by BDD steps (`- GIVEN/WHEN/THEN/AND/BUT text`).

    Headings at other levels (###, #####) are intentionally ignored — only h4
    is recognized as a scenario heading. Scenarios with zero steps (heading
    followed only by blank lines or non-step content) are skipped.

    Step ordering is intentionally not validated — AND/BUT may appear without
    a preceding GIVEN/WHEN/THEN. This parser is documentation-first; strict
    Gherkin ordering is left to downstream consumers.
    """
    scenarios: list[Scenario] = []
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        heading_match = SCENARIO_HEADING_RE.match(lines[i].strip())
        if heading_match:
            name = heading_match.group(1).strip()
            scenario_start = start_line_offset + i
            steps: list[ScenarioStep] = []
            i += 1

            while i < len(lines):
                stripped = lines[i].strip()
                step_match = BDD_STEP_RE.match(stripped)
                if step_match:
                    keyword = step_match.group(1).upper()
                    text = step_match.group(2).strip()
                    strength = _extract_strength(text)
                    steps.append(
                        ScenarioStep(
                            keyword=cast(Literal["GIVEN", "WHEN", "THEN", "AND", "BUT"], keyword),
                            text=text,
                            strength=strength,
                            line=start_line_offset + i,
                        )
                    )
                    i += 1
                elif stripped == "":
                    i += 1
                else:
                    # Non-empty, non-step line → end of scenario
                    break

            scenario_end = start_line_offset + i - 1
            if steps:  # skip headings with no steps — likely a parse artifact
                scenarios.append(
                    Scenario(
                        name=name,
                        steps=steps,
                        start_line=scenario_start,
                        end_line=scenario_end,
                    )
                )
        else:
            i += 1

    return scenarios


_STRENGTH_MAP: dict[str, str] = {
    "MUST": "MUST",
    "MUST NOT": "MUST_NOT",
    "SHOULD": "SHOULD",
    "SHOULD NOT": "SHOULD_NOT",
    "MAY": "MAY",
}


def _extract_strength(text: str) -> str | None:
    """Detect the first RFC 2119 strength keyword in *text*.

    Only uppercase keywords are recognized per RFC 2119 — "must" and "should"
    in lowercase are intentionally ignored.

    Scans for MUST NOT, MUST, SHOULD NOT, SHOULD, MAY (in that priority order
    due to regex alternation). If multiple keywords appear, only the **first**
    match is returned — callers cannot detect a second keyword.

    Returns the keyword normalized to the enum value (spaces → underscores):
    "MUST NOT" → "MUST_NOT", "SHOULD NOT" → "SHOULD_NOT".
    """
    match = STRENGTH_RE.search(text)
    if not match:
        return None
    return _STRENGTH_MAP[match.group(1)]


# ─── Internal helpers ─────────────────────────────────────


def _parse_frontmatter(
    raw: str, file_path: str | None
) -> tuple[SpecFrontmatter, str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    post = frontmatter.loads(raw)
    data = post.metadata

    def get_str(key: str, fallback: str) -> str:
        val = data.get(key)
        return str(val) if val is not None else fallback

    def parse_tags(val: object) -> list[str]:
        if isinstance(val, list):
            return [str(v) for v in val]
        if isinstance(val, str):
            return [s.strip() for s in val.split(",") if s.strip()]
        return []

    # Parse depends_on (list of strings)
    raw_depends = data.get("depends_on")
    if isinstance(raw_depends, list):
        depends_on = [str(v) for v in raw_depends]
    elif isinstance(raw_depends, str):
        depends_on = [s.strip() for s in raw_depends.split(",") if s.strip()]
    else:
        depends_on = []

    # Parse type
    doc_type = get_str("type", "spec")
    if doc_type not in VALID_DOC_TYPES:
        diagnostics.append(
            Diagnostic(
                severity="warning",
                message=f'Unknown document type: "{doc_type}", defaulting to "spec"',
                file_path=file_path,
            )
        )
        doc_type = "spec"

    # Parse review_status
    raw_review = data.get("review_status")
    review_status: str | None = None
    if raw_review is not None:
        review_status = str(raw_review)
        if review_status not in VALID_REVIEW_STATUSES:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    message=f'Unknown review_status: "{review_status}"',
                    file_path=file_path,
                )
            )
            review_status = None

    # Parse sync field (per-spec sync control)
    raw_sync = data.get("sync")
    sync_value = "auto"
    if raw_sync is not None:
        sync_str = str(raw_sync).lower()
        if sync_str in ("true", "false", "auto"):
            sync_value = sync_str
        else:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    message=f'Unknown sync value: "{raw_sync}", expected true/false/auto',
                    file_path=file_path,
                )
            )

    # Parse ai_exposure (None = not specified, let resolve_ai_exposure decide)
    raw_ai_exposure = data.get("ai_exposure")
    ai_exposure = None
    if raw_ai_exposure is not None:
        ai_exposure_str = str(raw_ai_exposure)
        if ai_exposure_str not in VALID_AI_EXPOSURES:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    message=f'Unknown ai_exposure: "{ai_exposure_str}", ignoring',
                    file_path=file_path,
                )
            )
        else:
            ai_exposure = ai_exposure_str

    fm = SpecFrontmatter(
        title=get_str("title", "Untitled Spec"),
        status=get_str("status", "draft"),
        owner=get_str("owner", ""),
        team=get_str("team", ""),
        ticket_project=str(data["ticket_project"])
        if data.get("ticket_project") is not None
        else None,
        created=str(data["created"]) if data.get("created") is not None else None,
        updated=str(data["updated"]) if data.get("updated") is not None else None,
        tags=parse_tags(data.get("tags")),
        doc_type=doc_type,
        depends_on=depends_on,
        supersedes=(str(data["supersedes"]) or None)
        if data.get("supersedes") is not None
        else None,
        review_status=review_status,
        sync=sync_value,
        ai_exposure=ai_exposure,
    )

    if "title" not in data or not data["title"]:
        diagnostics.append(
            Diagnostic(
                severity="warning",
                message="Missing required frontmatter field: title",
                file_path=file_path,
            )
        )

    if fm.status and fm.status not in VALID_STATUSES:
        diagnostics.append(
            Diagnostic(
                severity="warning",
                message=f'Unknown document status: "{fm.status}"',
                file_path=file_path,
            )
        )

    return fm, post.content, diagnostics


def _count_frontmatter_lines(raw: str) -> int:
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i + 1
    return 0


def _parse_status_string(raw: str) -> SectionStatus:
    if raw == "draft":
        return SectionStatus(state="draft")
    if raw == "todo":
        return SectionStatus(state="todo")
    if raw == "in_progress":
        return SectionStatus(state="in_progress")
    if raw == "done":
        return SectionStatus(state="done")
    if raw == "deprecated":
        return SectionStatus(state="deprecated")
    if raw.startswith("blocked:"):
        return SectionStatus(state="blocked", blocked_by=raw[len("blocked:") :])
    return SectionStatus(state="draft")


def _parse_sections(
    markdown_content: str, frontmatter_line_count: int, file_path: str | None
) -> tuple[list[SpecSection], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []

    # Use mistune to find headings with line positions
    headings = _extract_headings(markdown_content, frontmatter_line_count)

    raw_lines = markdown_content.split("\n")
    total_lines = len(raw_lines)

    all_sections: list[SpecSection] = []

    for i, h in enumerate(headings):
        next_h = headings[i + 1] if i + 1 < len(headings) else None

        # Content spans from line after heading to line before next heading
        content_start = h["start_line"] - frontmatter_line_count + 1  # 1-based in markdown
        content_end = next_h["start_line"] - frontmatter_line_count - 1 if next_h else total_lines

        content_lines = raw_lines[content_start - 1 : content_end]
        content = "\n".join(content_lines).strip()

        end_line = next_h["start_line"] - 1 if next_h else frontmatter_line_count + total_lines

        status, ticket_link = extract_comments_from_content(content, h["section_number"])
        delta = extract_delta_comment(content)
        acceptance_criteria = parse_acceptance_criteria(content, h["start_line"] + 1)
        scenarios = parse_scenarios(content, h["start_line"] + 1)

        section_id = _make_id(h["section_number"], h["title"])

        all_sections.append(
            SpecSection(
                id=section_id,
                section_number=h["section_number"],
                title=h["title"],
                depth=h["depth"],
                content=content,
                ticket_link=ticket_link,
                status=status,
                acceptance_criteria=acceptance_criteria,
                scenarios=scenarios,
                delta=delta,
                children=[],
                start_line=h["start_line"],
                end_line=end_line,
            )
        )

    # Nest h3s under preceding h2s
    top_level: list[SpecSection] = []
    current_h2: SpecSection | None = None

    for section in all_sections:
        if section.depth == 2:
            current_h2 = section
            top_level.append(section)
        elif section.depth == 3:
            if current_h2:
                current_h2.children.append(section)
            else:
                diagnostics.append(
                    Diagnostic(
                        severity="warning",
                        message=f'h3 "{section.title}" has no parent h2, treated as top-level',
                        line=section.start_line,
                        file_path=file_path,
                    )
                )
                top_level.append(section)

    return top_level, diagnostics


def _extract_headings(
    markdown_content: str, frontmatter_line_count: int
) -> list[dict[str, object]]:
    """Extract h2 and h3 headings with line positions using regex on raw lines."""
    headings: list[dict[str, object]] = []
    lines = markdown_content.split("\n")

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Match ## or ### headings
        if stripped.startswith("## ") and not stripped.startswith("### "):
            depth = 2
            text = stripped[3:].strip()
        elif stripped.startswith("### "):
            depth = 3
            text = stripped[4:].strip()
        else:
            continue

        # Skip content-marker headings
        if text in SKIP_HEADINGS:
            continue

        line_num = (i + 1) + frontmatter_line_count
        match = NUMBERED_HEADING_RE.match(text)

        headings.append(
            {
                "depth": depth,
                "text": text,
                "section_number": match.group(1) if match else None,
                "title": match.group(2) if match else text,
                "start_line": line_num,
            }
        )

    return headings


def _make_id(section_number: str | None, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{section_number}-{slug}" if section_number else slug


def _strip_content(sections: list[SpecSection]) -> list[SpecSection]:
    return [
        section.model_copy(update={"content": "", "children": _strip_content(section.children)})
        for section in sections
    ]
