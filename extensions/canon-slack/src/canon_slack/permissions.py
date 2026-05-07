"""Slack user ID -> Canon permission mapping."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Permission(Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


async def _check_collaborator_permission(github_login: str) -> Permission:
    """Check GitHub repo collaborator permission for a linked user.

    Returns ADMIN/WRITE if the user is a repo collaborator, READ otherwise.
    Falls back to READ on any error (fail closed).
    """
    try:
        from canon.main import _get_client, settings

        gh = _get_client()
        owner, repo = settings.github_owner, settings.github_repo
        if not owner or not repo:
            return Permission.READ

        perm = await gh.get_collaborator_permission(owner, repo, github_login)
        if perm in ("admin", "maintain"):
            return Permission.ADMIN
        if perm in ("write", "push"):
            return Permission.WRITE
        return Permission.READ
    except Exception:
        logger.warning(
            "Collaborator check failed for %s — defaulting to READ",
            github_login,
            exc_info=True,
        )
        return Permission.READ


async def resolve_permission(slack_user_id: str, registry: Any) -> Permission:
    """Map a Slack user to their Canon permission level.

    Checks the installation registry for a linked GitHub identity.
    Falls back to READ if no mapping exists.
    """
    if registry is None:
        return Permission.READ

    try:
        from .identity_store import IdentityStore

        # IdentityStore uses get_github_login; legacy registry uses get_github_login_for_slack
        if isinstance(registry, IdentityStore):
            github_login = await registry.get_github_login(slack_user_id)
            if not github_login:
                return Permission.READ
            # Verify repo collaborator status before granting WRITE
            return await _check_collaborator_permission(github_login)

        github_login = await registry.get_github_login_for_slack(slack_user_id)
        if not github_login:
            return Permission.READ

        role = await registry.get_user_role(github_login)
        if role == "admin":
            return Permission.ADMIN
        return Permission.WRITE
    except Exception:
        logger.warning(
            "Permission lookup failed for Slack user %s",
            slack_user_id,
            exc_info=True,
        )
        return Permission.READ
