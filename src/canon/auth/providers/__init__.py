"""OIDC provider factory — selects implementation based on settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...settings import Settings
    from .protocol import OIDCProvider


def create_provider(settings: Settings) -> OIDCProvider | None:
    """Create the appropriate OIDC provider based on settings.

    Returns None if no auth provider is configured (dev mode).
    """
    # Explicit provider selection
    provider_type = settings.auth_provider

    if not provider_type:
        # Auto-detect from available settings
        if settings.auth0_enabled:
            provider_type = "auth0"
        elif settings.oidc_enabled:
            provider_type = "oidc"
        else:
            return None

    if provider_type == "auth0":
        from .auth0 import Auth0Provider

        return Auth0Provider(settings=settings)

    if provider_type == "oidc":
        from .generic_oidc import GenericOIDCProvider

        return GenericOIDCProvider(settings=settings)

    raise ValueError(f"Unknown auth_provider: {provider_type!r}. Must be 'auth0' or 'oidc'.")
