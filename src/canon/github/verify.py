"""HMAC SHA-256 webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature (X-Hub-Signature-256).

    Args:
        payload: Raw request body bytes.
        signature: The signature header value (e.g. "sha256=abc123...").
        secret: The webhook secret.

    Returns:
        True if the signature is valid.
    """
    if not signature or not secret:
        return False

    prefix = "sha256="
    if not signature.startswith(prefix):
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"{prefix}{expected}", signature)
