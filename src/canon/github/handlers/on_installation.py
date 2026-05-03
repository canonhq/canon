"""Handle installation events — created, deleted, suspend, unsuspend."""

from __future__ import annotations

import logging

from canon import analytics

from . import fire_and_forget
from .onboarding import onboard_repos

logger = logging.getLogger(__name__)


def _get_app_state():
    """Import app and return its state. Returns None if unavailable."""
    try:
        from canon.main import app

        return app.state
    except Exception:
        return None


async def on_installation(client, payload: dict, *, _app_state=None) -> None:
    """Handle a GitHub App installation event.

    Args:
        client: GitHubClient instance (scoped to the installation).
        payload: The webhook payload.
        _app_state: Injected app state (for testing). Falls back to main app.
    """
    action = payload.get("action", "")
    installation = payload.get("installation", {})
    installation_id = installation.get("id", 0)
    account = installation.get("account", {})
    org_login = account.get("login", "")
    org_id = account.get("id", 0)
    app_id = str(installation.get("app_id", ""))

    logger.info(
        "installation event: action=%s org=%s installation_id=%s",
        action,
        org_login,
        installation_id,
    )

    state = _app_state or _get_app_state()
    if state is None:
        logger.warning("Could not access app state for installation event")
        return

    registry = getattr(state, "registry", None)
    if registry is None:
        logger.info("No registry available — skipping installation event")
        return

    if action == "created":
        await registry.upsert_installation(
            installation_id=installation_id,
            org_login=org_login,
            org_id=org_id,
            app_id=app_id,
        )
        logger.info("Registered installation %s for %s", installation_id, org_login)

        analytics.group("organization", org_login, {"installation_id": installation_id})
        analytics.track(
            "app_installed",
            properties={"org": org_login, "installation_id": installation_id},
            groups={"organization": org_login},
        )

        # Schedule background indexing
        indexer = getattr(state, "indexer", None)
        search_index = getattr(state, "search_index", None)
        embed_client = getattr(state, "embed_client", None)

        if indexer is not None and search_index is not None:
            indexer.schedule_org_index(
                installation_id=installation_id,
                org_login=org_login,
                client=client,
                search_index=search_index,
                embed_client=embed_client,
                registry=registry,
                content_cache_store=getattr(state, "content_cache_store", None),
                opensearch_client=getattr(state, "opensearch_client", None),
            )
            logger.info("Scheduled background indexing for %s", org_login)

        # Auto-provision Auth0 org (fire-and-forget — don't block webhook)
        provider = getattr(state, "oidc_provider", None)
        if provider and hasattr(provider, "create_organization"):
            fire_and_forget(_provision_auth0_org(provider, registry, installation_id, org_login))

        # Schedule background onboarding (repos are already in the payload)
        repos = payload.get("repositories", [])
        if repos:
            fire_and_forget(onboard_repos(client, repos))

    elif action == "deleted":
        # Disable Auth0 org connections (fire-and-forget)
        provider = getattr(state, "oidc_provider", None)
        if provider and hasattr(provider, "disable_org_connections"):
            installation = await registry.get_installation_by_id(installation_id)
            if installation and installation.oidc_org_id:
                fire_and_forget(provider.disable_org_connections(installation.oidc_org_id))

        await registry.mark_removed(installation_id)
        logger.info("Marked installation %s as removed", installation_id)

        analytics.track(
            "app_uninstalled",
            properties={"org": org_login, "installation_id": installation_id},
            groups={"organization": org_login},
        )

    elif action == "suspend":
        await registry.mark_suspended(installation_id)
        logger.info("Marked installation %s as suspended", installation_id)

    elif action == "unsuspend":
        await registry.mark_unsuspended(installation_id)
        logger.info("Marked installation %s as unsuspended", installation_id)


class ProvisionResult:
    """Outcome of an Auth0 provisioning attempt.

    ``status`` distinguishes the four meaningful cases the admin repair
    endpoint needs to disambiguate so it can return either 200 (no-op) or
    422 (failure) and emit the correct audit event.

    - ``"provisioned"`` — fresh org created end-to-end
    - ``"already_provisioned"`` — registry already had a valid oidc_org_id;
      the helper short-circuited and made no Auth0 calls
    - ``"reused"`` — Auth0 org existed (reinstall / partial-failure recovery)
      but the registry was missing oidc_org_id; the helper relinked it
    - ``"repaired"`` — connections were missing or had been stripped by a
      prior uninstall; the helper re-enabled them
    """

    def __init__(self, *, oidc_org_id: str, status: str) -> None:
        self.oidc_org_id = oidc_org_id
        self.status = status


async def provision_auth0_org(
    provider,
    registry,
    *,
    installation_id: int,
    org_login: str,
    skip_if_set: bool = True,
) -> ProvisionResult:
    """Provision an Auth0 Organization for a GitHub installation.

    Strict variant of the webhook provisioning path. Idempotent across all
    branches: safe to call when the registry already has an oidc_org_id, when
    the Auth0 org exists but isn't linked, and when connections were stripped.

    Raises on any Auth0 or registry error so callers (the admin repair
    endpoint) can return a 422 with the underlying detail. The webhook path
    wraps this in ``_provision_auth0_org_silently`` to preserve fire-and-forget
    semantics.

    When ``skip_if_set`` is True (default), an installation that already has
    an oidc_org_id short-circuits with status ``already_provisioned`` and
    makes no Auth0 calls — the cheapest possible repair-endpoint hit.
    """
    if skip_if_set:
        existing = await registry.get_installation_by_id(installation_id)
        if existing is not None and existing.oidc_org_id:
            return ProvisionResult(oidc_org_id=existing.oidc_org_id, status="already_provisioned")

    org_name = org_login.lower()
    existing_org_id = await provider.get_organization_by_name(org_name)
    if existing_org_id:
        org_id = existing_org_id
        status = "reused"
        logger.info("Reusing existing Auth0 org %s for %s", org_id, org_login)
    else:
        org_id = await provider.create_organization(name=org_name, display_name=org_login)
        status = "provisioned"

    # Always enable connections — idempotent (409 ignored). Fixes reinstall
    # after uninstall where disable_org_connections stripped them.
    github_conn_id = await provider.get_connection_by_name("github")
    db_conn_id = await provider.get_connection_by_name("Username-Password-Authentication")
    await provider.enable_org_connections(org_id, github_conn_id, db_conn_id)

    await registry.set_oidc_org_id(installation_id, org_id)
    logger.info(
        "Provisioned Auth0 org %s for installation %s (status=%s)",
        org_id,
        installation_id,
        status,
    )
    return ProvisionResult(oidc_org_id=org_id, status=status)


async def _provision_auth0_org(provider, registry, installation_id: int, org_login: str) -> None:
    """Fire-and-forget wrapper for the webhook path — swallows exceptions.

    The webhook handler must not block on Auth0 provisioning, and the
    failure mode is recoverable via the admin repair endpoint
    (POST /api/admin/orgs/{org}/repair-auth0). Logs failures with full
    context so they're discoverable in observability.
    """
    try:
        await provision_auth0_org(
            provider,
            registry,
            installation_id=installation_id,
            org_login=org_login,
            # Webhook path always tries to provision (even if oidc_org_id was
            # set) — the existing behavior happens to be idempotent already
            # because get_organization_by_name returns the existing org.
            skip_if_set=False,
        )
    except Exception:
        logger.exception("Failed to provision Auth0 org for installation %s", installation_id)
