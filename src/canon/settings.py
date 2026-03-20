"""Application settings loaded from environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Canon application configuration via environment variables."""

    # GitHub App
    gh_app_id: str = ""
    gh_private_key: str = ""
    gh_webhook_secret: str = ""
    gh_installation_id: str = ""

    # Anthropic
    anthropic_api_key: str = ""

    # Jira (optional)
    jira_host: str = ""
    jira_email: str = ""
    jira_api_token: str = ""

    # Linear (optional)
    linear_api_key: str = ""
    # When unconfigured, the /webhooks/linear endpoint returns 503.
    linear_webhook_secret: str = ""

    # GitHub token for ticket sync (optional)
    github_token: str = ""
    github_owner: str = ""
    github_repo: str = ""

    # Jira webhook secret (optional — for real-time reverse sync).
    # When unconfigured, the /webhooks/jira endpoint returns 503.
    jira_webhook_secret: str = ""

    # Asana webhook secret (optional — for real-time reverse sync).
    # When unconfigured, the /webhooks/asana endpoint returns 503.
    asana_webhook_secret: str = ""

    # Database (optional — app works without it)
    database_url: str = ""

    # Google Cloud / Vertex AI (optional — embedding service)
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    gcp_service_account_key: str = ""

    # Auth0 (optional — gates /app/* when configured)
    auth0_domain: str = ""
    auth0_client_id: str = ""
    auth0_client_secret: str = ""
    auth0_audience: str = ""

    # Auth0 Device Authorization (CLI auth — may use a separate Native app)
    auth0_device_client_id: str = ""

    # Platform URL (used by CLI to know where to connect, and for PR comment links)
    platform_url: str = ""

    # Environment: "development", "staging", "preview", "production"
    environment: str = "development"

    @property
    def auth0_enabled(self) -> bool:
        return bool(self.auth0_domain and self.auth0_client_id and self.auth0_client_secret)

    @property
    def oidc_enabled(self) -> bool:
        """True if generic OIDC credentials are fully configured."""
        return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret)

    @property
    def auth_enabled(self) -> bool:
        """True if any auth provider is configured."""
        return self.auth0_enabled or self.oidc_enabled

    @property
    def auth_mode(self) -> str:
        """Effective auth mode: 'auth0', 'oidc', or '' (disabled).

        Mirrors the auto-detection logic in ``create_provider()`` so the
        frontend renders the correct login UI.
        """
        if self.auth_provider:
            return self.auth_provider
        if self.auth0_enabled:
            return "auth0"
        if self.oidc_enabled:
            return "oidc"
        return ""

    # Auth0 Organizations — opt-in, requires an Auth0 Organization to be created
    # and linked via set_oidc_org_id() in the installation registry.
    auth0_orgs_enabled: bool = False

    # Generic OIDC (OSS — bring-your-own identity provider)
    auth_provider: Literal["auth0", "oidc", ""] = ""  # "" = auto-detect
    oidc_issuer: str = ""  # https://your-idp.example.com
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_audience: str = ""
    oidc_scopes: str = "openid email profile"

    @field_validator("oidc_issuer")
    @classmethod
    def _validate_oidc_issuer(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            raise ValueError("oidc_issuer must start with https:// (RFC 8414)")
        return v

    # Auth0 M2M credentials for Management API (org membership queries).
    # When not set, org membership lookups are skipped.
    auth0_m2m_client_id: str = ""
    auth0_m2m_client_secret: str = ""

    # GitHub OAuth (for web editor — user-level repo access)
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""

    @property
    def github_oauth_enabled(self) -> bool:
        return bool(self.github_oauth_client_id and self.github_oauth_client_secret)

    # PostHog analytics
    posthog_key: str = ""
    posthog_host: str = "https://us.i.posthog.com"

    # PostHog logs via OpenTelemetry (opt-in)
    posthog_logs_enabled: bool = False
    posthog_logs_min_level: str = "WARNING"

    # Server
    port: int = 3000
    log_level: str = "info"
    webhook_path: str = "/webhook"

    # MCP
    mcp_api_key: str | None = None

    # Web UI
    web_org: str = ""
    web_admin_logins: str = ""  # Comma-separated GitHub logins granted specs:admin in the SPA

    # Stripe billing
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_starter_monthly_price_id: str = ""
    stripe_starter_annual_price_id: str = ""
    stripe_pro_monthly_price_id: str = ""
    stripe_pro_annual_price_id: str = ""

    # BYOK encryption
    byok_encryption_key: str = ""

    # Enterprise contact
    enterprise_contact_email: str = "sales@canonhq.co"

    # SMTP (optional — for enterprise contact email notifications)
    # Port 465 always uses implicit TLS (SMTP_SSL); smtp_tls enables STARTTLS on other ports.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_tls: bool = True

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def stripe_enabled(self) -> bool:
        return bool(
            self.stripe_secret_key
            and self.stripe_publishable_key
            and self.stripe_webhook_secret
            and self.byok_encryption_key
        )

    cache_ttl_seconds: int = 300

    model_config = {"env_prefix": "", "case_sensitive": False}
