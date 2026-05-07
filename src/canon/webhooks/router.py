"""Webhook router — endpoints for real-time reverse sync from ticket systems.

Endpoints:
- POST /webhooks/jira — Jira issue updates
- POST /webhooks/linear — Linear issue updates
- POST /webhooks/asana — Asana task updates (handshake only; processing not yet implemented)
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, Response

from canon import analytics

if TYPE_CHECKING:
    from canon.github.client import GitHubClient
from canon.webhooks.processor import ProcessResult, TicketEvent, process_ticket_event
from canon.webhooks.verify import (
    verify_asana_signature,
    verify_jira_signature,
    verify_linear_signature,
)

logger = logging.getLogger(__name__)


def _record_misconfigured_503(source: str, request: Request) -> None:
    """Log + emit telemetry for a webhook 503 caused by missing secret config.

    Without this, every misconfigured-webhook request returns a bare 503 with
    no signal — the same anti-pattern that hid PR #701 for 41 days. The
    webhook providers (Jira/Linear/Asana) retry-then-disable silently, and
    operators have no way to detect the misconfig until ticket sync stops
    working entirely. Always logs (rate-limit via PostHog aggregation, not
    here — webhook providers backoff exponentially so volume stays low) and
    always tracks so the dashboard signal is per-request.
    """
    logger.warning(
        "%s webhook returned 503 — secret is not configured. "
        "Verify the matching K8s Secret is mounted and Doppler is syncing.",
        source,
    )
    try:
        analytics.track(
            "webhook_misconfigured_503",
            properties={
                "source": source,
                "request_ip": request.client.host if request.client else None,
            },
        )
    except Exception:
        logger.debug("Failed to track webhook_misconfigured_503", exc_info=True)


router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Defense-in-depth body size limit. The primary limit should be enforced by
# the reverse proxy (nginx client_max_body_size), but this catches cases
# where the proxy is misconfigured or bypassed.
_MAX_BODY_BYTES = 1_048_576  # 1 MiB


def _track_webhook(system: str, ticket_id: str, result: ProcessResult) -> None:
    """Track webhook processing in analytics."""
    org = result.owner or ""
    analytics.track(
        "webhook_ticket_sync",
        properties={
            "system": system,
            "ticket_id": ticket_id,
            "processed": result.processed,
            "old_state": result.old_state,
            "new_state": result.new_state,
            "error": result.error,
        },
        groups={"organization": org} if org else None,
    )


def _is_infrastructure_error(result: ProcessResult) -> bool:
    """True for errors where a retry might help (API failures, network errors).

    Business outcomes like "no linked section found" are not infrastructure
    errors — returning 500 for those causes webhook retry storms.
    Uses the structured error_kind field rather than string matching.
    """
    return result.error_kind == "infrastructure"


def _log_failure(system: str, ticket_id: str, result: ProcessResult) -> None:
    """Log webhook processing outcomes at appropriate severity."""
    if not result.error:
        return
    if _is_infrastructure_error(result):
        # Infrastructure failure — transient, warrants retry from sender.
        logger.warning(
            "Webhook processing failed for %s:%s — %s (retryable)",
            system,
            ticket_id,
            result.error,
        )
    else:
        # Business outcome — ticket exists but no spec references it.
        logger.info("No spec linked to %s:%s", system, ticket_id)


# ── Jira ───────────────────────────────────────────────────────────


@router.post("/jira")
async def jira_webhook(request: Request) -> Response:
    """Handle Jira webhook events for reverse sync.

    Triggered by: jira:issue_updated
    """
    settings = request.app.state.settings

    # Auth is fail-closed: reject requests when secret is not configured.
    if not settings.jira_webhook_secret:
        _record_misconfigured_503("jira", request)
        return Response(content="Jira webhook secret not configured", status_code=503)

    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        return Response(content="Payload too large", status_code=413)

    signature = request.headers.get("x-hub-signature", "")
    if not verify_jira_signature(body, signature, settings.jira_webhook_secret):
        return Response(content="Invalid signature", status_code=401)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(content="Invalid JSON", status_code=400)

    # Only process issue updates; creation/deletion events are not relevant
    # for reverse sync (the spec already reflects the intended state).
    webhook_event = payload.get("webhookEvent", "")
    if webhook_event != "jira:issue_updated":
        return Response(content="Ignored event", status_code=200)

    issue = payload.get("issue", {})
    issue_key = issue.get("key", "")
    # Jira status category key (new, indeterminate, done)
    status_category = (
        issue.get("fields", {}).get("status", {}).get("statusCategory", {}).get("key", "")
    )

    if not issue_key or not status_category:
        return Response(content="Missing issue data", status_code=400)

    # Jira doesn't identify the target repo — scan all installed repos
    # to find the spec section linked to this ticket.
    client = request.app.state.github_client
    result = await _process_across_repos(client, "jira", issue_key, status_category)

    _track_webhook("jira", issue_key, result)
    _log_failure("jira", issue_key, result)

    return _build_response(result)


def _build_response(result: ProcessResult) -> Response:
    """Build the HTTP response for a webhook processing result.

    Returns 500 only for infrastructure failures (API errors, network issues)
    where a retry might succeed. Business outcomes (e.g. no linked section)
    return 200 to prevent webhook retry storms.
    """
    if _is_infrastructure_error(result):
        # Don't leak internal error details to unauthenticated callers.
        return Response(
            content=json.dumps({"processed": False, "error": "Internal processing error"}),
            status_code=500,
            media_type="application/json",
        )
    return Response(
        content=json.dumps({"processed": result.processed, "error": result.error}),
        status_code=200,
        media_type="application/json",
    )


async def _process_across_repos(
    client: GitHubClient, system: str, ticket_id: str, raw_status: str
) -> ProcessResult:
    """Scan all installed repos (paginated) to find and update a linked spec section.

    First match wins — a ticket ID is expected to link to exactly one spec
    section across all repos. If duplicates exist, only the first is updated.

    Performance: O(repos x spec_files) sequential scan. For installations with
    many repos this is slow. Future optimization: use ticket ID prefixes (e.g.
    Jira project key from "PROJ-123") to filter repos by configured project_key.
    """
    try:
        repos = await client.list_installation_repos()
    except Exception as err:
        return ProcessResult(
            processed=False, error=f"Failed to list repos: {err}", error_kind="infrastructure"
        )

    logger.info("Scanning %d repos for %s ticket %s", len(repos), system, ticket_id)

    last_infra_error: str | None = None
    for repo_data in repos:
        owner = repo_data["owner"]["login"]
        repo_name = repo_data["name"]

        event = TicketEvent(
            system=system,
            ticket_id=ticket_id,
            raw_status=raw_status,
            owner=owner,
            repo=repo_name,
        )

        result = await process_ticket_event(client, event)
        if result.processed:
            return result
        if result.error_kind == "infrastructure":
            last_infra_error = result.error

    # If any repo had an infrastructure failure, report that instead of
    # "not found" — the section may exist but be unreachable.
    if last_infra_error:
        return ProcessResult(processed=False, error=last_infra_error, error_kind="infrastructure")
    return ProcessResult(processed=False, error="No linked spec section found in any repo")


# ── Linear ─────────────────────────────────────────────────────────


@router.post("/linear")
async def linear_webhook(request: Request) -> Response:
    """Handle Linear webhook events for reverse sync.

    Triggered by: Issue updates
    """
    settings = request.app.state.settings

    # Auth is fail-closed: reject requests when secret is not configured.
    if not settings.linear_webhook_secret:
        _record_misconfigured_503("linear", request)
        return Response(content="Linear webhook secret not configured", status_code=503)

    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        return Response(content="Payload too large", status_code=413)

    signature = request.headers.get("linear-signature", "")
    if not verify_linear_signature(body, signature, settings.linear_webhook_secret):
        return Response(content="Invalid signature", status_code=401)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(content="Invalid JSON", status_code=400)

    action = payload.get("action", "")
    resource_type = payload.get("type", "")
    if action != "update" or resource_type != "Issue":
        return Response(content="Ignored action", status_code=200)

    # Linear uses UUIDs for data.id; the human-readable identifier (e.g.
    # "ENG-123") is in data.identifier. Spec links use the readable form.
    issue_id = payload.get("data", {}).get("identifier") or payload.get("data", {}).get("id", "")
    # Linear state type: backlog, unstarted, started, completed, canceled
    state_type = payload.get("data", {}).get("state", {}).get("type", "")

    if not issue_id or not state_type:
        return Response(content="Missing issue data", status_code=400)

    # Linear doesn't tell us the repo — scan all installed repos
    client = request.app.state.github_client
    result = await _process_across_repos(client, "linear", issue_id, state_type)

    _track_webhook("linear", issue_id, result)
    _log_failure("linear", issue_id, result)

    return _build_response(result)


# ── Asana ──────────────────────────────────────────────────────────


@router.post("/asana")
async def asana_webhook(request: Request) -> Response:
    """Handle Asana webhook events for reverse sync.

    Currently only supports the webhook handshake (X-Hook-Secret).
    Task status processing requires an Asana API adapter to fetch
    actual completion status — not yet implemented.
    """
    settings = request.app.state.settings

    # Auth is fail-closed: reject requests when secret is not configured.
    # This check is intentionally before the handshake so unauthenticated
    # callers cannot complete the Asana webhook registration.
    # Uses 503 (not 501) to distinguish from the "not yet implemented" 501
    # returned at the bottom of this handler.
    if not settings.asana_webhook_secret:
        _record_misconfigured_503("asana", request)
        return Response(content="Asana webhook secret not configured", status_code=503)

    # Asana webhook registration handshake: Asana sends X-Hook-Secret and
    # expects the endpoint to echo it back. This is per the Asana webhook API
    # spec — the value is opaque and controlled by Asana, not user input.
    # Sanitized to printable ASCII and bounded to 256 chars as defense-in-depth.
    hook_secret = request.headers.get("x-hook-secret")
    if hook_secret:
        sanitized = re.sub(r"[^\x20-\x7E]", "", hook_secret)[:256]
        return Response(
            content="",
            status_code=200,
            headers={"X-Hook-Secret": sanitized},
        )

    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        return Response(content="Payload too large", status_code=413)

    sig = request.headers.get("x-hook-signature", "")
    if not verify_asana_signature(body, sig, settings.asana_webhook_secret):
        return Response(content="Invalid signature", status_code=401)

    # Asana webhooks don't include task status in the payload — an adapter
    # would need to call the Asana API to fetch it. Until that exists,
    # return 501 rather than silently writing incorrect statuses.
    return Response(
        content="Asana reverse sync not yet implemented",
        status_code=501,
    )
