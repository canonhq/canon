"""PR analysis and comment formatting."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from enum import StrEnum
from urllib.parse import quote

from pydantic import BaseModel

from .client import DEFAULT_AGENT_CONFIG, AgentAPIError, AgentConfig, ClaudeClient
from .prompts import (
    SYSTEM_PROMPT,
    PRAnalysisContext,
    build_user_message,
)

logger = logging.getLogger(__name__)

# ─── Types ────────────────────────────────────────────────


class SpecReference(BaseModel):
    spec_file: str
    section_id: str
    section_title: str
    relevance: str  # "high" | "medium"
    explanation: str


class SpecDiscrepancy(BaseModel):
    spec_file: str
    section_id: str
    section_title: str
    spec_says: str
    pr_does: str
    severity: str  # "conflict" | "warning"
    suggested_spec_update: str


class DocUpdateSuggestion(BaseModel):
    spec_file: str
    section_id: str
    current_text: str
    suggested_text: str
    reason: str


class RealizationStatus(StrEnum):
    REALIZED = "realized"
    PARTIALLY_REALIZED = "partially_realized"
    CONFLICTING = "conflicting"
    NOT_ADDRESSED = "not_addressed"


class ACRealization(BaseModel):
    spec_file: str
    section_id: str
    section_title: str
    ac_text: str
    status: RealizationStatus
    evidence_files: list[dict] = []  # [{path, start_line, end_line}]
    explanation: str = ""


class TokenUsage(BaseModel):
    input: int
    output: int


class PRAnalysisResult(BaseModel):
    summary: str
    spec_references: list[SpecReference]
    discrepancies: list[SpecDiscrepancy]
    doc_updates: list[DocUpdateSuggestion]
    realizations: list[ACRealization] = []
    tokens_used: TokenUsage


# ─── Lazy client ──────────────────────────────────────────

_client: ClaudeClient | None = None


def _get_client() -> ClaudeClient:
    global _client
    if _client is None:
        _client = ClaudeClient()
    return _client


# ─── Public API ───────────────────────────────────────────


def analyze_pr(
    context: PRAnalysisContext,
    config: AgentConfig = DEFAULT_AGENT_CONFIG,
    client: ClaudeClient | None = None,
) -> PRAnalysisResult | None:
    """Analyze a PR against repo specs using Claude. Returns None if unavailable."""
    c = client or _get_client()
    if not c.is_available:
        return None

    max_diff_chars = max((config.max_input_tokens - 2000) * 4, 4000)
    user_message = build_user_message(context, max_diff_chars)

    try:
        result = c.complete(SYSTEM_PROMPT, user_message, config)
    except AgentAPIError as e:
        if e.status_code in (401, 403):
            logger.warning("BYOK key rejected (HTTP %s) during PR analysis", e.status_code)
            return None
        raise

    parsed = parse_analysis_response(result.text)

    return PRAnalysisResult(
        **parsed,
        tokens_used=TokenUsage(input=result.input_tokens, output=result.output_tokens),
    )


def parse_analysis_response(
    text: str,
) -> dict:
    """Parse JSON response from Claude, stripping code fences if present."""
    fallback = {
        "summary": "Unable to parse analysis response.",
        "spec_references": [],
        "discrepancies": [],
        "doc_updates": [],
    }

    cleaned = text.strip()
    fence_match = re.match(r"^```(?:json)?\s*\n?([\s\S]*?)\n?\s*```$", cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        parsed = json.loads(cleaned)

        realizations: list[ACRealization] = []
        if isinstance(parsed.get("realizations"), list):
            for r in parsed["realizations"]:
                try:
                    status_val = r.get("status", "not_addressed")
                    realizations.append(
                        ACRealization(
                            spec_file=r.get("specFile", ""),
                            section_id=r.get("sectionId", ""),
                            section_title=r.get("sectionTitle", ""),
                            ac_text=r.get("acText", ""),
                            status=RealizationStatus(status_val),
                            evidence_files=r.get("evidenceFiles", []),
                            explanation=r.get("explanation", ""),
                        )
                    )
                except (ValueError, KeyError):
                    continue

        return {
            "summary": parsed.get("summary", fallback["summary"])
            if isinstance(parsed.get("summary"), str)
            else fallback["summary"],
            "spec_references": [
                SpecReference(
                    spec_file=r.get("specFile", ""),
                    section_id=r.get("sectionId", ""),
                    section_title=r.get("sectionTitle", ""),
                    relevance=r.get("relevance", "medium"),
                    explanation=r.get("explanation", ""),
                )
                for r in parsed.get("specReferences", [])
            ]
            if isinstance(parsed.get("specReferences"), list)
            else [],
            "discrepancies": [
                SpecDiscrepancy(
                    spec_file=d.get("specFile", ""),
                    section_id=d.get("sectionId", ""),
                    section_title=d.get("sectionTitle", ""),
                    spec_says=d.get("specSays", ""),
                    pr_does=d.get("prDoes", ""),
                    severity=d.get("severity", "warning"),
                    suggested_spec_update=d.get("suggestedSpecUpdate", ""),
                )
                for d in parsed.get("discrepancies", [])
            ]
            if isinstance(parsed.get("discrepancies"), list)
            else [],
            "doc_updates": [
                DocUpdateSuggestion(
                    spec_file=u.get("specFile", ""),
                    section_id=u.get("sectionId", ""),
                    current_text=u.get("currentText", ""),
                    suggested_text=u.get("suggestedText", ""),
                    reason=u.get("reason", ""),
                )
                for u in parsed.get("docUpdates", [])
            ]
            if isinstance(parsed.get("docUpdates"), list)
            else [],
            "realizations": realizations,
        }
    except (json.JSONDecodeError, KeyError):
        if cleaned and len(cleaned) < 500:
            return {**fallback, "summary": f"Analysis response (unparsed): {cleaned}"}
        return fallback


def _format_tokens(n: int) -> str:
    """Format token count as human-readable (e.g. 10.2k)."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _spec_link(
    base_url: str,
    owner: str,
    repo: str,
    spec_file: str,
    text: str,
    section_id: str | None = None,
) -> str:
    """Return a markdown link to the Canon web editor, or plain text if base_url is empty."""
    if not base_url or not owner or not repo:
        return text
    url = f"{base_url.rstrip('/')}/{owner}/{repo}/edit/{quote(spec_file, safe='/')}"
    if section_id:
        url += f"#{quote(section_id, safe='')}"
    return f"[{text}]({url})"


