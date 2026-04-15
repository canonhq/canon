"""Handle issues events — real-time reverse sync via ticket webhook processor."""

from __future__ import annotations

import logging

from canon.github.client import GitHubClient
from canon.webhooks.processor import TicketEvent, process_ticket_event

logger = logging.getLogger(__name__)


async def on_issues(client: GitHubClient, payload: dict) -> None:
    """Handle a GitHub issues event and trigger reverse sync.

    Processes opened, closed, labeled, unlabeled, and reopened events
    to keep spec statuses in sync with GitHub Issues in real time.
    """
    action = payload.get("action", "")
    if action not in ("opened", "closed", "labeled", "unlabeled", "reopened"):
        logger.debug("Ignoring issues event action=%s", action)
        return

    issue = payload.get("issue", {})
    repo_data = payload.get("repository", {})
    issue_number = str(issue.get("number", ""))
    issue_state = issue.get("state", "open")
    labels = [lb.get("name", "") for lb in issue.get("labels", [])]
    owner = repo_data.get("owner", {}).get("login", "")
    repo_name = repo_data.get("name", "")

    if not issue_number or not owner or not repo_name:
        logger.warning(
            "Issues event missing required data: issue=%s owner=%s repo=%s",
            issue_number,
            owner,
            repo_name,
        )
        return

    # raw_status is set for consistency but not used for GitHub events —
    # _resolve_new_state dispatches on github_state + github_labels instead.
    event = TicketEvent(
        system="github",
        ticket_id=issue_number,
        raw_status=issue_state,
        github_state=issue_state,
        github_labels=labels,
        owner=owner,
        repo=repo_name,
    )

    result = await process_ticket_event(client, event)

    if result.processed and result.old_state != result.new_state:
        logger.info(
            "Reverse sync: issue #%s in %s/%s → %s (was %s)",
            issue_number,
            owner,
            repo_name,
            result.new_state,
            result.old_state,
        )
    elif result.error:
        logger.warning(
            "Reverse sync failed for issue #%s in %s/%s: %s",
            issue_number,
            owner,
            repo_name,
            result.error,
        )
