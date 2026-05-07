"""Build the <personal_context> block for DM-only Claude prompts."""

from __future__ import annotations

import logging
from typing import Any

from canon_slack.work_context.models import PersonalContext

logger = logging.getLogger(__name__)


async def build_personal_context(
    identity_store: Any,
    spec_loader: Any,
    user_id: str,
    org_id: str,
) -> PersonalContext | None:
    """Assemble personal context for a DM, or return None if the user is unlinked.

    Read-only — issues identity-store and spec-loader reads but does not write
    state or send Slack messages. The caller is responsible for the
    one-time-prompt flow when this returns None.
    """
    try:
        github_login = await identity_store.get_github_login(user_id)
    except Exception:
        logger.debug("get_github_login failed", exc_info=True)
        github_login = None

    if not github_login:
        return None

    team: str | None = None
    try:
        team = await identity_store.get_team(user_id)
    except Exception:
        logger.debug("get_team failed", exc_info=True)

    owned: list[tuple[str, str]] = []
    try:
        await spec_loader.load()
        owned_specs = spec_loader.specs_owned_by(github_login)
        owned = [(s.slug, s.status) for s in owned_specs]
    except Exception:
        logger.warning(
            "build_personal_context: spec loader failed for %s",
            github_login,
            exc_info=True,
        )

    return PersonalContext(github_login=github_login, team=team, owned_specs=owned)
