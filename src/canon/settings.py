"""Application settings loaded from environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, field_validator
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

    # Base URL for constructing webhook callback URLs during OAuth flows.
    # Example: https://canonhq.co
    canon_base_url: str = ""

    # Database (optional — app works without it)
    database_url: str = ""

    # Google Cloud / Vertex AI (optional — embedding service)
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    gcp_service_account_key: str = ""

    # Content cache — serve specs from Postgres instead of GitHub
    content_cache_enabled: bool = False

    # OpenSearch (optional — replaces pgvector + ParadeDB for search)
    opensearch_url: str = ""
    opensearch_username: str = ""
    opensearch_password: SecretStr = SecretStr("")
    opensearch_specs_index: str = "canon-specs"
    opensearch_sections_index: str = "canon-sections"
    opensearch_enabled: bool = False

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
        if not v:
            return v
        # RFC 8414 §2 requires HTTPS for production issuers. Localhost is the
        # standard exception for local development and CI smoke tests — see
        # OAuth 2.1 §7.5.4 (loopback interface redirection) and the long-
        # standing industry convention that http://localhost and http://127.0.0.1
        # are trusted origins. Without this exception, running the OIDC smoke
        # harness against a local Keycloak or Zitadel docker container is
        # impossible without setting up self-signed TLS.
        if v.startswith("https://"):
            return v
        if v.startswith(("http://localhost", "http://127.0.0.1", "http://[::1]")):
            return v
        raise ValueError(
            "oidc_issuer must start with https:// (RFC 8414); "
            "http:// is only allowed for localhost/127.0.0.1/[::1] in local dev"
        )

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

    # Jira Cloud OAuth 2.0 (3LO) — for org-level Jira integration
    jira_oauth_client_id: str = ""
    jira_oauth_client_secret: str = ""

    # Linear OAuth 2.0 — for org-level Linear integration
    linear_oauth_client_id: str = ""
    linear_oauth_client_secret: str = ""

    # PostHog analytics
    posthog_key: str = ""
    posthog_host: str = "https://us.i.posthog.com"

    # PostHog logs via OpenTelemetry (opt-in)
    posthog_logs_enabled: bool = False
    posthog_logs_min_level: str = "WARNING"

    # PostHog Query API (read access for analytics dashboard)
    posthog_personal_api_key: str = ""
    posthog_project_id: str = ""

    # SRE Alerting
    slack_alerts_webhook_url: str = ""
    sre_alerts_enabled: bool = True
    sre_error_spike_threshold: int = 10
    sre_error_spike_window: int = 300
    sre_slow_query_threshold_ms: int = 500
    sre_auto_triage_enabled: bool = True
    sre_weekly_digest_enabled: bool = False

    @property
    def slack_alerts_enabled(self) -> bool:
        return bool(self.slack_alerts_webhook_url)

    # Slack Bot (interactive app — extends the webhook-only SlackAlerter)
    slack_bot_token: str = ""  # xoxb- bot user OAuth token
    slack_signing_secret: str = ""  # Request signature verification
    slack_app_token: str = ""  # xapp- socket mode token (optional)

    @property
    def slack_bot_enabled(self) -> bool:
        """True when the interactive Slack bot is fully configured."""
        return bool(self.slack_bot_token and self.slack_signing_secret)

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

    @field_validator("smtp_port", mode="before")
    @classmethod
    def _empty_smtp_port(cls, v: object) -> object:
        """Treat empty string as missing so the default (587) is used."""
        if v == "":
            return 587
        return v

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

    # Deployment mode — controls cloud vs self-hosted feature gating.
    deployment_mode: Literal["cloud", "self_hosted", "development"] = "development"

    # Admin audit log retention
    admin_audit_retention_days: int = Field(default=90, ge=1)

    model_config = {"env_prefix": "", "case_sensitive": False}
