"""System prompts and user message builder for PR analysis."""

from __future__ import annotations

import math
from collections.abc import Callable

from pydantic import BaseModel

from canon.parser.models import SpecSection

# ─── Types ────────────────────────────────────────────────


class PRFile(BaseModel):
    filename: str
    status: str
    patch: str | None = None
    additions: int
    deletions: int


class RepoSpec(BaseModel):
    file_path: str
    document: object  # SpecDocument, kept loose to avoid circular imports


class ContextDoc(BaseModel):
    """A non-spec doc section from the search index or fallback loading."""

    path: str  # e.g. "docs/adrs/0005-auth.md"
    doc_title: str
    heading: str
    body: str
    score: float = 0.0  # relevance score (0 if from fallback)


class PRAnalysisContext(BaseModel):
    class PRInfo(BaseModel):
        number: int
        title: str
        body: str | None = None
        author: str
        base_branch: str
        head_branch: str
        url: str

    pr: PRInfo
    files: list[PRFile]
    specs: list[RepoSpec]
    context_docs: list[ContextDoc] = []

    model_config = {"arbitrary_types_allowed": True}


# ─── System Prompt ────────────────────────────────────────

BASE_SYSTEM_PROMPT = """You are Canon, an AI agent that analyzes pull requests against product specification documents.

Your job is to determine which spec sections a PR relates to, identify discrepancies between the spec and the PR changes, and suggest documentation updates.

Rules:
- Only include spec references that the PR **directly** implements, modifies, or contradicts. Never include tangential or speculative connections.
- Keep explanations to short fragments (5-10 words), not full sentences. Example: "Implements the auth flow" not "This PR implements the authentication flow that is described in this section of the specification."
- Severity levels: "conflict" = PR directly contradicts spec, "warning" = potential mismatch worth reviewing.
- Do NOT flag discrepancies for spec sections whose status is todo, draft, or blocked — incomplete sections are expected gaps, not mismatches.
- Only suggest doc updates when the PR clearly makes the spec **prose content** outdated or incorrect.
- Doc updates must target real prose text in the spec, never canon metadata (HTML comments like `<!-- canon:system:... -->` or `<!-- canon:ticket:... -->`).
- Never suggest a doc update where the current and suggested text are identical or nearly identical.
- You also receive **context documents** (ADRs, guides, READMEs) that may be relevant. Flag conflicts with these just as you would with specs.
- `specFile` in the JSON schema refers to any indexed doc file, not just specs.
- For non-spec context docs, only suggest doc updates when the PR clearly makes the content outdated.
- If no specs are genuinely relevant, say so in the summary and return empty arrays. Empty arrays are always preferred over weak matches."""

REALIZATION_PROMPT_SECTION = """

Additionally, for each acceptance criterion (AC) in the relevant spec sections, evaluate whether this PR realizes it:
- "realized": Code fully implements this AC. Provide file:line evidence.
- "partially_realized": Partial implementation — explain what's missing.
- "conflicting": Code contradicts the AC — explain how.
- "not_addressed": PR doesn't touch this area — do not include evidence.

Only evaluate ACs from sections the PR actually touches. Skip ACs from unrelated sections entirely."""

REALIZATION_JSON_SCHEMA = """
  "realizations": [
    {
      "specFile": "path/to/spec.md",
      "sectionId": "section-id",
      "sectionTitle": "Section Title",
      "acText": "The acceptance criterion text",
      "status": "realized" | "partially_realized" | "conflicting" | "not_addressed",
      "evidenceFiles": [{"path": "src/file.py", "startLine": 42, "endLine": 60}],
      "explanation": "Brief explanation"
    }
  ]"""

_JSON_SCHEMA = """

You MUST respond with raw JSON only. No markdown, no code fences, no explanation text outside the JSON.

JSON schema:
{
  "summary": "1-2 sentence summary of how this PR relates to existing specs",
  "specReferences": [
    {
      "specFile": "path/to/spec.md",
      "sectionId": "section-id",
      "sectionTitle": "Section Title",
      "relevance": "high" | "medium",
      "explanation": "Short fragment (5-10 words)"
    }
  ],
  "discrepancies": [
    {
      "specFile": "path/to/spec.md",
      "sectionId": "section-id",
      "sectionTitle": "Section Title",
      "specSays": "What the spec says",
      "prDoes": "What the PR does differently",
      "severity": "conflict" | "warning",
      "suggestedSpecUpdate": "How to update the spec"
    }
  ],
  "docUpdates": [
    {
      "specFile": "path/to/spec.md",
      "sectionId": "section-id",
      "currentText": "Current prose text in spec (not metadata comments)",
      "suggestedText": "Suggested replacement prose",
      "reason": "Why this update is needed"
    }
  ],"""

SYSTEM_PROMPT = (
    BASE_SYSTEM_PROMPT + REALIZATION_PROMPT_SECTION + _JSON_SCHEMA + REALIZATION_JSON_SCHEMA + "\n}"
)


# ─── Public Functions ─────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return math.ceil(len(text) / 4)


