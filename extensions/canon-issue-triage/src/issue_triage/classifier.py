"""Issue classification using Claude."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .models import IssueCategory, IssueContext, SpecMatch, TriageResult

if TYPE_CHECKING:
    from canon.agent.client import ClaudeClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Canon's issue triage agent. Your job is to classify incoming GitHub \
issues and determine which existing spec documents they relate to.

You will receive:
1. The issue title and body
2. A list of existing spec summaries (title, status, section headings)

Classify the issue into exactly one category:
- feature-request: Describes new functionality or a capability not yet built
- bug-report: Describes incorrect behavior, errors, or regressions
- question: Asks how to do something or seeks clarification
- duplicate: Clearly restates an existing issue or spec section
- support: Requests help with setup, configuration, or integration

Score each spec's relevance to this issue from 0.0 to 1.0:
- 1.0 = The issue is directly about this spec or one of its sections
- 0.5 = The issue is tangentially related
- 0.0 = No relationship

Respond with ONLY valid JSON matching this schema:
{
  "classification": "feature-request|bug-report|question|duplicate|support",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<1-2 sentence explanation>",
  "related_specs": [
    {"path": "<spec file path>", "relevance": <float>, "section": "<section number or null>"}
  ],
  "suggested_labels": ["<label1>", "<label2>"],
  "duplicate_of": <issue number or null>
}

Only include specs with relevance > 0.3. Return at most 5 related specs, \
sorted by relevance descending.
"""

MAX_BODY_CHARS = 8000


def build_user_message(issue: IssueContext, spec_summaries: list[dict]) -> str:
    """Build the user message for the classification prompt."""
    body = issue.body[:MAX_BODY_CHARS] if issue.body else "(no body)"

    specs_text = ""
    if spec_summaries:
        specs_lines = []
        for s in spec_summaries:
            sections = ", ".join(s.get("sections", [])[:10])
            specs_lines.append(
                f'- {s["path"]}: "{s["title"]}" (status: {s["status"]}) [sections: {sections}]'
            )
        specs_text = "\n".join(specs_lines)
    else:
        specs_text = "(no specs found)"

    return f"""\
## Issue #{issue.number}

**Title:** {issue.title}
**Author:** {issue.author}
**Existing labels:** {", ".join(issue.labels) or "none"}

**Body:**
{body}

## Existing Specs

{specs_text}
"""


def parse_classification_response(text: str) -> TriageResult:
    """Parse Claude's JSON response into a TriageResult."""
    # Strip markdown code fences if present (only first/last lines)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove opening fence
        lines = lines[1:]
        # Remove closing fence if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    data = json.loads(cleaned)

    related_specs = []
    for spec_data in data.get("related_specs", []):
        related_specs.append(
            SpecMatch(
                path=spec_data["path"],
                relevance=float(spec_data["relevance"]),
                section=spec_data.get("section"),
            )
        )

    return TriageResult(
        classification=IssueCategory(data["classification"]),
        confidence=float(data["confidence"]),
        reasoning=data.get("reasoning", ""),
        related_specs=related_specs,
        suggested_labels=data.get("suggested_labels", []),
        duplicate_of=data.get("duplicate_of"),
    )


def classify_issue(
    client: ClaudeClient,
    issue: IssueContext,
    spec_summaries: list[dict],
    org: str = "",
) -> TriageResult:
    """Classify an issue using Claude.

    Args:
        client: The Canon Claude client instance.
        issue: Context about the issue to classify.
        spec_summaries: List of dicts with keys: path, title, status, sections.
        org: Organization ID for API key resolution.

    Returns:
        TriageResult with classification, confidence, and matched specs.
    """
    from canon.agent.client import AgentConfig

    user_message = build_user_message(issue, spec_summaries)
    config = AgentConfig(
        model="claude-sonnet-4-6",
        max_output_tokens=2000,
        temperature=0.0,
    )

    result = client.complete(SYSTEM_PROMPT, user_message, config, org=org)

    try:
        triage_result = parse_classification_response(result.text)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Failed to parse classification response: %s", e)
        logger.debug("Raw response: %s", result.text)
        # Return a low-confidence fallback
        return TriageResult(
            classification=IssueCategory.SUPPORT,
            confidence=0.0,
            reasoning=f"Classification failed: {e}",
        )

    # Filter related_specs to only include paths from the known spec set
    # (prevents LLM prompt injection from injecting arbitrary URLs)
    known_paths = {s["path"] for s in spec_summaries}
    triage_result.related_specs = [s for s in triage_result.related_specs if s.path in known_paths]

    return triage_result
