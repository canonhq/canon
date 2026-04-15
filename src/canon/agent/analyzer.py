"""PR analysis and comment formatting."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from enum import StrEnum
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from canon import analytics

from .client import DEFAULT_AGENT_CONFIG, AgentAPIError, AgentConfig, ClaudeClient
from .prompts import (
    SYSTEM_PROMPT,
    PRAnalysisContext,
    build_user_message,
)

logger = logging.getLogger(__name__)

# Stable fallback message used when the model response can't be parsed.
# Kept as a module constant so tests and downstream code can match on it
# deterministically instead of substring-checking prose.
PARSE_FALLBACK_SUMMARY = "Unable to parse analysis response."

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
    from .prompts import estimate_tokens

    c = client or _get_client()
    if not c.is_available:
        return None

    # Budget: total prompt (system + user) must fit within the model's context
    # window minus output tokens. We compute the diff and spec budgets
    # dynamically to avoid exceeding the API's token limit.
    system_tokens = estimate_tokens(SYSTEM_PROMPT)
    token_budget = config.max_context_tokens - config.max_output_tokens - system_tokens

    # First pass: build message with zero diff budget to measure spec/metadata size
    skeleton = build_user_message(context, max_diff_chars=0)
    skeleton_tokens = estimate_tokens(skeleton)

    # If specs alone blow the budget, rebuild with a spec char limit that
    # reserves at least 25% of the budget for diffs.
    max_spec_chars = 0  # 0 = unlimited
    min_diff_tokens = max(token_budget // 4, 4000)
    if skeleton_tokens > token_budget - min_diff_tokens:
        max_spec_chars = max((token_budget - min_diff_tokens) * 4, 8000)
        skeleton = build_user_message(context, max_diff_chars=0, max_spec_chars=max_spec_chars)
        skeleton_tokens = estimate_tokens(skeleton)
        logger.info(
            "Specs too large, capped at %d chars (%d est. tokens after cap)",
            max_spec_chars,
            skeleton_tokens,
        )

    # Allocate remaining budget to diffs (chars ≈ tokens * 4)
    diff_token_budget = max(token_budget - skeleton_tokens, 1000)
    max_diff_chars = max(diff_token_budget * 4, 4000)

    # Cap at the legacy limit so we don't balloon on small PRs
    legacy_limit = max((config.max_input_tokens - 2000) * 4, 4000)
    max_diff_chars = min(max_diff_chars, legacy_limit)

    user_message = build_user_message(context, max_diff_chars, max_spec_chars=max_spec_chars)

    # Safety check: if total still exceeds context, truncate the message
    total_tokens = system_tokens + estimate_tokens(user_message)
    if total_tokens > config.max_context_tokens - config.max_output_tokens:
        max_user_chars = (config.max_context_tokens - config.max_output_tokens - system_tokens) * 4
        if max_user_chars > 0:
            user_message = user_message[:max_user_chars]
            logger.warning(
                "Prompt too large (%d est. tokens), truncated user message to %d chars",
                total_tokens,
                max_user_chars,
            )

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


# ─── JSON extraction helpers ──────────────────────────────
#
# Claude's response format drifts with context length, model version, and
# prompt caching. The system prompt asks for raw JSON only, but long-context
# runs (~100k input tokens on this project) commonly produce preambles,
# postambles, or code fences regardless. Rather than pin a single brittle
# regex, we try a ladder of strategies and fall through until one yields
# valid JSON.
#
# Observed real-world shapes that broke the old anchored-fence regex:
#   1. "Here's my analysis:\n\n```json\n{...}\n```"
#   2. "```json\n{...}\n```\n\nLet me know if you need anything adjusted."
#   3. "<answer>\n{...}\n</answer>"
#   4. "{...}\n\n(The above JSON summarizes the PR changes.)"
#
# `parse_analysis_response` tries strategies in order and reports which one
# worked (or why all failed) via PostHog `pr_analysis_parse_*` events.


def _strip_answer_tags(text: str) -> str | None:
    """Extract content inside ``<answer>...</answer>`` if present."""
    m = re.search(r"<answer>\s*([\s\S]*?)\s*</answer>", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _strip_fence_relaxed(text: str) -> str | None:
    """Find a fenced code block anywhere in the text, not just as the root.

    Prefers explicitly-tagged ```json blocks, falls back to any ``` block.
    This is the relaxed cousin of the old anchored regex — it tolerates
    prose before and after the fence.
    """
    m = re.search(r"```json\s*\n?([\s\S]*?)\n?\s*```", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*\n?([\s\S]*?)\n?\s*```", text)
    if m:
        return m.group(1).strip()
    return None


def _slice_first_to_last_brace(text: str) -> str | None:
    """Return the substring from the first ``{`` to the last ``}``.

    Cheap and effective for responses that are JSON wrapped in prose, since
    ``json.loads`` will reject the slice if braces don't line up. Never
    matches anything useful if braces are absent, so callers should treat
    ``None`` as "try the next strategy".
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _build_result_dict(parsed: dict, fallback: dict) -> dict:
    """Map a parsed JSON dict onto the result schema used by ``analyze_pr``.

    Kept separate from ``parse_analysis_response`` so schema-mapping errors
    (``pydantic.ValidationError``) can be caught distinctly from JSON decode
    errors — they have different operational meanings (malformed JSON vs.
    JSON that doesn't match the expected schema).
    """
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
            except (ValueError, ValidationError, KeyError):
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


