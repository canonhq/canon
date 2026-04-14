"""Public v1 API endpoints consumed by the Canon GitHub Actions suite.

These routes are the bridge between the action suite and the Canon
backend. They accept ``CANON_TOKEN``-authenticated requests, run the
analyzer core, and return structured JSON. Today we ship the audit
endpoint; verify and others land in follow-up slices.

Authentication uses the existing ``Bearer`` header path
(``auth.deps.get_current_user``) which already handles the ``sw_*``
API key format that Canon issues. The action layer treats those tokens
as the ``CANON_TOKEN`` secret it stores in GitHub.

Endpoints are read-only. They never persist drift back to specs — that
happens client-side in the action when ``mode: pr`` is set. The
endpoint returns recommendations and lets the caller decide.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from canon.agent.client import ClaudeClient
from canon.auth.deps import require_permission
from canon.auth.models import CurrentUser
from canon.auth.permissions import Permission
from canon.cli.audit import (
    _recommendation_to_dict,
    audit_document,
)
from canon.parser.models import ParseOptions
from canon.parser.parse import parse_spec

logger = logging.getLogger(__name__)

# ─── Limits ──────────────────────────────────────────────

# Per-spec markdown size cap. Real Canon specs run ~50KB, this leaves
# headroom while bounding worst-case payload size and Claude prompt cost.
MAX_SPEC_BYTES = 500_000

# Maximum specs per request. Lets a single audit run cover an entire
# small repo without paginating; large monorepos should batch by team
# or directory and dispatch multiple requests.
MAX_SPECS_PER_REQUEST = 50

# Cap on snippets per section in the evidence map. Mirrors the CLI's
# internal cap in _gather_evidence so the prompt size is bounded.
MAX_EVIDENCE_PER_SECTION = 30

# ─── Request / Response Models ────────────────────────────


class SpecPayload(BaseModel):
    """A single spec markdown file the action wants audited."""

    path: str = Field(..., description="Path inside the consumer repo, e.g. 'docs/specs/auth.md'")
    raw_md: str = Field(
        ..., description="Raw spec markdown — frontmatter + sections + comments + ACs"
    )


class SpecEvidence(BaseModel):
    """Pre-gathered grep evidence keyed by section_id within one spec."""

    spec_path: str
    section_evidence: dict[str, list[str]] = Field(
        default_factory=dict,
        description="section_id -> list of 'file:lineno: snippet' strings (capped per section)",
    )


class AuditRequest(BaseModel):
    specs: list[SpecPayload] = Field(..., min_length=1, max_length=MAX_SPECS_PER_REQUEST)
    evidence: list[SpecEvidence] = Field(
        default_factory=list,
        description=(
            "Optional pre-gathered evidence per spec. When omitted, the audit "
            "runs without code context — useful for spec-only sanity checks."
        ),
    )
    repo: str | None = Field(
        default=None,
        description="Optional 'owner/name' of the consumer repo, for logging only",
    )
    workflow_run_id: str | None = Field(
        default=None,
        description="Optional GitHub Actions run ID, for traceability",
    )


class ACEvaluationDTO(BaseModel):
    ac_text: str
    status: str
    evidence: str = ""


class RecommendationDTO(BaseModel):
    spec: str
    spec_title: str
    section_id: str
    section_number: str
    current_status: str
    recommended_status: str
    confidence: str
    reasoning: str
    ac_evaluations: list[ACEvaluationDTO]


class AuditSummaryDTO(BaseModel):
    schema_version: int = 1
    mode: str  # claude | heuristic | none
    specs_scanned: int
    recommendations: int
    status_changes: int
    ac_evaluations: int
    input_tokens: int
    output_tokens: int


class AuditResponse(BaseModel):
    recommendations: list[RecommendationDTO]
    summary: AuditSummaryDTO


# ─── Router ──────────────────────────────────────────────

api_v1_actions_router = APIRouter(prefix="/v1/actions", tags=["v1-actions"])


@api_v1_actions_router.post(
    "/audit",
    response_model=AuditResponse,
    response_class=JSONResponse,
)
def post_audit(
    body: AuditRequest,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> AuditResponse:
    """Audit one or more spec markdown payloads against pre-gathered evidence.

    The action calls this endpoint with raw spec markdown plus optional
    grep evidence collected from the consumer repo's working tree.
    Returns recommendations identical in shape to ``canon audit --json``
    output. The endpoint does not persist anything — the action decides
    whether to open an issue, PR, or step summary.
    """
    # Reject oversized specs early so a runaway payload doesn't get parsed.
    for spec in body.specs:
        if len(spec.raw_md.encode("utf-8")) > MAX_SPEC_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Spec '{spec.path}' exceeds {MAX_SPEC_BYTES // 1000}KB limit. "
                    "Split the spec or scope the audit with a glob filter."
                ),
            )

    logger.info(
        "v1.audit run",
        extra={
            "user_sub": user.sub,
            "org": user.org_login,
            "repo": body.repo,
            "workflow_run_id": body.workflow_run_id,
            "spec_count": len(body.specs),
        },
    )

    # Build evidence lookup keyed by spec path for O(1) per-doc access.
    evidence_by_path: dict[str, dict[str, list[str]]] = {}
    for ev in body.evidence:
        # Cap per-section snippets defensively even though the action also caps.
        capped = {
            sid: snips[:MAX_EVIDENCE_PER_SECTION] for sid, snips in ev.section_evidence.items()
        }
        evidence_by_path[ev.spec_path] = capped

    client = ClaudeClient()
    use_claude = client.is_available

    all_recommendations: list[dict] = []
    specs_scanned = 0
    total_input_tokens = 0
    total_output_tokens = 0

    for spec in body.specs:
        parse_result = parse_spec(
            spec.raw_md,
            ParseOptions(file_path=spec.path, include_content=True),
        )
        doc = parse_result.document
        spec_evidence = evidence_by_path.get(spec.path, {})

        recommendations, in_tok, out_tok = audit_document(
            client, doc, spec_evidence, use_claude=use_claude
        )

        # Count and meter every spec the analyzer actually evaluated,
        # not just specs that produced recommendations. A spec that
        # consumed Claude tokens but came back clean still counts toward
        # specs_scanned and contributes to the token totals — those are
        # billing-relevant numbers and the CLI's `specs_scanned`
        # semantics include any auditable spec.
        specs_scanned += 1
        total_input_tokens += in_tok
        total_output_tokens += out_tok

        if not recommendations:
            continue

        ac_eligible = [r for r in recommendations if r.confidence in ("high", "medium")]
        for rec in ac_eligible:
            all_recommendations.append(_recommendation_to_dict(doc, rec))

    status_changes = sum(
        1 for r in all_recommendations if r["recommended_status"] != r["current_status"]
    )
    ac_evaluations = sum(len(r["ac_evaluations"]) for r in all_recommendations)

    summary = AuditSummaryDTO(
        schema_version=1,
        mode="claude" if use_claude else "heuristic",
        specs_scanned=specs_scanned,
        recommendations=len(all_recommendations),
        status_changes=status_changes,
        ac_evaluations=ac_evaluations,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
    )

    return AuditResponse(
        recommendations=[RecommendationDTO(**r) for r in all_recommendations],
        summary=summary,
    )
