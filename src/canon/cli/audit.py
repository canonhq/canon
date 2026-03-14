"""canon audit — Claude-powered spec status audit."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from canon.agent.client import ClaudeClient
from canon.parser.models import SpecDocument, SpecSection

from ._local import (
    _flatten_sections,
    load_local_config,
    parse_all_local_specs,
)

VALID_STATES = {"done", "in_progress", "todo", "blocked", "deprecated"}


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "audit", help="Audit spec statuses against codebase (Claude-powered)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--sync", action="store_true", help="Run ticket sync after audit")
    parser.add_argument("--spec", help="Filter to a single spec file")
    parser.add_argument(
        "--no-ac-updates", action="store_true", help="Skip checking off ACs and inserting evidence"
    )


# ─── Data Classes ─────────────────────────────────────────


@dataclass
class ACEvaluation:
    ac_text: str
    status: str  # realized, partially_realized, not_realized, not_evaluated
    evidence: str = ""


@dataclass
class AuditRecommendation:
    section_id: str
    section_number: str
    current_status: str
    recommended_status: str
    confidence: str  # high, medium, low
    reasoning: str = ""
    ac_evaluations: list[ACEvaluation] = field(default_factory=list)


# ─── Main Entry Point ────────────────────────────────────


def run_audit(
    *,
    dry_run: bool = False,
    do_sync: bool = False,
    spec: str | None = None,
    root: Path | None = None,
    no_ac_updates: bool = False,
) -> None:
    root = root or Path.cwd()
    config = load_local_config(root)
    docs = parse_all_local_specs(root, config)

    if spec:
        docs = [d for d in docs if spec in d.file_path]

    if not docs:
        print("No spec files found.")
        return

    # Try to create Claude client
    client = ClaudeClient()
    use_claude = client.is_available

    if not use_claude:
        print("ANTHROPIC_API_KEY not set — using heuristic mode (grep-only).")
        print("Heuristic mode can suggest in_progress but cannot confirm done.\n")

    total_changes = 0
    total_input_tokens = 0
    total_output_tokens = 0

    for doc in docs:
        all_sections = _flatten_sections(doc.sections)

        # Filter to sections that need auditing (blocked preserved as-is)
        skip_states = {"done", "deprecated", "blocked"}
        sections_to_audit = [s for s in all_sections if s.status.state not in skip_states]

        if not sections_to_audit:
            print(f"{doc.frontmatter.title}: all sections done/deprecated, skipping.")
            continue

        print(f"\n{doc.frontmatter.title} ({doc.file_path})")
        print("-" * 50)

        # Gather grep evidence
        evidence = _gather_evidence(root, sections_to_audit)

        # Audit
        if use_claude:
            from canon.agent.client import AgentAPIError

            try:
                recommendations, in_tok, out_tok = _audit_with_claude(
                    client, doc, sections_to_audit, evidence
                )
            except AgentAPIError as e:
                print(f"  Claude API error: {e} — skipping this spec.")
                continue
            total_input_tokens += in_tok
            total_output_tokens += out_tok
        else:
            recommendations = _audit_heuristic(sections_to_audit, evidence)

        # Filter to actionable status changes
        changes = [
            r
            for r in recommendations
            if r.recommended_status != r.current_status and r.confidence in ("high", "medium")
        ]

        # Collect all medium/high confidence recs for AC updates (includes unchanged-status sections)
        ac_eligible = [r for r in recommendations if r.confidence in ("high", "medium")]

        if not changes and not ac_eligible:
            print("  No status changes recommended.")
            continue

        # Print per-section details for status changes
        for r in changes:
            print(
                f"  {r.section_number} {r.section_id}: {r.current_status} → {r.recommended_status} ({r.confidence})"
            )
            if r.reasoning:
                print(f"    {r.reasoning}")
            for ae in r.ac_evaluations:
                symbol = (
                    "+"
                    if ae.status == "realized"
                    else "~"
                    if ae.status == "partially_realized"
                    else "-"
                )
                ev = f" ({ae.evidence})" if ae.evidence else ""
                print(f"    [{symbol}] {ae.ac_text}{ev}")

        # Print AC evaluations for sections without status changes
        unchanged_with_acs = [r for r in ac_eligible if r not in changes and r.ac_evaluations]
        for r in unchanged_with_acs:
            has_realized = any(ae.status == "realized" for ae in r.ac_evaluations)
            if has_realized:
                print(f"  {r.section_number} {r.section_id}: status unchanged, ACs updated")
                for ae in r.ac_evaluations:
                    symbol = (
                        "+"
                        if ae.status == "realized"
                        else "~"
                        if ae.status == "partially_realized"
                        else "-"
                    )
                    ev = f" ({ae.evidence})" if ae.evidence else ""
                    print(f"    [{symbol}] {ae.ac_text}{ev}")

        if not changes and not unchanged_with_acs:
            print("  No status changes recommended.")
            continue

        # Apply after printing details — pass all eligible recs for AC updates
        skip_ac = no_ac_updates or not use_claude
        num_applied = _apply_recommendations(
            root, doc, changes, dry_run, skip_ac_updates=skip_ac, all_recs=ac_eligible
        )
        total_changes += num_applied

    # Summary
    print(f"\nAudit complete: {total_changes} status change(s){' (dry run)' if dry_run else ''}.")
    if use_claude:
        # Approximate cost assuming Sonnet $3/$15 per MTok — informational only
        cost = (total_input_tokens * 3 + total_output_tokens * 15) / 1_000_000
        print(f"Tokens: {total_input_tokens:,} in / {total_output_tokens:,} out (~${cost:.2f})")

    # Optional sync
    if do_sync and total_changes > 0 and not dry_run:
        print("\nRunning ticket sync...")
        from .sync_cmd import run_sync

        run_sync(local=True, root=root, spec=spec)


# ─── Evidence Gathering ──────────────────────────────────


def _gather_evidence(
    root: Path,
    sections: list[SpecSection],
) -> dict[str, list[str]]:
    """Grep codebase for keywords from section titles and ACs.

    Returns dict mapping section_id to list of 'filepath:lineno: content' snippets.
    """
    from canon.cli._keywords import extract_keywords as _extract_keywords

    evidence: dict[str, list[str]] = {}

    for sec in sections:
        # Extract keywords from title + AC texts
        texts = [sec.title] + [ac.text for ac in sec.acceptance_criteria]
        keywords: list[str] = []
        for text in texts:
            keywords.extend(_extract_keywords(text))

        # Deduplicate
        seen: set[str] = set()
        unique_kw: list[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_kw.append(kw)

        snippets: list[str] = []
        for kw in unique_kw[:10]:  # Cap keywords per section
            results = _grep_with_context(root, kw)
            snippets.extend(results)
            if len(snippets) >= 30:  # Cap snippets per section
                snippets = snippets[:30]
                break

        evidence[sec.id] = snippets

    return evidence


def _grep_with_context(root: Path, keyword: str) -> list[str]:
    """Run grep -rn with context on src/ and frontend/src/."""
    results: list[str] = []
    for subdir in ("src", "frontend/src"):
        target = root / subdir
        if not target.exists():
            continue
        try:
            result = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "-C1",
                    "--include=*.py",
                    "--include=*.ts",
                    "--include=*.vue",
                    "--include=*.js",
                    "--include=*.yaml",
                    "--include=*.yml",
                    "--",
                    keyword,
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                # Relativize paths
                for line in result.stdout.strip().split("\n")[:20]:
                    line = line.replace(str(root) + "/", "")
                    results.append(line)
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass
    return results


# ─── Claude Audit ─────────────────────────────────────────


def _audit_with_claude(
    client: ClaudeClient,
    doc: SpecDocument,
    sections: list[SpecSection],
    evidence: dict[str, list[str]],
) -> tuple[list[AuditRecommendation], int, int]:
    """Call Claude to audit sections. Returns (recommendations, input_tokens, output_tokens)."""
    from canon.agent.audit_prompts import AUDIT_SYSTEM_PROMPT, build_audit_message
    from canon.agent.client import AgentConfig

    user_message = build_audit_message(doc, sections, evidence)
    # 8K is sufficient for structured JSON output; avoids overspending on verbose reasoning
    config = AgentConfig(temperature=0, max_output_tokens=8_000)

    result = client.complete(AUDIT_SYSTEM_PROMPT, user_message, config)

    recommendations = _parse_audit_response(result.text, sections)
    return recommendations, result.input_tokens, result.output_tokens


def _parse_audit_response(
    response_text: str,
    sections: list[SpecSection],
) -> list[AuditRecommendation]:
    """Parse Claude's JSON response into AuditRecommendation objects."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        # Try extracting JSON from markdown code fences
        import re

        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", response_text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                print("  Warning: Could not parse Claude response as JSON.")
                return []
        else:
            print("  Warning: Could not parse Claude response as JSON.")
            return []

    # Build section lookup for current status
    sec_map = {s.id: s for s in sections}

    recommendations: list[AuditRecommendation] = []
    for item in data.get("sections", []):
        rec_status = item.get("recommendedStatus", "")
        if rec_status not in VALID_STATES:
            continue

        section_id = item.get("sectionId", "")
        sec = sec_map.get(section_id)

        ac_evals = [
            ACEvaluation(
                ac_text=ae.get("acText", ""),
                status=ae.get("status", "not_evaluated"),
                evidence=ae.get("evidence", ""),
            )
            for ae in item.get("acEvaluations", [])
        ]

        recommendations.append(
            AuditRecommendation(
                section_id=section_id,
                section_number=item.get("sectionNumber", sec.section_number if sec else ""),
                current_status=item.get("currentStatus", sec.status.state if sec else ""),
                recommended_status=item.get("recommendedStatus", ""),
                confidence=item.get("confidence", "low"),
                reasoning=item.get("reasoning", ""),
                ac_evaluations=ac_evals,
            )
        )

    return recommendations


