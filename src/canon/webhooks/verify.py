"""Webhook signature verification for ticket system webhooks.

Each ticket system uses a different signature scheme:
- GitHub: HMAC SHA-256 via X-Hub-Signature-256 (reuses existing verify_signature)
- Jira: HMAC SHA-256 via X-Hub-Signature header
- Linear: HMAC SHA-256 via Linear-Signature header
- Asana: HMAC SHA-256 via X-Hook-Signature header (+ X-Hook-Secret handshake)
"""

from __future__ import annotations

import hashlib
import hmac


def verify_hmac_sha256(payload: bytes, signature_hex: str, secret: str) -> bool:
    """Verify an HMAC SHA-256 signature against a raw hex digest.

    This is the common building block — each system wraps it with
    header-specific parsing.
    """
    if not signature_hex or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_hex.lower())


def verify_jira_signature(payload: bytes, header: str, secret: str) -> bool:
    """Verify Jira webhook signature (X-Hub-Signature header).

    Handles both raw hex digests and sha256= prefixed values,
    since the format varies across Jira versions.
    """
    if not header:
        return False
    # Strip sha256= prefix if present (Jira Cloud vs Server difference)
    sig = header.removeprefix("sha256=")
    return verify_hmac_sha256(payload, sig, secret)


def verify_linear_signature(payload: bytes, header: str, secret: str) -> bool:
    """Verify Linear webhook signature (Linear-Signature header)."""
    if not header:
        return False
    return verify_hmac_sha256(payload, header, secret)


def verify_asana_signature(payload: bytes, header: str, secret: str) -> bool:
    """Verify Asana webhook signature (X-Hook-Signature header)."""
    if not header:
        return False
    return verify_hmac_sha256(payload, header, secret)