def build_user_message(
    context: PRAnalysisContext,
    max_diff_chars: int = 24000,
    ai_exposure_default: str = "full",
    ai_exposure_restricted_tags: list[str] | None = None,
) -> str:
    """Build the user message for the PR analysis prompt."""
    parts: list[str] = []

    # PR metadata
    parts.append("## Pull Request")
    parts.append(f"#{context.pr.number}: {context.pr.title}")
    parts.append(f"Author: {context.pr.author}")
    parts.append(f"Branch: {context.pr.head_branch} → {context.pr.base_branch}")
    if context.pr.body:
        body = context.pr.body[:500]
        parts.append(f"\nDescription:\n{body}")

    # Spec summaries (respecting ai_exposure)
    if context.specs:
        spec_parts: list[str] = []
        for spec in context.specs:
            summary = _summarize_spec(spec, ai_exposure_default, ai_exposure_restricted_tags)
            if summary is not None:
                spec_parts.append(summary)
        if spec_parts:
            parts.append("\n## Spec Documents")
            parts.extend(spec_parts)
        else:
            parts.append("\n## Spec Documents\nNo spec documents available for AI analysis.")
    else:
        parts.append("\n## Spec Documents\nNo spec documents found in this repository.")

    # Related context documents (ADRs, guides, READMEs)
    if context.context_docs:
        parts.append("\n## Related Documents")
        for doc in context.context_docs:
            parts.append(f"### {doc.path}")
            parts.append(f"Title: {doc.doc_title} | Section: {doc.heading}")
            parts.append(doc.body)

    # File list (always included)
    parts.append("\n## Changed Files")
    for f in context.files:
        parts.append(f"- {f.filename} ({f.status}, +{f.additions} -{f.deletions})")

    # Diffs: largest-first until budget hit
    files_with_patches = sorted(
        [f for f in context.files if f.patch],
        key=lambda f: len(f.patch or ""),
        reverse=True,
    )

    diff_chars_used = 0
    included_diffs: list[str] = []

    for f in files_with_patches:
        patch = f.patch or ""
        if diff_chars_used + len(patch) > max_diff_chars:
            continue
        included_diffs.append(f"### {f.filename}\n```diff\n{patch}\n```")
        diff_chars_used += len(patch)

    if included_diffs:
        parts.append("\n## Diffs")
        parts.extend(included_diffs)

    if len(included_diffs) < len(files_with_patches):
        skipped = len(files_with_patches) - len(included_diffs)
        parts.append(f"\n_{skipped} file diff(s) omitted due to size limits._")

    return "\n".join(parts)


# ─── Internal Helpers ─────────────────────────────────────


def _summarize_spec(
    spec: RepoSpec,
    config_default: str = "full",
    restricted_tags: list[str] | None = None,
) -> str | None:
    """Summarize a spec for the PR analysis prompt.

    Returns None if the spec's ai_exposure is 'none'.
    """
    from canon.parser.models import SpecDocument, resolve_ai_exposure

    doc: SpecDocument = spec.document  # type: ignore[assignment]
    fm = doc.frontmatter
    exposure = resolve_ai_exposure(fm, restricted_tags, config_default)

    if exposure == "none":
        return None

    lines: list[str] = [
        f"### {spec.file_path}",
        f"Title: {fm.title} | Status: {fm.status} | Owner: {fm.owner} | Team: {fm.team}",
    ]

    if exposure == "metadata":
        # Only include section titles and AC counts, no content or AC text
        _walk_sections(doc.sections, lines, _format_section_metadata, 0)
    else:
        _walk_sections(doc.sections, lines, _format_section_summary, 0)

    return "\n".join(lines)


def _walk_sections(
    sections: list[SpecSection],
    lines: list[str],
    formatter: Callable[[SpecSection, int], str],
    depth: int,
) -> None:
    """Recursively walk sections at all depths, appending formatted lines."""
    for section in sections:
        lines.append(formatter(section, depth))
        if section.children:
            _walk_sections(section.children, lines, formatter, depth + 1)


def _format_section_metadata(section: SpecSection, indent: int) -> str:
    """Format a section as metadata only (title, status, AC count) — no content or AC text."""
    prefix = "  " * indent
    status = section.status.state
    ac_total = len(section.acceptance_criteria)
    ac_checked = sum(1 for ac in section.acceptance_criteria if ac.checked)
    ac_info = f" ({ac_checked}/{ac_total} ACs)" if ac_total else ""
    return f"{prefix}- [{section.id}] {section.title} ({status}){ac_info}"


def _format_section_summary(section: SpecSection, indent: int) -> str:
    prefix = "  " * indent
    status = section.status.state
    ticket = (
        f" [{section.ticket_link.system}:{section.ticket_link.ticket_id}]"
        if section.ticket_link
        else ""
    )
    delta = f" [delta: {section.delta}]" if section.delta else ""
    snippet = section.content[:120].replace("\n", " ").strip()
    lines = [f"{prefix}- [{section.id}] {section.title} ({status}){ticket}{delta}: {snippet}"]

    # Include acceptance criteria so Claude can evaluate realization
    for ac in section.acceptance_criteria:
        check = "x" if ac.checked else " "
        strength = f" [{ac.strength}]" if ac.strength else ""
        lines.append(f"{prefix}  - [{check}] {ac.text}{strength}")

    # Include BDD scenarios (Gherkin-style: no list markers, KEYWORD prefix instead)
    for scenario in section.scenarios:
        lines.append(f"{prefix}  Scenario: {scenario.name}")
        for step in scenario.steps:
            strength = f" [{step.strength}]" if step.strength else ""
            lines.append(f"{prefix}    {step.keyword} {step.text}{strength}")

    return "\n".join(lines)
