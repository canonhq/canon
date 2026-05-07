"""Handler for the /canon new spec creation modal submission."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from .telemetry import EVENT_SPEC_CREATED, SuperProperties, track_slack

logger = logging.getLogger(__name__)

_SPEC_TEMPLATE = """\
---
title: "{title}"
type: {spec_type}
status: draft
owner: "{owner}"
team: "{team}"
review_status: draft
tags: []
depends_on: []
created: "{created}"
updated: "{created}"
---

# {title}

## 1. Background

{background}

## 2. Requirements

### Acceptance Criteria

- [ ] First requirement

## 3. Design

Describe the technical approach.

## 4. Rollout Plan

Describe phased rollout and success criteria.
"""


def _slugify(title: str) -> str:
    """Convert a title to a kebab-case slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


async def handle_new_spec_submit(ack: Any, view: dict, client: Any, body: dict) -> None:
    """Handle submission of the 'Create New Spec' modal."""
    await ack()
    values = view.get("state", {}).get("values", {})

    title = values.get("title_block", {}).get("title_input", {}).get("value", "").strip()
    spec_type = (
        values.get("type_block", {})
        .get("type_select", {})
        .get("selected_option", {})
        .get("value", "spec")
    )
    team = (
        values.get("team_block", {})
        .get("team_select", {})
        .get("selected_option", {})
        .get("value", "")
    )
    background = (
        values.get("background_block", {}).get("background_input", {}).get("value", "")
        or "Describe the context and motivation for this spec."
    )

    user_id = body.get("user", {}).get("id", "")
    slug = _slugify(title)
    if not slug:
        slug = "untitled-spec"

    # Resolve GitHub username for owner field
    owner = ""
    try:
        from canon.main import app

        identity_store = getattr(app.state, "identity_store", None)
        if identity_store:
            owner = await identity_store.get_github_login(user_id) or ""
    except Exception:
        pass

    now = datetime.now(UTC).strftime("%Y-%m-%d")

    # Escape curly braces in user-supplied fields to prevent str.format() crashes
    def _safe(val: str) -> str:
        return val.replace("{", "{{").replace("}", "}}")

    content = _SPEC_TEMPLATE.format(
        title=_safe(title or slug),
        spec_type=spec_type,
        owner=_safe(owner),
        team=_safe(team),
        background=_safe(background),
        created=now,
    )

    # Commit to GitHub
    try:
        from canon.main import _get_client, settings

        gh = _get_client()
        repo_owner = settings.github_owner
        repo = settings.github_repo
        spec_path = f"docs/specs/{slug}.md"

        await gh.create_or_update_file(
            repo_owner,
            repo,
            spec_path,
            content,
            f"docs(specs): create {slug} spec via Slack",
        )

        github_url = f"https://github.com/{repo_owner}/{repo}/blob/main/{spec_path}"

        # DM the user with a confirmation
        dm = await client.conversations_open(users=[user_id])
        dm_channel = dm["channel"]["id"]
        await client.chat_postMessage(
            channel=dm_channel,
            text=(
                f":sparkles: Created spec *{title or slug}* ({spec_type})\n"
                f"<{github_url}|View on GitHub>"
            ),
        )
        track_slack(
            EVENT_SPEC_CREATED,
            SuperProperties(
                slack_workspace_id=body.get("team", {}).get("id", ""),
                org_id="unknown",
                extension_version="0.1.0",
            ),
            {"team": team, "type": spec_type},
            distinct_id=user_id,
        )
    except Exception:
        logger.error("Failed to create spec %s via Slack", slug, exc_info=True)
        try:
            dm = await client.conversations_open(users=[user_id])
            dm_channel = dm["channel"]["id"]
            await client.chat_postMessage(
                channel=dm_channel,
                text=f":x: Failed to create spec *{title or slug}* — check logs.",
            )
        except Exception:
            logger.warning(
                "Could not DM user %s after spec creation failure", user_id, exc_info=True
            )
