"""Tests for webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac

from canon.webhooks.verify import (
    verify_asana_signature,
    verify_hmac_sha256,
    verify_jira_signature,
    verify_linear_signature,
)


def _make_signature(payload: bytes, secret: str) -> str:
    """Generate a valid HMAC SHA-256 hex digest."""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class TestVerifyHmacSha256:
    def test_valid_signature(self):
        payload = b'{"action": "updated"}'
        secret = "test-secret"
        sig = _make_signature(payload, secret)
        assert verify_hmac_sha256(payload, sig, secret) is True

    def test_invalid_signature(self):
        payload = b'{"action": "updated"}'
        assert verify_hmac_sha256(payload, "invalid-hex", "test-secret") is False

    def test_wrong_secret(self):
        payload = b'{"action": "updated"}'
        sig = _make_signature(payload, "correct-secret")
        assert verify_hmac_sha256(payload, sig, "wrong-secret") is False

    def test_empty_signature(self):
        assert verify_hmac_sha256(b"payload", "", "secret") is False

    def test_empty_secret(self):
        assert verify_hmac_sha256(b"payload", "some-sig", "") is False

    def test_tampered_payload(self):
        secret = "test-secret"
        sig = _make_signature(b"original", secret)
        assert verify_hmac_sha256(b"tampered", sig, secret) is False

    def test_uppercase_hex_accepted(self):
        """Some providers send uppercase hex digests."""
        payload = b'{"action": "updated"}'
        secret = "test-secret"
        sig = _make_signature(payload, secret).upper()
        assert verify_hmac_sha256(payload, sig, secret) is True


class TestVerifyJiraSignature:
    def test_valid_jira_signature(self):
        payload = b'{"webhookEvent": "jira:issue_updated"}'
        secret = "jira-secret"
        sig = _make_signature(payload, secret)
        assert verify_jira_signature(payload, sig, secret) is True

    def test_sha256_prefixed_signature(self):
        """Jira Cloud may send sha256= prefixed signatures."""
        payload = b'{"webhookEvent": "jira:issue_updated"}'
        secret = "jira-secret"
        sig = f"sha256={_make_signature(payload, secret)}"
        assert verify_jira_signature(payload, sig, secret) is True

    def test_empty_header(self):
        assert verify_jira_signature(b"payload", "", "secret") is False


class TestVerifyLinearSignature:
    def test_valid_linear_signature(self):
        payload = b'{"action": "update", "type": "Issue"}'
        secret = "linear-secret"
        sig = _make_signature(payload, secret)
        assert verify_linear_signature(payload, sig, secret) is True

    def test_invalid_linear_signature(self):
        assert verify_linear_signature(b"payload", "bad-sig", "secret") is False


class TestVerifyAsanaSignature:
    def test_valid_asana_signature(self):
        payload = b'{"events": []}'
        secret = "asana-secret"
        sig = _make_signature(payload, secret)
        assert verify_asana_signature(payload, sig, secret) is True

    def test_empty_header(self):
        assert verify_asana_signature(b"payload", "", "secret") is False
