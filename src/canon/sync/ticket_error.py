"""Classify ticket-adapter exceptions into broken-ref error kinds.

Used by reverse_sync to decide whether a per-section failure indicates
a durably-broken ticket reference (404/401/403) or a transient issue
(5xx, 429, timeout, network) that should not flip the broken flag.
"""

from __future__ import annotations

from typing import Literal

import httpx

ErrorKind = Literal["not_found", "forbidden", "unauthorized", "transient"]


def classify_error(exc: BaseException) -> ErrorKind:
    """Map an adapter exception to an error_kind.

    Only ``httpx.HTTPStatusError`` with status 404/401/403 maps to a
    durable broken state. Everything else — 5xx, 429 (rate-limited),
    timeouts, network errors, programming bugs — is ``transient`` so
    the broken flag never trips on a recoverable issue.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return "not_found"
        if code == 403:
            return "forbidden"
        if code == 401:
            return "unauthorized"
    return "transient"
