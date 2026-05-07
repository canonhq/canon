"""Shared Block Kit builder utilities for Slack messages."""

from __future__ import annotations

_STATUS_EMOJI = {
    "done": ":white_check_mark:",
    "approved": ":white_check_mark:",
    "in_progress": ":large_blue_circle:",
    "active": ":large_blue_circle:",
    "review": ":mag:",
    "todo": ":yellow_circle:",
    "draft": ":yellow_circle:",
    "blocked": ":red_circle:",
    "stale": ":warning:",
}


def status_emoji(status: str) -> str:
    """Return a Slack emoji for a spec/section status."""
    return _STATUS_EMOJI.get(status, ":white_circle:")


def progress_bar(done: int, total: int, width: int = 10) -> str:
    """Build a text progress bar: [########--] 80% (8/10)."""
    pct = 0 if total == 0 else round(done / total * 100)
    filled = round(pct / 100 * width)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {pct}% ({done}/{total})"


def header_block(text: str) -> dict:
    """Build a Slack header block."""
    return {
        "type": "header",
        "text": {"type": "plain_text", "text": text[:150]},
    }


def section_block(text: str, accessory: dict | None = None) -> dict:
    """Build a Slack section block with mrkdwn text."""
    block: dict = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text[:3000]},
    }
    if accessory:
        block["accessory"] = accessory
    return block


def context_block(elements: list[str]) -> dict:
    """Build a Slack context block with mrkdwn elements."""
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": e[:3000]} for e in elements],
    }


def divider() -> dict:
    """Build a Slack divider block."""
    return {"type": "divider"}


def action_buttons(buttons: list[tuple[str, str, str]]) -> dict:
    """Build an actions block with buttons.

    Each button is (label, action_id, value).
    If value looks like a URL (starts with http), the button opens it as a link.
    """
    elements = []
    for label, action_id, value in buttons:
        btn: dict = {
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "action_id": action_id,
            "value": value,
        }
        if value.startswith("http"):
            btn["url"] = value
        elements.append(btn)
    return {"type": "actions", "elements": elements}


def spec_summary_blocks(
    title: str,
    status: str,
    sections_done: int,
    sections_total: int,
    github_url: str = "",
    updated: str = "",
) -> list[dict]:
    """Build summary blocks for a single spec."""
    emoji = status_emoji(status)
    bar = progress_bar(sections_done, sections_total)
    text = f"{emoji} *{title}* — {status}\n{bar}"
    blocks: list[dict] = [section_block(text)]

    ctx_parts = []
    if updated:
        ctx_parts.append(f"Updated: {updated}")
    if github_url:
        ctx_parts.append(f"<{github_url}|View on GitHub>")
    if ctx_parts:
        blocks.append(context_block(ctx_parts))

    return blocks
