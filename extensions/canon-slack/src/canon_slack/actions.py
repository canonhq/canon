"""Button and modal interaction handlers for Slack."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .permissions import Permission, resolve_permission

logger = logging.getLogger(__name__)


def _get_registry() -> Any:
    """Get the IdentityStore from app state for permission resolution."""
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


async def handle_approve(ack: Any, body: dict, client: Any) -> None:
    """Handle the 'Approve' button — update review_status in GitHub and post confirmation."""
    await ack()
    user_id = body["user"]["id"]
    spec_title = body["actions"][0]["value"]

    # Sanitize spec_title to prevent path traversal
    if ".." in spec_title or "/" in spec_title:
        await client.chat_postEphemeral(
            channel=body.get("channel", {}).get("id", ""),
            user=user_id,
            text=":x: Invalid spec name.",
        )
        return

    registry = _get_registry()
    perm = await resolve_permission(user_id, registry)

    if perm.value not in ("write", "admin"):
        await client.chat_postEphemeral(
            channel=body.get("channel", {}).get("id", ""),
            user=user_id,
            text=":lock: You don't have permission to approve specs (requires specs:write).",
        )
        return

    channel = body.get("channel", {}).get("id", "")
    ts = body.get("message", {}).get("ts", "")

    # Update review_status frontmatter in GitHub
    try:
        owner, repo = _get_repo_settings()
        gh = _get_github_client()
        spec_path = f"docs/specs/{spec_title}.md"
        raw_content, file_sha = await gh.get_file_content(owner, repo, spec_path)

        from canon.parser.writer import update_frontmatter_field

        updated = update_frontmatter_field(raw_content, "review_status", "approved")
        await gh.create_or_update_file(
            owner,
            repo,
            spec_path,
            updated,
            f"chore(specs): mark {spec_title} as approved via Slack",
            sha=file_sha,
        )
        await client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f":white_check_mark: *{spec_title}* approved by <@{user_id}> — `review_status` updated in GitHub.",
        )
    except Exception:
        logger.error("Failed to update review_status for %s", spec_title, exc_info=True)
        await client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f":warning: <@{user_id}> approved *{spec_title}* but the GitHub update failed — review_status was not changed. Check logs.",
        )


async def handle_request_changes_open(ack: Any, body: dict, client: Any) -> None:
    """Open the 'Request Changes' modal."""
    await ack()
    user_id = body["user"]["id"]
    spec_title = body["actions"][0]["value"]

    registry = _get_registry()
    perm = await resolve_permission(user_id, registry)

    if perm.value not in ("write", "admin"):
        await client.chat_postEphemeral(
            channel=body.get("channel", {}).get("id", ""),
            user=user_id,
            text=":lock: You don't have permission to request changes (requires specs:write).",
        )
        return

    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "request_changes_submit",
            "title": {"type": "plain_text", "text": "Request Changes"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Spec:* {spec_title}"},
                },
                {
                    "type": "input",
                    "block_id": "feedback_block",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "feedback_input",
                        "multiline": True,
                        "max_length": 3000,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Describe the changes needed...",
                        },
                    },
                    "label": {"type": "plain_text", "text": "Feedback"},
                },
            ],
            "private_metadata": json.dumps(
                {
                    "spec_title": spec_title,
                    "channel_id": body.get("channel", {}).get("id", ""),
                    "message_ts": body.get("message", {}).get("ts", ""),
                }
            ),
        },
    )


async def handle_request_changes_submit(ack: Any, view: dict, client: Any, body: dict) -> None:
    """Handle submission of the 'Request Changes' modal.

    Posts feedback as a threaded reply in the original channel, as a GitHub PR
    comment if a linked PR exists, and updates review_status in GitHub.
    """
    await ack()
    user_id = body.get("user", {}).get("id", "")

    registry = _get_registry()
    perm = await resolve_permission(user_id, registry)
    if perm.value not in ("write", "admin"):
        logger.warning("Permission denied for modal submit from user %s", user_id)
        try:
            dm = await client.conversations_open(users=[user_id])
            await client.chat_postMessage(
                channel=dm["channel"]["id"],
                text=":lock: You don't have permission to submit spec feedback (requires specs:write).",
            )
        except Exception:
            logger.warning("Could not DM permission-denied notice to %s", user_id)
        return

    raw_metadata = view.get("private_metadata", "{}")
    try:
        metadata = json.loads(raw_metadata)
    except (json.JSONDecodeError, TypeError):
        metadata = {"spec_title": raw_metadata, "channel_id": "", "message_ts": ""}
    spec_title = metadata.get("spec_title", "")
    channel_id = metadata.get("channel_id", "")
    message_ts = metadata.get("message_ts", "")

    # Sanitize spec_title to prevent path traversal
    if ".." in spec_title or "/" in spec_title:
        logger.warning("Rejected spec_title with path traversal chars: %s", spec_title[:50])
        return

    feedback = (
        view.get("state", {})
        .get("values", {})
        .get("feedback_block", {})
        .get("feedback_input", {})
        .get("value", "")
    )

    logger.info(
        "Review feedback for %s from %s: %s",
        spec_title,
        user_id,
        feedback[:100],
    )

    # Post feedback as a threaded reply in the original channel
    if channel_id:
        thread_text = f":pencil: <@{user_id}> requested changes on *{spec_title}*:\n>{feedback}"
        kwargs: dict[str, Any] = {"channel": channel_id, "text": thread_text}
        if message_ts:
            kwargs["thread_ts"] = message_ts
        await client.chat_postMessage(**kwargs)

    # Post feedback as a GitHub PR comment
    gh_posted = await _post_feedback_to_github(spec_title, feedback, user_id)

    # Update review_status in GitHub
    try:
        owner, repo = _get_repo_settings()
        gh = _get_github_client()
        spec_path = f"docs/specs/{spec_title}.md"
        raw_content, file_sha = await gh.get_file_content(owner, repo, spec_path)

        from canon.parser.writer import update_frontmatter_field

        updated = update_frontmatter_field(raw_content, "review_status", "changes_requested")
        await gh.create_or_update_file(
            owner,
            repo,
            spec_path,
            updated,
            f"chore(specs): mark {spec_title} as changes_requested via Slack",
            sha=file_sha,
        )
    except Exception:
        logger.error("Failed to update review_status for %s", spec_title, exc_info=True)

    # DM the user as confirmation
    try:
        dm = await client.conversations_open(users=[user_id])
        dm_channel = dm["channel"]["id"]
        if gh_posted is True:
            msg = f":pencil: Feedback for *{spec_title}* posted as a GitHub PR comment — review_status updated."
        elif gh_posted is None:
            msg = f":x: Failed to post feedback for *{spec_title}* to GitHub — please try again."
        else:
            msg = f":pencil: Feedback recorded for *{spec_title}* — review_status updated."
        await client.chat_postMessage(channel=dm_channel, text=msg)
    except Exception:
        logger.warning("Could not DM user %s after modal submit", user_id, exc_info=True)


async def _post_feedback_to_github(
    spec_title: str, feedback: str, slack_user_id: str
) -> bool | None:
    """Post review feedback as a comment on the spec's most recent PR.

    Returns True if posted, False if no linked PR found, None on error.
    """
    try:
        from canon.main import _get_client, settings

        gh = _get_client()
        owner, repo = settings.github_owner, settings.github_repo
        if not owner or not repo:
            return False

        # Find an open PR that touches the spec file via Search API (O(1) call)
        spec_slug = re.sub(r"[^a-z0-9]+", "-", spec_title.lower()).strip("-")
        spec_path = f"docs/specs/{spec_slug}.md"
        results = await gh._get(
            "/search/issues",
            q=f"repo:{owner}/{repo} is:pr is:open {spec_slug} in:title",
            per_page="5",
        )
        items = results.get("items", []) if isinstance(results, dict) else []

        # Verify the candidate PR actually touches the spec file
        target_pr = None
        for item in items:
            files = await gh.list_pull_files(owner, repo, item["number"])
            if any(f.get("filename", "") == spec_path for f in files):
                target_pr = item
                break

        if not target_pr:
            return False

        quoted = "\n".join(f"> {line}" for line in feedback.splitlines())
        comment_body = (
            f"**Spec Review Feedback** (via Slack)\n\n"
            f"**Spec:** {spec_title}\n"
            f"**From:** Slack user `{slack_user_id}`\n\n"
            f"{quoted}"
        )
        await gh.create_comment(owner, repo, target_pr["number"], comment_body)
        return True
    except Exception:
        logger.warning("Failed to post feedback to GitHub for %s", spec_title, exc_info=True)
        return None


async def handle_sync_tickets(ack: Any, body: dict, client: Any) -> None:
    """Handle the 'Sync Tickets' button — trigger forward sync for a spec."""
    await ack()
    user_id = body["user"]["id"]
    spec_title = body["actions"][0]["value"]

    registry = _get_registry()
    perm = await resolve_permission(user_id, registry)

    if perm != Permission.ADMIN:
        await client.chat_postEphemeral(
            channel=body.get("channel", {}).get("id", ""),
            user=user_id,
            text=":lock: You don't have permission to trigger sync (requires specs:admin).",
        )
        return

    # Sanitize spec_title to prevent path traversal
    if ".." in spec_title or "/" in spec_title:
        await client.chat_postEphemeral(
            channel=body.get("channel", {}).get("id", ""),
            user=user_id,
            text=":x: Invalid spec name.",
        )
        return

    channel = body.get("channel", {}).get("id", "")
    ts = body.get("message", {}).get("ts", "")

    # Post progress indicator
    await client.chat_postMessage(
        channel=channel,
        thread_ts=ts,
        text=f":arrows_counterclockwise: Syncing tickets for *{spec_title}*\u2026",
    )

    try:
        owner, repo = _get_repo_settings()
        gh = _get_github_client()
        spec_path = f"docs/specs/{spec_title}.md"
        raw_content, _ = await gh.get_file_content(owner, repo, spec_path)

        from canon.parser.parse import parse_spec

        doc = parse_spec(raw_content)

        from canon.sync.adapters.factory import create_adapter
        from canon.sync.engine import forward_sync

        adapter = create_adapter(ticket_project=spec_title)
        if adapter is None:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=ts,
                text=f":warning: No ticket adapter configured \u2014 cannot sync *{spec_title}*.",
            )
            return

        spec_url = f"https://github.com/{owner}/{repo}/blob/main/{spec_path}"
        _updated_md, result = await forward_sync(
            doc,
            adapter,
            spec_title,
            spec_url=spec_url,
        )
        created = len(result.created)
        updated = len(result.updated)
        await client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=(
                f":white_check_mark: Ticket sync complete for *{spec_title}*: "
                f"{created} created, {updated} updated."
            ),
        )
    except Exception:
        logger.error("Ticket sync failed for %s", spec_title, exc_info=True)
        await client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f":x: Ticket sync failed for *{spec_title}* \u2014 check logs for details.",
        )


async def handle_refresh(ack: Any, body: dict, client: Any) -> None:
    """Handle the 'Refresh' button — invalidate cache and update the dashboard message."""
    await ack()
    channel = body.get("channel", {}).get("id", "")
    message_ts = body.get("message", {}).get("ts", "")

    try:
        owner, repo = _get_repo_settings()
        gh = _get_github_client()

        from .commands import _get_spec_loader, invalidate_spec_cache
        from .dashboard import build_dashboard_blocks

        invalidate_spec_cache(owner, repo)
        loader = _get_spec_loader(gh, owner, repo)
        await loader.load()

        if loader.has_load_error:
            await client.chat_postEphemeral(
                channel=channel,
                user=body["user"]["id"],
                text=f":warning: Failed to refresh: {loader.load_error}",
            )
            return

        stats = loader.coverage_stats()
        blocks = build_dashboard_blocks(loader.specs, stats)

        await client.chat_update(
            channel=channel,
            ts=message_ts,
            blocks=blocks,
            text="Spec Dashboard (refreshed)",
        )
    except Exception:
        logger.error("Dashboard refresh failed", exc_info=True)
        await client.chat_postEphemeral(
            channel=channel,
            user=body["user"]["id"],
            text=":x: Dashboard refresh failed \u2014 check logs.",
        )
