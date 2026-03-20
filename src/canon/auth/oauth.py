"""OAuth client configuration — registers the OIDC provider via authlib."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from ..settings import Settings

oauth = OAuth()


def configure_oauth(settings: Settings) -> None:
    """Register the OIDC provider for authlib. Call during app startup.

    Safe to call multiple times (e.g. during testing or hot-reload) —
    skips registration if the client is already registered.
    """
    client_kwargs: dict = {"scope": settings.oidc_scopes or "openid email profile"}

    if settings.auth0_enabled and (not settings.auth_provider or settings.auth_provider == "auth0"):
        if getattr(oauth, "auth0", None) is not None:
            return
        if settings.auth0_audience:
            client_kwargs["audience"] = settings.auth0_audience
        oauth.register(
            name="auth0",
            client_id=settings.auth0_client_id,
            client_secret=settings.auth0_client_secret,
            server_metadata_url=f"https://{settings.auth0_domain}/.well-known/openid-configuration",
            client_kwargs=client_kwargs,
        )
    elif settings.oidc_issuer:
        if getattr(oauth, "oidc", None) is not None:
            return
        if settings.oidc_audience:
            client_kwargs["audience"] = settings.oidc_audience
        oauth.register(
            name="oidc",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration",
            client_kwargs=client_kwargs,
        )
