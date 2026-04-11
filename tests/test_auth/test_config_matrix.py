"""Comprehensive configuration matrix tests for OIDC provider auto-detection.

Covers the full cross-product of auth settings combinations, edge cases,
and backward-compatibility guarantees that go beyond the basic factory
tests in ``test_providers/test_factory.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from canon.auth.providers import create_provider
from canon.auth.providers.auth0 import Auth0Provider
from canon.auth.providers.generic_oidc import GenericOIDCProvider
from canon.settings import Settings

# ---------------------------------------------------------------------------
# Shared credential dicts to keep parametrize tables readable
# ---------------------------------------------------------------------------

AUTH0_CREDS = dict(
    auth0_domain="test.auth0.com",
    auth0_client_id="a0-cid",
    auth0_client_secret="a0-csec",
)

OIDC_CREDS = dict(
    oidc_issuer="https://idp.example.com",
    oidc_client_id="oidc-cid",
    oidc_client_secret="oidc-csec",
)


# ===================================================================
# TestAutoDetectionMatrix
# ===================================================================


class TestAutoDetectionMatrix:
    """Parametrized matrix covering all 7 auto-detection paths."""

    @pytest.mark.parametrize(
        "settings_kwargs, expected_type, expected_error",
        [
            pytest.param(
                {},
                type(None),
                None,
                id="no-creds-returns-none",
            ),
            pytest.param(
                {**AUTH0_CREDS},
                Auth0Provider,
                None,
                id="auth0-creds-only",
            ),
            pytest.param(
                {**OIDC_CREDS},
                GenericOIDCProvider,
                None,
                id="oidc-creds-only",
            ),
            pytest.param(
                {**AUTH0_CREDS, **OIDC_CREDS},
                Auth0Provider,
                None,
                id="both-creds-auth0-wins-backward-compat",
            ),
            pytest.param(
                {"auth_provider": "auth0", **AUTH0_CREDS},
                Auth0Provider,
                None,
                id="explicit-auth0",
            ),
            pytest.param(
                {"auth_provider": "oidc", **OIDC_CREDS},
                GenericOIDCProvider,
                None,
                id="explicit-oidc",
            ),
            pytest.param(
                {"auth_provider": "unknown"},
                None,
                ValidationError,
                id="explicit-unknown-raises",
            ),
        ],
    )
    def test_auto_detection(self, settings_kwargs, expected_type, expected_error):
        if expected_error is ValidationError:
            # Pydantic Literal type catches invalid auth_provider at Settings construction
            with pytest.raises(ValidationError, match="auth_provider"):
                Settings(**settings_kwargs)
            return
        s = Settings(**settings_kwargs)
        if expected_error is not None:
            with pytest.raises(expected_error):
                create_provider(s)
        else:
            result = create_provider(s)
            if expected_type is type(None):
                assert result is None
            else:
                assert isinstance(result, expected_type)


# ===================================================================
# TestAuthEnabledProperty
# ===================================================================


class TestAuthEnabledProperty:
    """Test ``Settings.auth_enabled`` across all credential combinations."""

    @pytest.mark.parametrize(
        "settings_kwargs, expected",
        [
            pytest.param({}, False, id="neither-configured"),
            pytest.param({**AUTH0_CREDS}, True, id="auth0-only"),
            pytest.param({**OIDC_CREDS}, True, id="oidc-only"),
            pytest.param({**AUTH0_CREDS, **OIDC_CREDS}, True, id="both-configured"),
            pytest.param(
                {"auth0_domain": "test.auth0.com"},
                False,
                id="partial-auth0-domain-only",
            ),
            pytest.param(
                {"oidc_issuer": "https://idp.example.com"},
                False,
                id="partial-oidc-issuer-only",
            ),
        ],
    )
    def test_auth_enabled(self, settings_kwargs, expected):
        s = Settings(**settings_kwargs)
        assert s.auth_enabled is expected


# ===================================================================
# TestAuthModeProperty
# ===================================================================


class TestAuthModeProperty:
    """Test ``Settings.auth_mode`` returns the correct string."""

    @pytest.mark.parametrize(
        "settings_kwargs, expected",
        [
            pytest.param({}, "", id="no-creds-empty-string"),
            pytest.param({**AUTH0_CREDS}, "auth0", id="auth0-only"),
            pytest.param({**OIDC_CREDS}, "oidc", id="oidc-only"),
            pytest.param({**AUTH0_CREDS, **OIDC_CREDS}, "auth0", id="both-auth0-wins"),
            pytest.param(
                {"auth_provider": "oidc", **AUTH0_CREDS, **OIDC_CREDS},
                "oidc",
                id="explicit-oidc-overrides-auth0",
            ),
        ],
    )
    def test_auth_mode(self, settings_kwargs, expected):
        s = Settings(**settings_kwargs)
        assert s.auth_mode == expected


# ===================================================================
# TestSettingsBackwardCompat
# ===================================================================


class TestSettingsBackwardCompat:
    """Ensure adding OIDC settings did not break existing property contracts."""

    def test_auth0_enabled_with_oidc_also_present(self):
        """``auth0_enabled`` is True even when OIDC creds are also set."""
        s = Settings(**AUTH0_CREDS, **OIDC_CREDS)
        assert s.auth0_enabled is True

    def test_stripe_enabled_unaffected_by_auth_changes(self):
        """Stripe enablement is independent of auth configuration."""
        s = Settings(
            **AUTH0_CREDS,
            stripe_secret_key="sk_test_xxx",
            stripe_publishable_key="pk_test_xxx",
            stripe_webhook_secret="whsec_xxx",
            byok_encryption_key="enc_key",
        )
        assert s.stripe_enabled is True
        # And without auth — stripe still works
        s2 = Settings(
            stripe_secret_key="sk_test_xxx",
            stripe_publishable_key="pk_test_xxx",
            stripe_webhook_secret="whsec_xxx",
            byok_encryption_key="enc_key",
        )
        assert s2.stripe_enabled is True

    def test_github_oauth_enabled_unaffected_by_auth_changes(self):
        """GitHub OAuth enablement is independent of OIDC auth."""
        s = Settings(
            **AUTH0_CREDS,
            github_oauth_client_id="gh-cid",
            github_oauth_client_secret="gh-csec",
        )
        assert s.github_oauth_enabled is True
        # Without auth — still works
        s2 = Settings(
            github_oauth_client_id="gh-cid",
            github_oauth_client_secret="gh-csec",
        )
        assert s2.github_oauth_enabled is True

    def test_default_settings_have_auth_disabled(self):
        """Bare ``Settings()`` must have all auth properties disabled."""
        s = Settings()
        assert s.auth_enabled is False
        assert s.auth0_enabled is False
        assert s.auth_mode == ""
        assert s.stripe_enabled is False
        assert s.github_oauth_enabled is False


# ===================================================================
# TestPartialConfigurations
# ===================================================================


class TestPartialConfigurations:
    """Edge cases with incomplete or mismatched credentials."""

    def test_only_auth0_domain_no_client_id(self):
        """Setting only ``auth0_domain`` without client creds -> auth disabled."""
        s = Settings(auth0_domain="test.auth0.com")
        assert s.auth_enabled is False
        assert s.auth0_enabled is False
        assert create_provider(s) is None

    def test_only_oidc_issuer_no_client_id(self):
        """Setting only ``oidc_issuer`` without client creds -> auth disabled."""
        s = Settings(oidc_issuer="https://idp.example.com")
        assert s.auth_enabled is False
        assert create_provider(s) is None

    def test_explicit_auth0_without_auth0_creds_raises(self):
        """Explicit auth_provider='auth0' without creds raises at construction."""
        s = Settings(auth_provider="auth0")
        with pytest.raises(ValueError, match="auth0_domain is required"):
            create_provider(s)

    def test_explicit_oidc_without_oidc_creds_raises(self):
        """Explicit auth_provider='oidc' without creds raises at construction."""
        s = Settings(auth_provider="oidc")
        with pytest.raises(ValueError, match="oidc_issuer is required"):
            create_provider(s)

    def test_auth0_domain_and_client_id_but_no_secret(self):
        """Two of three Auth0 fields set — still not enough."""
        s = Settings(auth0_domain="test.auth0.com", auth0_client_id="cid")
        assert s.auth0_enabled is False
        assert s.auth_enabled is False
        assert create_provider(s) is None

    def test_oidc_issuer_and_client_id_but_no_secret(self):
        """Two of three OIDC fields set — still not enough."""
        s = Settings(oidc_issuer="https://idp.example.com", oidc_client_id="cid")
        assert s.auth_enabled is False
        assert create_provider(s) is None


class TestOidcIssuerValidation:
    """``oidc_issuer`` validator — HTTPS required except for localhost."""

    def test_https_issuer_accepted(self):
        s = Settings(oidc_issuer="https://idp.example.com")
        assert s.oidc_issuer == "https://idp.example.com"

    def test_empty_issuer_accepted(self):
        """Empty issuer means OIDC not configured — validator must not fire."""
        s = Settings(oidc_issuer="")
        assert s.oidc_issuer == ""

    def test_plain_http_non_localhost_rejected(self):
        with pytest.raises(ValueError, match="must start with https://"):
            Settings(oidc_issuer="http://idp.example.com")

    @pytest.mark.parametrize(
        "issuer",
        [
            "http://localhost:8180/realms/canon-smoke",
            "http://localhost/realms/canon-smoke",
            "http://127.0.0.1:8180/realms/canon-smoke",
            "http://[::1]:8180/realms/canon-smoke",
        ],
    )
    def test_localhost_http_accepted(self, issuer: str):
        """Localhost is the standard exception so local dev and CI smoke
        tests against dockerized IDPs (Keycloak, Zitadel) don't need TLS."""
        s = Settings(oidc_issuer=issuer)
        assert s.oidc_issuer == issuer
