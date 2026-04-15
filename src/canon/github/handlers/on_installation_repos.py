"""Handle installation_repositories events — repos added/removed from installation."""

from __future__ import annotations

import logging

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


async def on_installation_repositories(client, payload: dict, *, _app_state=None) -> None:
    """Handle repos added to or removed from a GitHub App installation.

    Args:
        client: GitHubClient instance.
        payload: The webhook payload.
        _app_state: Injected app state (for testing). Falls back to main app.
    """
    action = payload.get("action", "")
    installation = payload.get("installation", {})
    installation_id = installation.get("id", 0)
    org_login = installation.get("account", {}).get("login", "")

    added = payload.get("repositories_added", [])
    removed = payload.get("repositories_removed", [])

    logger.info(
        "installation_repositories event: action=%s org=%s added=%d removed=%d",
        action,
        org_login,
        len(added),
        len(removed),
    )

    state = _app_state or _get_app_state()
    if state is None:
        logger.warning("Could not access app state for installation_repositories event")
        return

    search_index = getattr(state, "search_index", None)
    indexer = getattr(state, "indexer", None)
    embed_client = getattr(state, "embed_client", None)
    registry = getattr(state, "registry", None)

    # Remove indexed data for removed repos
    if search_index is not None:
        for repo_data in removed:
            full_name = repo_data.get("full_name", "")
            if full_name:
                try:
                    await search_index.delete_repo(full_name)
                    logger.info("Deleted indexed data for removed repo: %s", full_name)
                except Exception:
                    logger.warning("Failed to delete indexed data for %s", full_name, exc_info=True)

    # Schedule indexing for added repos
    if indexer is not None and search_index is not None and added:
        repos_to_index = [r.get("full_name", "") for r in added if r.get("full_name")]
        if repos_to_index:
            indexer.schedule_repos_index(
                installation_id=installation_id,
                org_login=org_login,
                repos=repos_to_index,
                client=client,
                search_index=search_index,
                embed_client=embed_client,
                registry=registry,
            )
            logger.info("Scheduled indexing for %d added repos", len(repos_to_index))

    # Schedule background onboarding for added repos
    if added:
        fire_and_forget(onboard_repos(client, added))