def _report_parse_failure(
    raw_text: str,
    error: Exception | None,
    *,
    stage: str,
) -> None:
    """Emit a WARN log and a PostHog analytics event for a parse failure.

    This is the *only* path that reports analyzer parse failures to the
    outside world. Historically the parser swallowed JSONDecodeError silently
    and returned a generic fallback, which left operators with an 85% bot
    failure rate and no diagnostic signal. Every fallback now produces:

      1. A ``WARN``-level log with the error type and first 300 chars of
         the response (visible under any reasonable OTel min_level).
      2. A ``pr_analysis_parse_failed`` PostHog event carrying the full
         error message plus a 2000-char response preview, for structured
         analysis in the dashboard.

    ``stage`` distinguishes the failure class:
      * ``"json_decode"`` — none of the extraction strategies produced
        valid JSON.
      * ``"schema_validation"`` — JSON parsed but pydantic rejected the
        shape when building result models.
    """
    err_type = type(error).__name__ if error is not None else "unknown"
    err_msg = str(error) if error is not None else ""
    # Keep the log line compact — operators just need enough to recognize
    # the failure class. The full payload goes to the PostHog event.
    logger.warning(
        "analyze_pr: failed to parse Claude response at stage=%s (len=%d, error=%s: %s): %s",
        stage,
        len(raw_text),
        err_type,
        err_msg[:200],
        raw_text[:300].replace("\n", " ⏎ "),
    )

    try:
        analytics.track(
            "pr_analysis_parse_failed",
            properties={
                "stage": stage,
                "error_type": err_type,
                "error_message": err_msg[:500],
                "response_length": len(raw_text),
                # Keep the preview bounded so a runaway response doesn't
                # produce an oversized PostHog event. 2000 chars is plenty
                # to see the shape (preamble, fences, tags) and diagnose.
                "response_preview": raw_text[:2000],
            },
        )
    except Exception:
        # Analytics must never break the main flow. Failure to report is
        # itself a warn-level condition but should not propagate.
        logger.debug("Failed to emit pr_analysis_parse_failed event", exc_info=True)


def parse_analysis_response(
    text: str,
) -> dict:
    """Parse JSON response from Claude, tolerant of preamble/postamble.

    Tries a ladder of extraction strategies — direct parse, ``<answer>`` tag
    stripping, relaxed code-fence stripping, first-brace-to-last-brace slice
    — and returns the result of the first strategy that yields valid JSON
    matching the expected schema.

    On complete failure (no strategy yields parseable JSON, or the parsed
    JSON fails schema validation), logs at WARN and emits a
    ``pr_analysis_parse_failed`` PostHog event with the raw response, then
    returns a stable fallback dict. The fallback NEVER embeds the raw
    response in the summary — that would post the model's output verbatim
    as a bot comment on the user's PR, which is a publishing footgun.
    """
    fallback = {
        "summary": PARSE_FALLBACK_SUMMARY,
        "spec_references": [],
        "discrepancies": [],
        "doc_updates": [],
        "realizations": [],
    }

    if not text or not text.strip():
        # Empty responses shouldn't page anyone. Return the fallback without
        # reporting — the bot will post the generic "unable to parse" and
        # the caller can retry.
        return fallback

    cleaned_text = text.strip()

    # Each entry is (strategy_name, extracted_candidate_or_None). ``None``
    # means "this strategy didn't find a candidate" — skip it silently.
    # Order matters: direct parse first (most common for well-behaved
    # responses), then most-specific-to-least-specific heuristics.
    strategies: list[tuple[str, str | None]] = [
        ("direct", cleaned_text),
        ("answer_tags", _strip_answer_tags(cleaned_text)),
        ("fence_relaxed", _strip_fence_relaxed(cleaned_text)),
        ("brace_slice", _slice_first_to_last_brace(cleaned_text)),
    ]

    parsed: dict | None = None
    strategy_used: str | None = None
    last_error: Exception | None = None

    for name, candidate in strategies:
        if candidate is None:
            continue
        try:
            parsed = json.loads(candidate)
            if not isinstance(parsed, dict):
                # Valid JSON but not an object (e.g. a list or string).
                # Treat as decode failure so we try the next strategy.
                last_error = TypeError(f"expected JSON object, got {type(parsed).__name__}")
                parsed = None
                continue
            strategy_used = name
            break
        except json.JSONDecodeError as e:
            last_error = e
            continue

    if parsed is None:
        _report_parse_failure(text, last_error, stage="json_decode")
        return fallback

    try:
        result = _build_result_dict(parsed, fallback)
    except ValidationError as e:
        _report_parse_failure(text, e, stage="schema_validation")
        return fallback

    # Log non-direct successes at INFO so we can measure how often the
    # model is wrapping its output and tune the prompt if needed. Direct
    # successes are the happy path — no need to log them.
    if strategy_used != "direct":
        logger.info(
            "analyze_pr: recovered JSON via strategy=%s (response_length=%d)",
            strategy_used,
            len(text),
        )
        try:
            analytics.track(
                "pr_analysis_parse_recovered",
                properties={
                    "strategy": strategy_used,
                    "response_length": len(text),
                },
            )
        except Exception:
            logger.debug("Failed to emit pr_analysis_parse_recovered event", exc_info=True)

    return result


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
