"""Telemetry constants and helpers for the canon-slack extension."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from canon import analytics

logger = logging.getLogger(__name__)


# §10 Slack events
EVENT_COMMAND_INVOKED = "slack_command_invoked"
EVENT_MENTION_HANDLED = "slack_mention_handled"
EVENT_ACTION_CLICKED = "slack_action_clicked"
EVENT_HOME_TAB_OPENED = "slack_home_tab_opened"
EVENT_SPEC_CREATED = "slack_spec_created"
EVENT_NOTIFICATION_DISPATCHED = "slack_notification_dispatched"
EVENT_IDENTITY_LINKED = "slack_identity_linked"
EVENT_DIGEST_SENT = "slack_digest_sent"

# Sub-project A work-context events
EVENT_INTENT_CLASSIFIED = "work_context_intent_classified"
EVENT_SOURCE_FETCHED = "work_context_source_fetched"
EVENT_WORK_CONTEXT_ASSEMBLED = "work_context_assembled"


@dataclass(frozen=True)
class SuperProperties:
    """Common props attached to every Slack event."""

    slack_workspace_id: str
    org_id: str
    extension_version: str


def track_slack(
    event: str,
    super_props: SuperProperties,
    properties: dict[str, Any],
    *,
    distinct_id: str,
    groups: dict[str, str] | None = None,
) -> None:
    """Capture a Slack telemetry event. Best-effort — swallows failures.

    Per design spec §10.2: 'All track() calls wrapped to never block the
    user-facing operation.'

    Caller *properties* take priority over super-prop fields if keys collide
    (intentional — allows local overrides). analytics.track will additionally
    apply server-level _super_properties underneath, so the effective property
    priority is: server super-props < SuperProperties < caller properties.
    """
    merged: dict[str, Any] = {
        "slack_workspace_id": super_props.slack_workspace_id,
        "org_id": super_props.org_id,
        "extension_version": super_props.extension_version,
        **properties,
    }
    try:
        analytics.track(event, distinct_id=distinct_id, properties=merged, groups=groups)
    except Exception:
        logger.debug("track_slack failed for event %s", event, exc_info=True)
