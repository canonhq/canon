"""Backend routing for canon audit when CANON_TOKEN is set.

When the CLI has a Canon token (either from the environment or from a
stored credential created via ``canon login --token``), audit POSTs the
parsed specs and pre-gathered evidence to the Canon backend's
``/v1/actions/audit`` endpoint instead of calling Claude directly.

This module is the integration seam between the CLI and the backend.
It is intentionally small: a credential resolver, a request builder, a
synchronous HTTP call via httpx, and a response parser. The CLI's
``run_audit`` decides whether to call this module based on the result
of :func:`should_use_backend`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from canon.parser.models import SpecDocument

from ._credentials import load_credentials

DEFAULT_API_URL = "https://api.canonhq.co"


@dataclass(frozen=True)
class BackendCredential:
    """A resolved Canon backend credential ready to use in an HTTP request."""

    token: str
    api_url: str


def resolve_backend_credential() -> BackendCredential | None:
    """Look for a Canon backend credential in env vars or the credential store.

    Resolution order:
    1. ``CANON_TOKEN`` env var (with optional ``CANON_API_URL`` override).
       Used by the GitHub Actions audit action which exports both into
       the runner environment.
    2. Stored credential from ``canon login --token`` (method == "token").
       Used by interactive CLI sessions on dev machines.

    Returns ``None`` if neither is set, in which case the CLI falls
    through to the local Anthropic key path.
    """
    env_token = os.environ.get("CANON_TOKEN", "").strip()
    if env_token:
        env_url = os.environ.get("CANON_API_URL", "").strip() or DEFAULT_API_URL
        return BackendCredential(token=env_token, api_url=env_url)

    cred = load_credentials()
    if cred and cred.get("method") == "token" and cred.get("token"):
        return BackendCredential(
            token=cred["token"],
            api_url=cred.get("api_url") or DEFAULT_API_URL,
        )

    return None


def should_use_backend() -> bool:
    """True iff a Canon backend credential is available."""
    return resolve_backend_credential() is not None


def call_audit_endpoint(
    *,
    docs: list[SpecDocument],
    evidence_by_path: dict[str, dict[str, list[str]]],
    repo: str | None = None,
    workflow_run_id: str | None = None,
    timeout: float = 120.0,
) -> dict:
    """POST to /v1/actions/audit and return the parsed JSON response.

    Raises :class:`BackendAuditError` on non-2xx responses, network
    failures, or missing credentials. Callers in the CLI catch the
    exception and fall through to the local audit path with a clear
    warning so a flaky backend never blocks an audit run.
    """
    cred = resolve_backend_credential()
    if cred is None:
        raise BackendAuditError("No CANON_TOKEN found in env or credential store")

    payload = {
        "specs": [{"path": doc.file_path, "raw_md": doc.raw} for doc in docs],
        "evidence": [
            {"spec_path": path, "section_evidence": sec_map}
            for path, sec_map in evidence_by_path.items()
        ],
    }
    if repo:
        payload["repo"] = repo
    if workflow_run_id:
        payload["workflow_run_id"] = workflow_run_id

    url = cred.api_url.rstrip("/") + "/v1/actions/audit"
    headers = {
        "Authorization": f"Bearer {cred.token}",
        "Content-Type": "application/json",
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise BackendAuditError(f"network error calling {url}: {exc}") from exc

    if response.status_code == 401:
        raise BackendAuditError(
            "Canon backend rejected the token (401). Run "
            "`canon login --token <new-token>` to refresh."
        )
    if response.status_code == 413:
        raise BackendAuditError(
            "spec payload too large for the backend (413). "
            "Use --spec to scope the audit to a single file."
        )
    if response.status_code >= 500:
        raise BackendAuditError(
            f"Canon backend error ({response.status_code}). "
            "The CLI will fall back to local audit on the next run."
        )
    if not response.is_success:
        raise BackendAuditError(
            f"Canon backend returned {response.status_code}: {response.text[:200]}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise BackendAuditError(f"backend returned non-JSON: {exc}") from exc


class BackendAuditError(Exception):
    """Raised when the Canon backend audit endpoint cannot be reached or
    returns an error. The CLI catches this and falls through to the
    local audit path."""
