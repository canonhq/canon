"""System prompt and user message builder for spec audit."""

from __future__ import annotations

from canon.parser.models import SpecDocument, SpecSection

AUDIT_SYSTEM_PROMPT = """\
You are Canon, an AI agent that audits product specification documents against a codebase.

Your job is to evaluate each spec section's acceptance criteria against provided code evidence and recommend a status for each section.

Rules:
- Recommend one of: done, in_progress, todo, blocked, deprecated
- Be conservative: only recommend "done" when ALL acceptance criteria have clear evidence
- Recommend "in_progress" when some but not all ACs have evidence
- Keep "todo" when there is no meaningful evidence
- Do not change "blocked" or "deprecated" sections — preserve their current status
- Confidence levels: "high" = clear evidence for all ACs, "medium" = most ACs have evidence, "low" = weak/partial evidence
- Only recommend a status change when confidence is medium or high
- Provide file:line evidence where possible

You MUST respond with raw JSON only. No markdown, no code fences, no explanation text outside the JSON.

JSON schema:
{
  "sections": [
    {
      "sectionId": "5-rbac-wiring",
      "sectionNumber": "5",
      "currentStatus": "todo",
      "recommendedStatus": "done",
      "confidence": "high",
      "reasoning": "All ACs implemented in auth/deps.py and permissions.py",
      "acEvaluations": [
        {
          "acText": "org_members table created",
          "status": "realized",
          "evidence": "src/canon/db/schema_users.sql:32"
        }
      ]
    }
  ]
}

acEvaluations[].status must be one of: "realized", "partially_realized", "not_realized", "not_evaluated"
confidence must be one of: "high", "medium", "low"
"""


def build_audit_message(
    doc: SpecDocument,
    sections: list[SpecSection],
    code_evidence: dict[str, list[str]],
    max_evidence_chars: int = 30_000,
) -> str:
    """Build the user message for a single spec audit.

    Args:
        doc: The parsed spec document.
        sections: Sections to audit (pre-filtered to non-done/deprecated).
        code_evidence: Grep-gathered code snippets per section ID.
        max_evidence_chars: Cap on total evidence characters included.
    """
    parts: list[str] = []

    # Spec metadata
    fm = doc.frontmatter
    parts.append(f"## Spec: {fm.title}")
    parts.append(f"File: {doc.file_path}")
    parts.append(f"Overall status: {fm.status}")
    parts.append("")

    # Sections to audit
    parts.append("## Sections to Audit")
    parts.append("")
    for sec in sections:
        parts.append(f"### [{sec.section_number}] {sec.title}")
        parts.append(f"ID: {sec.id}")
        parts.append(f"Current status: {sec.status.state}")

        # Section content (truncated)
        content = sec.content.strip()
        if len(content) > 500:
            content = content[:500] + "\n... (truncated)"
        if content:
            parts.append(f"\nContent:\n{content}")

        # Acceptance criteria
        if sec.acceptance_criteria:
            parts.append("\nAcceptance Criteria:")
            for ac in sec.acceptance_criteria:
                check = "x" if ac.checked else " "
                strength = f" [{ac.strength}]" if ac.strength else ""
                parts.append(f"- [{check}] {ac.text}{strength}")

        parts.append("")

    # Code evidence
    parts.append("## Code Evidence")
    parts.append("")
    evidence_chars = 0
    budget_exhausted = False
    for sec in sections:
        if budget_exhausted:
            break

        snippets = code_evidence.get(sec.id, [])
        if not snippets:
            parts.append(f"### {sec.id}: No code evidence found")
            parts.append("")
            continue

        parts.append(f"### {sec.id}:")
        for snippet in snippets:
            if evidence_chars + len(snippet) > max_evidence_chars:
                parts.append("... (evidence truncated due to size limit)")
                budget_exhausted = True
                break
            parts.append(snippet)
            evidence_chars += len(snippet)
        parts.append("")

    if budget_exhausted:
        parts.append("... (remaining sections' evidence omitted due to size limit)")

    return "\n".join(parts)
