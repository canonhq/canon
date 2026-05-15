"""Tests for OAuth client configuration (configure_oauth)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from canon.settings import Settings


class TestConfigureOAuth:
    """Tests for the configure_oauth function."""

    def _make_settings(self, **overrides) -> Settings:
        """Build a Settings instance with sensible defaults plus overrides."""
        defaults = {
            "auth0_domain": "test.us.auth0.com",
            "auth0_client_id": "test-client-id",
            "auth0_client_secret": "test-client-secret",
        }
        defaults.update(overrides)
        return Settings(**defaults)

    def test_registers_auth0_when_enabled(self):
        """When auth0_enabled is true and no auth_provider override, registers 'auth0'."""
        settings = self._make_settings()
        assert settings.auth0_enabled is True

        with patch("canon.auth.oauth.OAuth") as MockOAuth:
            mock_oauth = MagicMock()
            # Simulate no prior registration
            mock_oauth.auth0 = None
            mock_oauth.auth0 = None
            MockOAuth.return_value = mock_oauth

            # Reimport to get fresh module-level `oauth`
            import canon.auth.oauth as oauth_mod

            original_oauth = oauth_mod.oauth
            oauth_mod.oauth = mock_oauth
            try:
                oauth_mod.configure_oauth(settings)
                mock_oauth.register.assert_called_once()
                call_kwargs = mock_oauth.register.call_args
                assert call_kwargs.kwargs["name"] == "auth0"
                assert call_kwargs.kwargs["client_id"] == "test-client-id"
                assert call_kwargs.kwargs["client_secret"] == "test-client-secret"
                assert "openid-configuration" in call_kwargs.kwargs["server_metadata_url"]
                assert "test.us.auth0.com" in call_kwargs.kwargs["server_metadata_url"]
            finally:
                oauth_mod.oauth = original_oauth

    def test_skips_auth0_when_already_registered(self):
        """If auth0 client is already registered, skip registration."""
        settings = self._make_settings()

        import canon.auth.oauth as oauth_mod

        mock_oauth = MagicMock()
        # Simulate auth0 already registered (non-None)
        mock_oauth.auth0 = MagicMock()

        original_oauth = oauth_mod.oauth
        oauth_mod.oauth = mock_oauth
        try:
            oauth_mod.configure_oauth(settings)
            mock_oauth.register.assert_not_called()
        finally:
            oauth_mod.oauth = original_oauth

    def test_includes_audience_when_configured(self):
        """When auth0_audience is set, it's passed in client_kwargs."""
        settings = self._make_settings(auth0_audience="https://api.example.com")

        import canon.auth.oauth as oauth_mod

        mock_oauth = MagicMock()
        mock_oauth.auth0 = None
        mock_oauth.auth0 = None

        original_oauth = oauth_mod.oauth
        oauth_mod.oauth = mock_oauth
        try:
            oauth_mod.configure_oauth(settings)
            call_kwargs = mock_oauth.register.call_args.kwargs
            assert call_kwargs["client_kwargs"]["audience"] == "https://api.example.com"
        finally:
            oauth_mod.oauth = original_oauth

    def test_registers_oidc_when_issuer_set_and_auth0_disabled(self):
        """When oidc_issuer is set and auth0 is not enabled, registers 'oidc'."""
        settings = self._make_settings(
            auth0_domain="",
            auth0_client_id="",
            auth0_client_secret="",
            oidc_issuer="https://idp.example.com",
            oidc_client_id="oidc-client",
            oidc_client_secret="oidc-secret",
        )
        # auth0_enabled should be False when domain/id/secret are empty
        assert settings.auth0_enabled is False

        import canon.auth.oauth as oauth_mod

        mock_oauth = MagicMock()
        mock_oauth.oidc = None
        mock_oauth.oidc = None
        # auth0 should not be checked since auth0_enabled is False
        mock_oauth.auth0 = None

        original_oauth = oauth_mod.oauth
        oauth_mod.oauth = mock_oauth
        try:
            oauth_mod.configure_oauth(settings)
            mock_oauth.register.assert_called_once()
            call_kwargs = mock_oauth.register.call_args.kwargs
            assert call_kwargs["name"] == "oidc"
            assert call_kwargs["client_id"] == "oidc-client"
            assert call_kwargs["client_secret"] == "oidc-secret"
            assert "idp.example.com" in call_kwargs["server_metadata_url"]
        finally:
            oauth_mod.oauth = original_oauth

    def test_skips_oidc_when_already_registered(self):
        """If oidc client is already registered, skip registration."""
        settings = self._make_settings(
            auth0_domain="",
            auth0_client_id="",
            auth0_client_secret="",
            oidc_issuer="https://idp.example.com",
            oidc_client_id="oidc-client",
            oidc_client_secret="oidc-secret",
        )

        import canon.auth.oauth as oauth_mod

        mock_oauth = MagicMock()
        mock_oauth.oidc = MagicMock()  # already registered

        original_oauth = oauth_mod.oauth
        oauth_mod.oauth = mock_oauth
        try:
            oauth_mod.configure_oauth(settings)
            mock_oauth.register.assert_not_called()
        finally:
            oauth_mod.oauth = original_oauth

    def test_oidc_includes_audience_when_configured(self):
        """When oidc_audience is set, it's passed in client_kwargs."""
        settings = self._make_settings(
            auth0_domain="",
            auth0_client_id="",
            auth0_client_secret="",
            oidc_issuer="https://idp.example.com",
            oidc_client_id="oidc-client",
            oidc_client_secret="oidc-secret",
            oidc_audience="https://oidc-api.example.com",
        )

        import canon.auth.oauth as oauth_mod

        mock_oauth = MagicMock()
        mock_oauth.oidc = None
        mock_oauth.oidc = None

        original_oauth = oauth_mod.oauth
        oauth_mod.oauth = mock_oauth
        try:
            oauth_mod.configure_oauth(settings)
            call_kwargs = mock_oauth.register.call_args.kwargs
            assert call_kwargs["client_kwargs"]["audience"] == "https://oidc-api.example.com"
        finally:
            oauth_mod.oauth = original_oauth

    def test_no_registration_when_neither_auth0_nor_oidc(self):
        """When neither auth0 nor oidc_issuer is configured, nothing is registered."""
        settings = self._make_settings(
            auth0_domain="",
            auth0_client_id="",
            auth0_client_secret="",
        )

        import canon.auth.oauth as oauth_mod

        mock_oauth = MagicMock()

        original_oauth = oauth_mod.oauth
        oauth_mod.oauth = mock_oauth
        try:
            oauth_mod.configure_oauth(settings)
            mock_oauth.register.assert_not_called()
        finally:
            oauth_mod.oauth = original_oauth

    def test_oidc_issuer_trailing_slash_stripped(self):
        """Trailing slash on oidc_issuer is stripped in the metadata URL."""
        settings = self._make_settings(
            auth0_domain="",
            auth0_client_id="",
            auth0_client_secret="",
            oidc_issuer="https://idp.example.com/",
            oidc_client_id="oidc-client",
            oidc_client_secret="oidc-secret",
        )

        import canon.auth.oauth as oauth_mod

        mock_oauth = MagicMock()
        mock_oauth.oidc = None
        mock_oauth.oidc = None

        original_oauth = oauth_mod.oauth
        oauth_mod.oauth = mock_oauth
        try:
            oauth_mod.configure_oauth(settings)
            url = mock_oauth.register.call_args.kwargs["server_metadata_url"]
            # Should not have double slash before .well-known
            assert "//.well-known" not in url
            assert url == "https://idp.example.com/.well-known/openid-configuration"
        finally:
            oauth_mod.oauth = original_oauth

    def test_default_scopes(self):
        """Default scopes include openid email profile."""
        settings = self._make_settings()

        import canon.auth.oauth as oauth_mod

        mock_oauth = MagicMock()
        mock_oauth.auth0 = None
        mock_oauth.auth0 = None

        original_oauth = oauth_mod.oauth
        oauth_mod.oauth = mock_oauth
        try:
            oauth_mod.configure_oauth(settings)
            client_kwargs = mock_oauth.register.call_args.kwargs["client_kwargs"]
            assert "openid" in client_kwargs["scope"]
            assert "email" in client_kwargs["scope"]
            assert "profile" in client_kwargs["scope"]
        finally:
            oauth_mod.oauth = original_oauth
