"""App Home Tab handler for Slack — personal dashboard."""

from __future__ import annotations

import logging
from typing import Any

from .telemetry import EVENT_HOME_TAB_OPENED, SuperProperties, track_slack

logger = logging.getLogger(__name__)


def _get_identity_store():
    """Get the IdentityStore from app state."""
    try:
        from canon.main import app

        return getattr(app.state, "identity_store", None)
    except Exception:
        return None


def _get_repo_settings() -> tuple[str, str]:
    """Get owner/repo from settings."""
    from canon.main import settings

    return settings.github_owner, settings.github_repo


def _get_github_client() -> object:
    """Get the GitHubClient singleton from main."""
    from canon.main import _get_client

    return _get_client()


def _build_onboarding_blocks() -> list[dict]:
    """Build the onboarding Home Tab for users without a linked GitHub identity."""
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "Welcome to Canon"}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":wave: Link your GitHub account to get a personalized dashboard "
                    "with your specs, team coverage, and activity.\n\n"
                    "Use `/canon link <github-username>` to get started."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Link GitHub Account"},
                    "action_id": "home_link_github",
                    "value": "link",
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Quick Commands:*\n"
                    "- `/canon list` — List all specs\n"
                    "- `/canon search <query>` — Search specs\n"
                    "- `/canon coverage` — View coverage metrics\n"
                    "- `/canon help` — See all commands"
                ),
            },
        },
    ]


def _build_dashboard_blocks(
    user_specs: list,
    team: str,
    team_stats: dict,
    recent_activity: list[str],
) -> list[dict]:
    """Build the personalized Home Tab dashboard."""
    from .blocks import progress_bar, status_emoji

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Canon Dashboard"}},
    ]

    # My Specs section
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*My Specs*"}})
    if user_specs:
        lines = []
        for spec in user_specs[:10]:
            emoji = status_emoji(spec.status)
            bar = progress_bar(spec.sections_done, spec.sections_total)
            lines.append(f"{emoji} *{spec.title}* — {spec.status}\n      {bar}")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
    else:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_No specs owned by you yet._"},
            }
        )

    blocks.append({"type": "divider"})

    # Team Coverage section
    if team:
        total = team_stats.get("total", 0)
        done = team_stats.get("done", 0)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Team Coverage ({team})*\n{progress_bar(done, total)}",
                },
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Team Coverage*\n_Set `team` in your specs to see team metrics._",
                },
            }
        )

    blocks.append({"type": "divider"})

    # Recent Activity section
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Recent Activity*"}})
    if recent_activity:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(recent_activity[:10])},
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_No recent activity._"},
            }
        )

    blocks.append({"type": "divider"})

    # Quick Actions
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "List Specs"},
                    "action_id": "home_list_specs",
                    "value": "list",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Dashboard"},
                    "action_id": "home_view_dashboard",
                    "value": "dashboard",
                },
            ],
        }
    )

    return blocks


async def handle_app_home_opened(event: dict, client: Any) -> None:
    """Handle app_home_opened event — publish personalized Home Tab."""
    user_id = event["user"]
    workspace_id = event.get("team", "")

    identity_store = _get_identity_store()
    github_username = None
    if identity_store:
        github_username = await identity_store.get_github_login(user_id)

    if not github_username:
        blocks = _build_onboarding_blocks()
        await client.views_publish(
            user_id=user_id,
            view={"type": "home", "blocks": blocks},
        )
        track_slack(
            EVENT_HOME_TAB_OPENED,
            SuperProperties(
                slack_workspace_id=workspace_id,
                org_id="unknown",
                extension_version="0.1.0",
            ),
            {"is_linked": False, "owned_specs_count": 0},
            distinct_id=user_id,
        )
        return

    # Load specs and build personalized dashboard
    owned_specs_count = 0
    try:
        owner, repo = _get_repo_settings()
        gh = _get_github_client()

        from .commands import _get_spec_loader

        loader = _get_spec_loader(gh, owner, repo)
        specs = await loader.load()

        # Filter specs owned by this user
        user_specs = [s for s in specs if s.owner == github_username]
        owned_specs_count = len(user_specs)

        # Determine team from user's specs
        teams = {s.team for s in user_specs if s.team}
        team = next(iter(teams), "")
        team_stats = loader.coverage_stats(team=team) if team else {}

        # Recent activity from notification dispatcher
        recent_activity: list[str] = []
        try:
            from canon.main import app as _app

            activity_store = getattr(_app.state, "activity_store", None)
            if activity_store:
                entries = activity_store.recent(user_id, limit=10)
                recent_activity = [f"- {e.text}" for e in entries]
        except Exception:
            pass

        blocks = _build_dashboard_blocks(user_specs, team, team_stats, recent_activity)
    except Exception:
        logger.error("Failed to build Home Tab for %s", user_id, exc_info=True)
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "Canon Dashboard"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":warning: Failed to load dashboard — please try again.",
                },
            },
        ]

    await client.views_publish(
        user_id=user_id,
        view={"type": "home", "blocks": blocks},
    )
    track_slack(
        EVENT_HOME_TAB_OPENED,
        SuperProperties(
            slack_workspace_id=workspace_id,
            org_id="unknown",
            extension_version="0.1.0",
        ),
        {"is_linked": True, "owned_specs_count": owned_specs_count},
        distinct_id=user_id,
    )