# ─── Heuristic Fallback ──────────────────────────────────


def _audit_heuristic(
    sections: list[SpecSection],
    evidence: dict[str, list[str]],
) -> list[AuditRecommendation]:
    """Grep-only fallback when no API key. Can suggest in_progress but not done."""
    recommendations: list[AuditRecommendation] = []

    for sec in sections:
        snippets = evidence.get(sec.id, [])
        current = sec.status.state

        if current == "blocked":
            continue

        if current == "todo" and snippets:
            recommendations.append(
                AuditRecommendation(
                    section_id=sec.id,
                    section_number=sec.section_number or "",
                    current_status=current,
                    recommended_status="in_progress",
                    confidence="medium",
                    reasoning=f"Found {len(snippets)} code matches via grep",
                )
            )

    return recommendations


# ─── Evidence Parsing ────────────────────────────────────


def _parse_evidence(evidence_str: str) -> tuple[str, str]:
    """Parse an evidence string like 'src/auth.py:10' into (file_path, lines).

    Returns (file_path, lines) where lines may be empty.
    """
    if not evidence_str:
        return ("", "")
    # evidence is typically "file:line" or "file:start-end"
    parts = evidence_str.rsplit(":", 1)
    if len(parts) == 2 and parts[1] and (parts[1][0].isdigit()):
        return (parts[0], parts[1])
    return (evidence_str, "")