def format_analysis_comment(
    result: PRAnalysisResult,
    model: str = "",
    preview_url: str | None = None,
    base_url: str = "",
    owner: str = "",
    repo: str = "",
    doc_patterns: list[str] | None = None,
) -> str:
    """Format an analysis result as a GitHub markdown comment."""
    lines: list[str] = []

    lines.append("<!-- canon-bot -->")
    lines.append("## Canon")
    lines.append("")
    # Summary as blockquote
    for summary_line in result.summary.split("\n"):
        lines.append(f"> {summary_line}")

    if result.spec_references:
        if doc_patterns is not None:
            from ..github.spec_utils import matches_doc_patterns

            has_non_spec = any(
                not matches_doc_patterns(ref.spec_file, doc_patterns)
                for ref in result.spec_references
            )
        else:
            has_non_spec = any(
                not ref.spec_file.startswith("docs/specs/") for ref in result.spec_references
            )
        heading = "### Relevant Documents" if has_non_spec else "### Relevant Specs"
        lines.append("")
        lines.append(heading)

        # Group references by spec file
        groups: dict[str, list[SpecReference]] = {}
        for ref in result.spec_references:
            groups.setdefault(ref.spec_file, []).append(ref)

        for spec_file, refs in groups.items():
            spec_name = spec_file.rsplit("/", 1)[-1].removesuffix(".md")
            linked_name = _spec_link(base_url, owner, repo, spec_file, spec_name)
            lines.append("")
            if base_url and owner and repo:
                lines.append(f"**{linked_name}**")
            else:
                lines.append(f"**{linked_name}** · {spec_file}")
            lines.append("")
            lines.append("| Section | |")
            lines.append("|---------|---|")
            for ref in refs:
                title = ref.section_title.replace("|", "\\|")
                explanation = ref.explanation.replace("|", "\\|")
                lines.append(f"| {title} | {explanation} |")

    # Filter out "info" severity as safety net (prompt shouldn't produce them)
    actionable = [d for d in result.discrepancies if d.severity != "info"]
    if actionable:
        lines.append("")
        lines.append("### Discrepancies")
        for d in actionable:
            admonition = "CAUTION" if d.severity == "conflict" else "WARNING"
            linked_ref = _spec_link(
                base_url,
                owner,
                repo,
                d.spec_file,
                f"{d.spec_file} \u00a7 {d.section_id}",
                d.section_id,
            )
            lines.append("")
            lines.append(f"> [!{admonition}]")
            lines.append(f"> **{d.section_title}** \u00b7 {linked_ref}")
            lines.append(">")
            lines.append(f"> Spec says: {d.spec_says}")
            lines.append(f"> PR does: {d.pr_does}")

    # Filter out no-op doc updates (identical text)
    meaningful_updates = [
        u for u in result.doc_updates if u.current_text.strip() != u.suggested_text.strip()
    ]

    if meaningful_updates:
        lines.append("")
        lines.append("### Suggested Updates")
        for u in meaningful_updates:
            spec_name = u.spec_file.rsplit("/", 1)[-1].removesuffix(".md")
            linked_ref = _spec_link(
                base_url,
                owner,
                repo,
                u.spec_file,
                f"{u.spec_file} \u00a7 {u.section_id}",
                u.section_id,
            )
            lines.append("")
            lines.append(f"**{spec_name}** \u00b7 {linked_ref}")
            lines.append("")
            lines.append("```diff")
            for line in u.current_text.split("\n"):
                lines.append(f"- {line}")
            for line in u.suggested_text.split("\n"):
                lines.append(f"+ {line}")
            lines.append("```")

    # Realization status table
    if result.realizations:
        lines.append("")
        lines.append("### Realization Status")

        # Group realizations by spec_file + section_title
        real_groups: dict[str, list[ACRealization]] = {}
        for r in result.realizations:
            key = f"{r.spec_file}|{r.section_id}|{r.section_title}"
            real_groups.setdefault(key, []).append(r)

        for key, reals in real_groups.items():
            parts = key.split("|", 2)
            spec_file = parts[0]
            section_id = parts[1] if len(parts) > 1 else ""
            spec_name = spec_file.rsplit("/", 1)[-1].removesuffix(".md")
            section_title = parts[2] if len(parts) > 2 else ""
            linked_name = _spec_link(
                base_url,
                owner,
                repo,
                spec_file,
                spec_name,
                section_id or None,
            )
            lines.append("")
            lines.append(f"**{linked_name}** \u00a7 {section_title}")
            lines.append("")
            lines.append("| AC | Status | Evidence |")
            lines.append("|----|--------|----------|")

            for r in reals:
                status_icon = {
                    RealizationStatus.REALIZED: ":white_check_mark: Realized",
                    RealizationStatus.PARTIALLY_REALIZED: ":large_orange_diamond: Partial",
                    RealizationStatus.CONFLICTING: ":warning: Conflicting",
                    RealizationStatus.NOT_ADDRESSED: ":white_large_square: Not addressed",
                }.get(r.status, r.status.value)

                evidence = ""
                if r.evidence_files:
                    evidence_parts = []
                    for ef in r.evidence_files:
                        path = ef.get("path", "")
                        start = ef.get("start_line") or ef.get("startLine", "")
                        end = ef.get("end_line") or ef.get("endLine", "")
                        if start and end:
                            evidence_parts.append(f"`{path}:{start}-{end}`")
                        elif start:
                            evidence_parts.append(f"`{path}:{start}`")
                        elif path:
                            evidence_parts.append(f"`{path}`")
                    evidence = ", ".join(evidence_parts)
                elif r.explanation:
                    evidence = r.explanation

                ac_text = r.ac_text.replace("|", "\\|")
                lines.append(f"| {ac_text} | {status_icon} | {evidence} |")

    # Footer
    cost = estimate_cost(result.tokens_used.input, result.tokens_used.output, model)
    tokens_in = _format_tokens(result.tokens_used.input)
    tokens_out = _format_tokens(result.tokens_used.output)

    # Extract model family name for display
    model_display = model.split("-")[0] if model else "claude"
    for family in ("opus", "sonnet", "haiku"):
        if family in model.lower():
            model_display = family
            break

    footer_parts = [f"{model_display}", f"{tokens_in} in, {tokens_out} out", f"${cost}"]
    if preview_url:
        footer_parts.append(f"[preview]({preview_url})")
    if base_url and owner and repo:
        specs_url = f"{base_url.rstrip('/')}/{owner}/{repo}"
        footer_parts.append(f"[View in Canon]({specs_url})")
    footer_parts.extend(["dismiss", "reanalyze"])

    lines.append("")
    lines.append("---")
    lines.append(f"<sub>canon \u00b7 {' \u00b7 '.join(footer_parts)}</sub>")

    embedded_json = json.dumps(
        {
            "docUpdates": [u.model_dump() for u in result.doc_updates],
            "discrepancies": [d.model_dump() for d in result.discrepancies],
            "realizations": [r.model_dump() for r in result.realizations],
        }
    )
    # Base64-encode to avoid breaking HTML comments — raw JSON can contain
    # "--" sequences (em dashes, etc.) which prematurely close the comment.
    encoded = base64.b64encode(embedded_json.encode()).decode()
    lines.append("")
    lines.append(f"<!-- canon-analysis-b64: {encoded} -->")

    return "\n".join(lines)


