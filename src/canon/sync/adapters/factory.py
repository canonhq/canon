"""Adapter factory — auto-detect from config, DB, or env vars.

Credential resolution order (highest priority first):
1. CANON.yaml auth_profiles (per-repo overrides)
2. DB org_integrations (per-org OAuth credentials from Settings UI)
3. Environment variables (self-hosted / env-var deployments)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Literal

from canon.sync.adapters.base import TicketAdapter
from canon.sync.adapters.github_issues import GitHubAdapter
from canon.sync.adapters.jira import JiraAdapter
from canon.sync.adapters.linear import LinearAdapter
from canon.sync.mapping import AuthProfile, TicketSystemConfig
from canon.sync.models import GitHubConfig, JiraConfig, LinearConfig

if TYPE_CHECKING:
    from canon.db.integration_store import IntegrationStore

logger = logging.getLogger(__name__)


def create_adapter(
    *,
    ticket_project: str,
    system: Literal["jira", "linear", "github"] | None = None,
) -> TicketAdapter | None:
    """Return a TicketAdapter if credentials are configured, None otherwise."""
    resolved = system or _detect_system()

    if resolved == "jira":
        host = os.environ.get("JIRA_HOST", "")
        email = os.environ.get("JIRA_EMAIL", "")
        api_token = os.environ.get("JIRA_API_TOKEN", "")
        if not host or not email or not api_token:
            return None
        return JiraAdapter(JiraConfig(host=host, email=email, api_token=api_token))

    if resolved == "linear":
        api_key = os.environ.get("LINEAR_API_KEY", "")
        if not api_key:
            return None
        return LinearAdapter(LinearConfig(api_key=api_key))

    if resolved == "github":
        token = os.environ.get("GITHUB_TOKEN", "")
        default_owner = os.environ.get("GITHUB_OWNER", "")
        default_repo = os.environ.get("GITHUB_REPO", "")
        if not token or not default_owner or not default_repo:
            return None
        return GitHubAdapter(
            GitHubConfig(token=token, default_owner=default_owner, default_repo=default_repo)
        )

    return None


def from_config(
    name: str,
    config: TicketSystemConfig,
    auth_profiles: dict[str, AuthProfile] | None = None,
) -> TicketAdapter | None:
    """Create an adapter from a TicketSystemConfig.

    Args:
        name: Logical name of the ticket system (for logging/diagnostics).
        config: The system configuration to create an adapter from.
        auth_profiles: Optional auth profiles for credential resolution.

    Resolves credentials from an auth profile (if set) or falls back to
    the standard env var auto-detection.
    """
    prefix = _resolve_env_prefix(config, auth_profiles)

    if config.system == "jira":
        host = config.host_override or os.environ.get(f"{prefix}HOST", "")
        email = os.environ.get(f"{prefix}EMAIL", "")
        api_token = os.environ.get(f"{prefix}API_TOKEN", "")
        if not host or not email or not api_token:
            logger.warning("Ticket system %r: missing Jira credentials (prefix=%s)", name, prefix)
            return None
        return JiraAdapter(JiraConfig(host=host, email=email, api_token=api_token))

    if config.system == "linear":
        api_key = os.environ.get(f"{prefix}API_KEY", "")
        if not api_key:
            logger.warning("Ticket system %r: missing Linear API key (prefix=%s)", name, prefix)
            return None
        return LinearAdapter(LinearConfig(api_key=api_key))

    if config.system == "github":
        token = os.environ.get(f"{prefix}TOKEN", "")
        # For GitHub, project is "owner/repo" format
        default_owner = os.environ.get(f"{prefix}OWNER", "")
        default_repo = os.environ.get(f"{prefix}REPO", "")
        if config.project and "/" in config.project:
            parts = config.project.split("/", 1)
            default_owner = default_owner or parts[0]
            default_repo = default_repo or parts[1]
        if not token or not default_owner or not default_repo:
            logger.warning("Ticket system %r: missing GitHub credentials (prefix=%s)", name, prefix)
            return None
        return GitHubAdapter(
            GitHubConfig(token=token, default_owner=default_owner, default_repo=default_repo)
        )

    logger.warning("Ticket system %r: unknown system type %r", name, config.system)
    return None


async def validate_config(ticket_project: str) -> None:
    """Validate adapter configuration at startup. Raises on misconfiguration."""
    adapter = create_adapter(ticket_project=ticket_project)
    if adapter is None:
        raise ValueError(f"No ticket adapter configured for project '{ticket_project}'")

    # Only Jira has startup validation
    if isinstance(adapter, JiraAdapter):
        await adapter.validate_config(ticket_project)


def _detect_system() -> Literal["jira", "linear", "github"] | None:
    if os.environ.get("JIRA_HOST"):
        return "jira"
    if os.environ.get("LINEAR_API_KEY"):
        return "linear"
    if os.environ.get("GITHUB_TOKEN"):
        return "github"
    return None


def _resolve_env_prefix(
    config: TicketSystemConfig,
    auth_profiles: dict[str, AuthProfile] | None,
) -> str:
    """Resolve the env var prefix for credential lookup.

    If an auth_profile is referenced, uses its env_prefix.
    Otherwise, uses the default prefix for the system.
    """
    if config.auth_profile and auth_profiles:
        profile = auth_profiles.get(config.auth_profile)
        if profile:
            return profile.env_prefix

    # Default prefixes (match existing env var conventions).
    # All valid systems are covered; VALID_SYSTEMS validation on
    # TicketSystemConfig guarantees config.system is one of these.
    defaults = {
        "jira": "JIRA_",
        "linear": "LINEAR_",
        "github": "GITHUB_",
    }
    prefix = defaults.get(config.system)
    if prefix is None:
        raise ValueError(f"No default env prefix for system {config.system!r}")
    return prefix


async def from_org(
    org_login: str,
    system: Literal["jira", "linear", "github"],
    integration_store: IntegrationStore,
    *,
    ticket_project: str = "",
) -> TicketAdapter | None:
    """Create an adapter using DB-stored OAuth credentials for an org.

    Falls back to env vars if no DB integration exists.
    Resolution: DB org_integrations → env vars.
    """
    config = await integration_store.get_integration_config(org_login, system)

    if config and system == "jira":
        return JiraAdapter(
            JiraConfig(
                auth_method="oauth",
                access_token=config["access_token"],
                refresh_token=config.get("refresh_token", ""),
                cloud_id=config["cloud_id"],
            )
        )

    if config and system == "linear":
        return LinearAdapter(LinearConfig(access_token=config["access_token"]))

    if config and system == "github":
        # GitHub Issues via DB config (stores default repo selection)
        default_owner = config.get("default_owner", "")
        default_repo = config.get("default_repo", "")
        token = config.get("token", "")
        if token and default_owner and default_repo:
            return GitHubAdapter(
                GitHubConfig(token=token, default_owner=default_owner, default_repo=default_repo)
            )

    # Fall back to env var detection
    logger.debug("No DB integration for %s/%s, falling back to env vars", org_login, system)
    return create_adapter(ticket_project=ticket_project, system=system)
