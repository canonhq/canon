"""Bolt AsyncApp factory and FastAPI ASGI mount."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp

from canon.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class SlackBot:
    """Container for the Bolt app and its ASGI handler."""

    app: AsyncApp
    handler: AsyncSlackRequestHandler
    socket_mode: bool = False


def create_slack_app(settings: Settings) -> SlackBot | None:
    """Create the Slack Bolt app. Returns None if not configured."""
    if not settings.slack_bot_enabled:
        return None

    bolt_app = AsyncApp(
        token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
    )

    # Register handlers
    from .actions import (
        handle_approve,
        handle_refresh,
        handle_request_changes_open,
        handle_request_changes_submit,
        handle_sync_tickets,
    )
    from .commands import handle_canon_command
    from .home_tab import handle_app_home_opened
    from .mentions import handle_dm, handle_mention
    from .new_spec import handle_new_spec_submit

    bolt_app.command("/canon")(handle_canon_command)
    bolt_app.event("app_mention")(handle_mention)
    bolt_app.event("message")(handle_dm)  # Filtered by channel_type in handle_dm
    bolt_app.action("approve_spec")(handle_approve)
    bolt_app.action("request_changes")(handle_request_changes_open)
    bolt_app.view("request_changes_submit")(handle_request_changes_submit)
    bolt_app.action("sync_tickets")(handle_sync_tickets)
    bolt_app.action("dashboard_refresh")(handle_refresh)
    bolt_app.event("app_home_opened")(handle_app_home_opened)
    bolt_app.view("new_spec_submit")(handle_new_spec_submit)

    handler = AsyncSlackRequestHandler(bolt_app)
    use_socket_mode = bool(settings.slack_app_token)

    bot = SlackBot(
        app=bolt_app,
        handler=handler,
        socket_mode=use_socket_mode,
    )

    logger.info(
        "Slack bot created (mode=%s)",
        "socket" if use_socket_mode else "http",
    )
    return bot
