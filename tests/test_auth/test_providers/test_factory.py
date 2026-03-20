"""Tests for provider auto-detection and factory."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from canon.auth.providers import create_provider
from canon.auth.providers.auth0 import Auth0Provider
from canon.settings import Settings


class TestCreateProvider:
    def test_returns_none_when_no_auth(self):
        s = Settings()
        assert create_provider(s) is None

    def test_auto_detects_auth0(self):
        s = Settings(
            auth0_domain="test.auth0.com",
            auth0_client_id="cid",
            auth0_client_secret="csec",
        )
        p = create_provider(s)
        assert isinstance(p, Auth0Provider)

    def test_auto_detects_oidc(self):
        from canon.auth.providers.generic_oidc import GenericOIDCProvider

        s = Settings(
            oidc_issuer="https://idp.example.com",
            oidc_client_id="cid",
            oidc_client_secret="csec",
        )
        p = create_provider(s)
        assert isinstance(p, GenericOIDCProvider)

    def test_explicit_auth_provider_overrides(self):
        s = Settings(
            auth_provider="auth0",
            auth0_domain="test.auth0.com",
            auth0_client_id="cid",
            auth0_client_secret="csec",
            oidc_issuer="https://idp.example.com",
            oidc_client_id="oidc-cid",
            oidc_client_secret="oidc-csec",
        )
        p = create_provider(s)
        assert isinstance(p, Auth0Provider)

    def test_auth_enabled_with_oidc(self):
        s = Settings(
            oidc_issuer="https://idp.example.com",
            oidc_client_id="cid",
            oidc_client_secret="csec",
        )
        assert s.auth_enabled is True

    def test_auth_enabled_with_auth0(self):
        s = Settings(
            auth0_domain="test.auth0.com",
            auth0_client_id="cid",
            auth0_client_secret="csec",
        )
        assert s.auth_enabled is True

    def test_auth_enabled_false_when_empty(self):
        s = Settings()
        assert s.auth_enabled is False

    def test_unknown_provider_raises(self):
        with pytest.raises(ValidationError, match="auth_provider"):
            Settings(auth_provider="unknown")