# ─── Apply Recommendations ────────────────────────────────


def _apply_recommendations(
    root: Path,
    doc: SpecDocument,
    recommendations: list[AuditRecommendation],
    dry_run: bool,
    *,
    skip_ac_updates: bool = False,
    all_recs: list[AuditRecommendation] | None = None,
) -> int:
    """Write status updates to spec markdown. Returns number of changes applied.

    ``recommendations`` controls status updates (only sections with changed status).
    ``all_recs`` (if provided) controls AC updates — this includes sections whose
    status is unchanged but whose ACs were evaluated.
    """
    from canon.parser.writer import (
        RealizationInsertion,
        StatusUpdate,
        check_off_acs,
        insert_realization_comments,
        insert_status_comment,
        update_status_comments,
    )

    # Build section lookup for start_line info
    all_sections = _flatten_sections(doc.sections)
    sec_map = {s.id: s for s in all_sections}

    # Separate into updates (existing status comments) and inserts (no comment yet)
    updates: list[StatusUpdate] = []
    inserts: list[AuditRecommendation] = []

    for rec in recommendations:
        sec = sec_map.get(rec.section_id)
        if not sec:
            continue

        if sec.status.state != "draft":
            # Section has a status comment — update in place
            updates.append(
                StatusUpdate(
                    section_number=rec.section_number,
                    new_state=rec.recommended_status,
                )
            )
        else:
            # No status comment — need to insert one
            inserts.append(rec)

    if dry_run:
        return len(updates) + len(inserts)

    # Apply updates
    updated_md = doc.raw
    if updates:
        updated_md = update_status_comments(doc, updates)

    # Apply inserts in reverse line order to avoid offset drift
    sorted_inserts = sorted(
        inserts,
        key=lambda r: sec_map[r.section_id].start_line if r.section_id in sec_map else 0,
        reverse=True,
    )
    for rec in sorted_inserts:
        sec = sec_map.get(rec.section_id)
        if sec:
            updated_md = insert_status_comment(
                updated_md, sec.start_line, rec.section_number, rec.recommended_status
            )

    # Apply AC updates: check off realized ACs and insert realization evidence.
    # Use all_recs (all medium/high confidence recs) so ACs are updated even when
    # the section status is unchanged.
    ac_source = all_recs if all_recs is not None else recommendations
    if not skip_ac_updates:
        ac_texts_to_check: list[str] = []
        realization_insertions: list[RealizationInsertion] = []

        for rec in ac_source:
            if rec.confidence not in ("high", "medium"):
                continue
            for ae in rec.ac_evaluations:
                if ae.status != "realized":
                    continue
                ac_texts_to_check.append(ae.ac_text)
                if ae.evidence:
                    file_path, lines = _parse_evidence(ae.evidence)
                    if file_path:
                        realization_insertions.append(
                            RealizationInsertion(
                                ac_text=ae.ac_text,
                                pr_number=None,
                                file_path=file_path,
                                lines=lines,
                            )
                        )

        if ac_texts_to_check:
            updated_md = check_off_acs(updated_md, ac_texts_to_check)

        if realization_insertions:
            # Re-create doc with updated markdown for realization insertion.
            # sections=[] because insert_realization_comments only uses .raw,
            # and the original section line numbers are stale after edits above.
            from canon.parser.models import SpecDocument as SD

            temp_doc = SD(
                file_path=doc.file_path,
                frontmatter=doc.frontmatter,
                sections=[],
                raw=updated_md,
            )
            updated_md = insert_realization_comments(temp_doc, realization_insertions)

    # Write back
    if updated_md != doc.raw:
        spec_path = root / doc.file_path
        spec_path.write_text(updated_md)
        print(f"  Written: {doc.file_path}")
        return max(len(updates) + len(inserts), 1)

    return 0
