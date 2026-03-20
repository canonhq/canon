"""Tests for OIDC provider protocol models."""

from __future__ import annotations

from canon.auth.providers.protocol import DeviceCodeResponse, Pending, TokenSet


class TestTokenSet:
    def test_create(self):
        ts = TokenSet(
            access_token="at",
            id_token="it",
            refresh_token="rt",
            expires_in=3600,
        )
        assert ts.access_token == "at"
        assert ts.expires_in == 3600

    def test_optional_fields(self):
        ts = TokenSet(access_token="at")
        assert ts.id_token == ""
        assert ts.refresh_token == ""
        assert ts.expires_in == 0


class TestDeviceCodeResponse:
    def test_create(self):
        dcr = DeviceCodeResponse(
            device_code="dc",
            user_code="UC-1234",
            verification_uri="https://example.com/activate",
            interval=5,
            expires_in=900,
        )
        assert dcr.device_code == "dc"
        assert dcr.interval == 5

    def test_verification_uri_complete_optional(self):
        dcr = DeviceCodeResponse(
            device_code="dc",
            user_code="UC",
            verification_uri="https://example.com",
        )
        assert dcr.verification_uri_complete == ""


class TestPending:
    def test_is_distinct_from_token_set(self):
        p = Pending()
        assert not isinstance(p, TokenSet)