def extract_analysis_data(
    comment_body: str,
) -> dict | None:
    """Extract embedded analysis data from a bot comment.

    Supports both base64-encoded (current) and raw JSON (legacy) formats.
    """
    # Try base64-encoded format first (current)
    b64_match = re.search(r"<!-- (?:specwright|canon)-analysis-b64: (.+?) -->", comment_body)
    if b64_match:
        try:
            decoded = base64.b64decode(b64_match.group(1)).decode()
            parsed = json.loads(decoded)
            return {
                "doc_updates": parsed.get("docUpdates", []),
                "discrepancies": parsed.get("discrepancies", []),
                "realizations": parsed.get("realizations", []),
            }
        except (json.JSONDecodeError, KeyError, ValueError, binascii.Error):
            return None

    # Fall back to legacy raw JSON format
    match = re.search(r"<!-- (?:specwright|canon)-analysis: (.+?) -->", comment_body)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(1))
        return {
            "doc_updates": parsed.get("docUpdates", []),
            "discrepancies": parsed.get("discrepancies", []),
            "realizations": parsed.get("realizations", []),
        }
    except (json.JSONDecodeError, KeyError):
        return None


def estimate_cost(input_tokens: int, output_tokens: int, model: str = "") -> str:
    """Estimate cost in USD based on model pricing."""
    # Per-million-token pricing
    pricing = {
        "opus": (15.0, 75.0),
        "sonnet": (3.0, 15.0),
        "haiku": (0.8, 4.0),
    }
    # Match model family from model ID string
    rates = pricing["haiku"]  # fallback
    for family, p in pricing.items():
        if family in model.lower():
            rates = p
            break
    cost = (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
    return f"{cost:.4f}"
