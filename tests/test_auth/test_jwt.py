"""Tests for canon.auth.jwt — validate_access_token, resolve_org_login, resolve_jwt_org."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canon.auth.jwt import resolve_jwt_org, resolve_org_login, validate_access_token


def _settings(**overrides):
    """Build a minimal Settings-like object for JWT tests."""
    defaults = {
        "auth0_domain": "",
        "auth0_audience": "",
        "oidc_issuer": "",
        "oidc_audience": "",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# validate_access_token
# ---------------------------------------------------------------------------


class TestValidateAccessToken:
    """Tests for validate_access_token configuration and decode paths."""

    async def test_legacy_path_requires_auth0_domain_and_audience(self):
        """Without jwks_uri, auth0_domain + auth0_audience are required."""
        settings = _settings()
        with pytest.raises(ValueError, match="Auth0 domain and audience must be configured"):
            await validate_access_token("tok", settings)

    async def test_legacy_path_missing_audience_only(self):
        """auth0_domain present but no audience → ValueError."""
        settings = _settings(auth0_domain="example.auth0.com")
        with pytest.raises(ValueError, match="Auth0 domain and audience must be configured"):
            await validate_access_token("tok", settings)

    async def test_jwks_uri_no_issuer_configured(self):
        """With jwks_uri but no issuer → ValueError."""
        settings = _settings()
        with pytest.raises(ValueError, match="no issuer configured"):
            await validate_access_token("tok", settings, jwks_uri="https://example.com/jwks")

    async def test_oidc_issuer_without_audience_raises(self):
        """Generic OIDC with jwks_uri but no audience → ValueError (confused deputy)."""
        settings = _settings(oidc_issuer="https://idp.example.com")
        mock_key = MagicMock()
        mock_key.key = "fake-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with (
            patch("canon.auth.jwt._get_jwks_client", return_value=mock_client),
            pytest.raises(ValueError, match="JWT audience must be configured"),
        ):
            await validate_access_token("tok", settings, jwks_uri="https://idp.example.com/jwks")

    async def test_auth0_without_audience_raises(self):
        """Auth0 without audience raises ValueError (confused deputy prevention)."""
        settings = _settings(auth0_domain="example.auth0.com")
        mock_key = MagicMock()
        mock_key.key = "fake-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with (
            patch("canon.auth.jwt._get_jwks_client", return_value=mock_client),
            pytest.raises(ValueError, match="JWT audience must be configured"),
        ):
            await validate_access_token(
                "tok", settings, jwks_uri="https://example.auth0.com/.well-known/jwks.json"
            )

    async def test_valid_token_with_oidc_issuer(self):
        """Full valid path: jwks_uri + oidc_issuer + oidc_audience."""
        settings = _settings(
            oidc_issuer="https://idp.example.com",
            oidc_audience="https://api.example.com",
        )
        mock_key = MagicMock()
        mock_key.key = "fake-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        expected_claims = {"sub": "user1", "iss": "https://idp.example.com"}
        with (
            patch("canon.auth.jwt._get_jwks_client", return_value=mock_client),
            patch("canon.auth.jwt.pyjwt.decode", return_value=expected_claims) as mock_decode,
        ):
            result = await validate_access_token(
                "tok", settings, jwks_uri="https://idp.example.com/jwks"
            )

        assert result == expected_claims
        _, kwargs = mock_decode.call_args
        assert kwargs["issuer"] == "https://idp.example.com"
        assert kwargs["audience"] == "https://api.example.com"
        assert kwargs["algorithms"] == ["RS256", "ES256"]

    async def test_legacy_auth0_path_derives_jwks_uri(self):
        """Without jwks_uri, derives from auth0_domain."""
        settings = _settings(
            auth0_domain="example.auth0.com",
            auth0_audience="https://api.example.com",
        )
        mock_key = MagicMock()
        mock_key.key = "fake-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        expected_claims = {"sub": "user1"}
        with (
            patch("canon.auth.jwt._get_jwks_client", return_value=mock_client) as mock_get_client,
            patch("canon.auth.jwt.pyjwt.decode", return_value=expected_claims),
        ):
            result = await validate_access_token("tok", settings)

        assert result == expected_claims
        mock_get_client.assert_called_with("https://example.auth0.com/.well-known/jwks.json")

    async def test_issuer_from_auth0_domain_when_no_oidc_issuer(self):
        """With jwks_uri but only auth0_domain (no oidc_issuer), issuer uses auth0_domain."""
        settings = _settings(
            auth0_domain="example.auth0.com",
            auth0_audience="https://api.example.com",
        )
        mock_key = MagicMock()
        mock_key.key = "fake-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        expected_claims = {"sub": "user1"}
        with (
            patch("canon.auth.jwt._get_jwks_client", return_value=mock_client),
            patch("canon.auth.jwt.pyjwt.decode", return_value=expected_claims) as mock_decode,
        ):
            await validate_access_token("tok", settings, jwks_uri="https://example.auth0.com/jwks")

        _, kwargs = mock_decode.call_args
        assert kwargs["issuer"] == "https://example.auth0.com/"


# ---------------------------------------------------------------------------
# resolve_org_login
# ---------------------------------------------------------------------------


class TestResolveOrgLogin:
    """Tests for resolve_org_login — org_id lookup and single-org fallback."""

    async def test_no_registry_returns_empty(self):
        assert await resolve_org_login({"org_id": "org_123"}, None) == ""

    async def test_org_id_claim_resolves_via_registry(self):
        installation = SimpleNamespace(org_login="my-org")
        registry = AsyncMock()
        registry.get_installation_by_oidc_org = AsyncMock(return_value=installation)
        registry.list_orgs = AsyncMock(return_value=["my-org"])

        result = await resolve_org_login({"org_id": "org_123"}, registry)
        assert result == "my-org"
        registry.get_installation_by_oidc_org.assert_awaited_once_with("org_123")

    async def test_org_id_not_found_falls_back_to_single_org(self):
        registry = AsyncMock()
        registry.get_installation_by_oidc_org = AsyncMock(return_value=None)
        registry.list_orgs = AsyncMock(return_value=["only-org"])

        result = await resolve_org_login({"org_id": "unknown"}, registry)
        assert result == "only-org"

    async def test_no_org_id_single_org_fallback(self):
        registry = AsyncMock()
        registry.list_orgs = AsyncMock(return_value=["solo-org"])

        result = await resolve_org_login({}, registry)
        assert result == "solo-org"

    async def test_no_org_id_multiple_orgs_returns_empty(self):
        registry = AsyncMock()
        registry.list_orgs = AsyncMock(return_value=["org-a", "org-b"])

        result = await resolve_org_login({}, registry)
        assert result == ""

    async def test_no_org_id_no_orgs_returns_empty(self):
        registry = AsyncMock()
        registry.list_orgs = AsyncMock(return_value=[])

        result = await resolve_org_login({}, registry)
        assert result == ""

    async def test_registry_error_on_org_id_falls_through(self):
        registry = AsyncMock()
        registry.get_installation_by_oidc_org = AsyncMock(side_effect=RuntimeError("db down"))
        registry.list_orgs = AsyncMock(return_value=["fallback-org"])

        result = await resolve_org_login({"org_id": "org_123"}, registry)
        assert result == "fallback-org"

    async def test_registry_error_on_list_orgs_returns_empty(self):
        registry = AsyncMock()
        registry.list_orgs = AsyncMock(side_effect=RuntimeError("db down"))

        result = await resolve_org_login({}, registry)
        assert result == ""


# ---------------------------------------------------------------------------
# resolve_jwt_org
# ---------------------------------------------------------------------------


class TestResolveJwtOrg:
    """Tests for resolve_jwt_org — the combined validate + resolve helper."""

    async def test_invalid_token_returns_none(self):
        """When token validation fails, returns None."""
        settings = _settings()
        result = await resolve_jwt_org("bad-token", settings, None)
        assert result is None

    async def test_valid_token_resolves_org(self):
        """When token validates and org resolves, returns org_login."""
        settings = _settings(
            oidc_issuer="https://idp.example.com",
            oidc_audience="https://api.example.com",
        )
        claims = {"sub": "user1", "org_id": "org_abc"}
        installation = SimpleNamespace(org_login="resolved-org")
        registry = AsyncMock()
        registry.get_installation_by_oidc_org = AsyncMock(return_value=installation)

        with patch("canon.auth.jwt.validate_access_token", return_value=claims):
            result = await resolve_jwt_org("good-token", settings, registry)

        assert result == "resolved-org"

    async def test_valid_token_no_org_returns_none(self):
        """When token validates but org resolution returns empty, returns None."""
        settings = _settings(
            oidc_issuer="https://idp.example.com",
            oidc_audience="https://api.example.com",
        )
        claims = {"sub": "user1"}
        registry = AsyncMock()
        registry.list_orgs = AsyncMock(return_value=[])

        with patch("canon.auth.jwt.validate_access_token", return_value=claims):
            result = await resolve_jwt_org("good-token", settings, registry)

        assert result is None

    async def test_uses_provider_jwks_uri(self):
        """When provider is given, calls get_jwks_uri and passes it through."""
        settings = _settings(
            oidc_issuer="https://idp.example.com",
            oidc_audience="https://api.example.com",
        )
        provider = AsyncMock()
        provider.get_jwks_uri = AsyncMock(return_value="https://idp.example.com/jwks")
        registry = AsyncMock()
        registry.list_orgs = AsyncMock(return_value=["org1"])

        claims = {"sub": "user1"}
        with patch("canon.auth.jwt.validate_access_token", return_value=claims) as mock_validate:
            await resolve_jwt_org("tok", settings, registry, provider=provider)

        provider.get_jwks_uri.assert_awaited_once()
        mock_validate.assert_awaited_once_with(
            "tok", settings, jwks_uri="https://idp.example.com/jwks"
        )

    async def test_provider_jwks_failure_returns_none(self):
        """When provider.get_jwks_uri fails, return None instead of falling back
        to a legacy path that could validate against the wrong JWKS."""
        settings = _settings(
            auth0_domain="example.auth0.com",
            auth0_audience="https://api.example.com",
        )
        provider = AsyncMock()
        provider.get_jwks_uri = AsyncMock(side_effect=RuntimeError("provider down"))
        registry = AsyncMock()

        result = await resolve_jwt_org("tok", settings, registry, provider=provider)

        assert result is None
