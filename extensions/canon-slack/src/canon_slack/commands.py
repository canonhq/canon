"""Slash command handlers for /canon."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from .blocks import (
    action_buttons,
    context_block,
    divider,
    header_block,
    progress_bar,
    section_block,
    spec_summary_blocks,
    status_emoji,
)
from .dashboard import build_dashboard_blocks
from .spec_loader import SpecLoader
from .telemetry import EVENT_COMMAND_INVOKED, EVENT_IDENTITY_LINKED, SuperProperties, track_slack

logger = logging.getLogger(__name__)

COMMANDS = {
    "status": "Show spec status and progress",
    "list": "List specs, optionally filtered by status",
    "search": "Search specs by keyword",
    "coverage": "Show spec coverage metrics",
    "dashboard": "Post coverage dashboard to channel",
    "digest": "Preview team digest, optionally for a specific team",
    "review": "Request a spec review",
    "new": "Create a new spec from a modal",
    "mute": "Mute notifications for a spec",
    "unmute": "Unmute notifications for a spec",
    "link": "Link your Slack account to GitHub",
    "unlink": "Unlink your GitHub account",
    "help": "Show available commands",
}

# Module-level cache for SpecLoader instances keyed by (owner, repo)
_loaders: dict[tuple[str, str], SpecLoader] = {}


def _get_spec_loader(github_client: object, owner: str, repo: str) -> SpecLoader:
    """Get or create a cached SpecLoader for the given repo."""
    key = (owner, repo)
    if key not in _loaders:
        _loaders[key] = SpecLoader(github_client=github_client, owner=owner, repo=repo)
    return _loaders[key]


def invalidate_spec_cache(owner: str, repo: str) -> None:
    """Invalidate the cached SpecLoader for a repo (call on push events)."""
    key = (owner, repo)
    if key in _loaders:
        _loaders[key].invalidate()
        logger.info("Invalidated Slack spec cache for %s/%s", owner, repo)


def _get_repo_settings() -> tuple[str, str]:
    """Get owner/repo from settings."""
    from canon.main import settings

    return settings.github_owner, settings.github_repo


def _get_github_client() -> object:
    """Get the GitHubClient singleton from main."""
    from canon.main import _get_client

    return _get_client()


_interest_tracker_instance = None


def _track_interest(user_id: str, spec_slug: str) -> str | None:
    """Record a spec query for auto-follow suggestions. Returns slug if threshold crossed."""
    global _interest_tracker_instance
    if _interest_tracker_instance is None:
        try:
            from .interest_tracker import InterestTracker

            _interest_tracker_instance = InterestTracker()
        except Exception:
            return None
    return _interest_tracker_instance.record_query(user_id, spec_slug)


async def _load_specs(respond: Any) -> tuple[SpecLoader, bool]:
    """Load specs, sending an error message if it fails.

    Returns (loader, success).
    """
    owner, repo = _get_repo_settings()
    if not owner or not repo:
        await respond(
            blocks=[
                section_block(
                    ":warning: GitHub owner/repo not configured. "
                    "Set `GITHUB_OWNER` and `GITHUB_REPO` environment variables."
                )
            ],
            response_type="ephemeral",
        )
        return SpecLoader(object(), "", ""), False

    client = _get_github_client()
    loader = _get_spec_loader(client, owner, repo)
    await loader.load()

    if loader.has_load_error:
        await respond(
            blocks=[
                section_block(
                    f":x: Failed to load specs: {loader.load_error}\n"
                    "Try again or check the GitHub configuration."
                )
            ],
            response_type="ephemeral",
        )
        return loader, False

    return loader, True


def parse_command(text: str) -> tuple[str, str]:
    """Parse '/canon <subcommand> [args]' into (subcommand, args)."""
    text = text.strip()
    if not text:
        return "help", ""
    parts = text.split(None, 1)
    subcommand = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return subcommand, args


async def help_handler(ack: Any, respond: Any) -> None:
    """List all available /canon subcommands."""
    await ack()
    lines = [f"`/canon {cmd}` — {desc}" for cmd, desc in COMMANDS.items()]
    blocks = [
        header_block("Canon Commands"),
        section_block("\n".join(lines)),
    ]
    await respond(blocks=blocks, response_type="ephemeral")


async def unknown_handler(ack: Any, respond: Any, subcommand: str) -> None:
    """Handle unknown subcommands with a hint."""
    await ack()
    blocks = [
        section_block(
            f":warning: Unknown command `{subcommand}`.\n"
            f"Run `/canon help` to see available commands."
        ),
    ]
    await respond(
        blocks=blocks,
        response_type="ephemeral",
        text=f"Unknown command: {subcommand}",
    )


async def handle_canon_command(ack: Any, command: dict, respond: Any, client: Any) -> None:
    """Main /canon command dispatcher."""
    text = command.get("text", "")
    subcommand, args = parse_command(text)

    super_props = SuperProperties(
        slack_workspace_id=command.get("team_id", ""),
        org_id="unknown",
        extension_version="0.1.0",
    )
    start = time.monotonic()
    success = False

    try:
        if subcommand == "help":
            await help_handler(ack, respond)
        elif subcommand == "status":
            await status_handler(ack, respond, client, args, command)
        elif subcommand == "list":
            await list_handler(ack, respond, client, args, command)
        elif subcommand == "search":
            await search_handler(ack, respond, client, args, command)
        elif subcommand == "coverage":
            await coverage_handler(ack, respond, client, args, command)
        elif subcommand == "dashboard":
            await dashboard_handler(ack, respond, client, args, command)
        elif subcommand == "digest":
            await digest_handler(ack, respond, client, args, command)
        elif subcommand == "review":
            await review_handler(ack, respond, client, args, command)
        elif subcommand == "new":
            await new_spec_handler(ack, respond, client, args, command)
        elif subcommand == "mute":
            await mute_handler(ack, respond, args, command)
        elif subcommand == "unmute":
            await unmute_handler(ack, respond, args, command)
        elif subcommand == "link":
            await link_handler(ack, respond, args, command)
        elif subcommand == "unlink":
            await unlink_handler(ack, respond, command)
        else:
            await unknown_handler(ack, respond, subcommand)
        success = True
    except Exception:
        logger.exception("Unhandled error in /canon %s", subcommand)
        try:
            await respond(
                blocks=[
                    section_block(
                        f":x: Something went wrong processing `/canon {subcommand}`. "
                        "Please try again or contact an administrator."
                    )
                ],
                response_type="ephemeral",
            )
        except Exception:
            logger.error("Failed to send error response to Slack", exc_info=True)
    finally:
        track_slack(
            EVENT_COMMAND_INVOKED,
            super_props,
            {
                "subcommand": subcommand,
                "channel_type": command.get("channel_name", ""),
                "success": success,
                "duration_ms": int((time.monotonic() - start) * 1000),
            },
            distinct_id=command.get("user_id", "unknown"),
        )


async def status_handler(ack: Any, respond: Any, client: Any, args: str, command: dict) -> None:
    """Show spec status and AC progress."""
    await ack()

    slug = args.strip()
    if not slug:
        await respond(
            blocks=[section_block("Usage: `/canon status <spec-name>`")],
            response_type="ephemeral",
        )
        return

    loader, ok = await _load_specs(respond)
    if not ok:
        return

    spec = loader.get_by_slug(slug)
    if spec is None:
        suggestions = loader.suggest_similar(slug)
        if suggestions:
            hint = ", ".join(f"`{s}`" for s in suggestions)
            msg = f":mag: Spec `{slug}` not found. Did you mean: {hint}?"
        else:
            msg = f":mag: Spec `{slug}` not found."
        await respond(
            blocks=[section_block(msg)],
            response_type="ephemeral",
        )
        return

    # Track interest for auto-follow suggestions
    user_id = command.get("user_id", "")
    follow_suggestion = _track_interest(user_id, slug)

    # Build status response
    blocks: list[dict] = []
    emoji = status_emoji(spec.status)
    bar = progress_bar(spec.sections_done, spec.sections_total)
    blocks.append(header_block(spec.title))
    blocks.append(section_block(f"{emoji} *Status:* {spec.status}\n*Progress:* {bar}"))

    if spec.owner:
        ctx_parts = [f"Owner: {spec.owner}"]
        if spec.team:
            ctx_parts.append(f"Team: {spec.team}")
        if spec.github_url:
            ctx_parts.append(f"<{spec.github_url}|View on GitHub>")
        blocks.append(context_block(ctx_parts))

    # Per-section breakdown
    if spec.sections:
        blocks.append(divider())
        blocks.append(section_block("*Sections:*"))
        for sec in spec.sections:
            sec_emoji = status_emoji(sec.status)
            ac_text = ""
            if sec.acs_total > 0:
                ac_text = f" — {sec.acs_done}/{sec.acs_total} ACs"
            blocks.append(section_block(f"{sec_emoji} {sec.title} _{sec.status}_{ac_text}"))

    if follow_suggestion:
        blocks.append(divider())
        blocks.append(
            section_block(
                f":bell: You've checked *{slug}* several times. "
                f"Consider using `/canon mute` or `/canon unmute` to manage notifications for it."
            )
        )

    await respond(blocks=blocks, response_type="ephemeral")


async def list_handler(ack: Any, respond: Any, client: Any, args: str, command: dict) -> None:
    """List specs with optional status filter."""
    await ack()

    # Parse --status flag
    status_filter = ""
    args_stripped = args.strip()
    if args_stripped.startswith("--status"):
        parts = args_stripped.split(None, 1)
        if len(parts) > 1:
            status_filter = parts[1].strip()

    loader, ok = await _load_specs(respond)
    if not ok:
        return

    if status_filter:
        specs = loader.filter_by_status(status_filter)
        title = f"Specs — {status_filter}"
    else:
        specs = loader.specs
        title = "All Specs"

    if not specs:
        msg = ":mag: No specs found" + (
            f" with status `{status_filter}`." if status_filter else "."
        )
        await respond(
            blocks=[section_block(msg)],
            response_type="ephemeral",
        )
        return

    blocks: list[dict] = [header_block(title)]
    display_limit = 10
    for spec in specs[:display_limit]:
        blocks.extend(
            spec_summary_blocks(
                title=spec.title,
                status=spec.status,
                sections_done=spec.sections_done,
                sections_total=spec.sections_total,
                github_url=spec.github_url,
                updated=spec.updated,
            )
        )
        blocks.append(divider())

    if len(specs) > display_limit:
        blocks.append(context_block([f"_Showing {display_limit} of {len(specs)} specs._"]))

    await respond(blocks=blocks, response_type="ephemeral")


async def search_handler(ack: Any, respond: Any, client: Any, args: str, command: dict) -> None:
    """Search specs by keyword."""
    await ack()

    query = args.strip()
    if not query:
        await respond(
            blocks=[section_block("Usage: `/canon search <query>`")],
            response_type="ephemeral",
        )
        return

    loader, ok = await _load_specs(respond)
    if not ok:
        return

    results = loader.search(query)
    if not results:
        await respond(
            blocks=[section_block(f":mag: No specs matching `{query}`.")],
            response_type="ephemeral",
        )
        return

    blocks: list[dict] = [
        header_block(f"Search: {query}"),
        context_block([f"_{len(results)} result{'s' if len(results) != 1 else ''}_"]),
    ]
    for spec in results[:10]:
        blocks.extend(
            spec_summary_blocks(
                title=spec.title,
                status=spec.status,
                sections_done=spec.sections_done,
                sections_total=spec.sections_total,
                github_url=spec.github_url,
            )
        )
        blocks.append(divider())

    await respond(blocks=blocks, response_type="ephemeral")


async def coverage_handler(ack: Any, respond: Any, client: Any, args: str, command: dict) -> None:
    """Show coverage metrics."""
    await ack()

    # Parse --team flag
    team_filter = ""
    args_stripped = args.strip()
    if args_stripped.startswith("--team"):
        parts = args_stripped.split(None, 1)
        if len(parts) > 1:
            team_filter = parts[1].strip()

    loader, ok = await _load_specs(respond)
    if not ok:
        return

    stats = loader.coverage_stats(team=team_filter)

    title = "Spec Coverage"
    if team_filter:
        title += f" — {team_filter}"

    bar = progress_bar(stats["done"], stats["total"])
    blocks: list[dict] = [
        header_block(title),
        section_block(f"*Overall:* {bar}"),
        section_block(
            f":white_check_mark: Done: *{stats['done']}*\n"
            f":large_blue_circle: In Progress: *{stats['in_progress']}*\n"
            f":yellow_circle: Other: *{stats['total'] - stats['done'] - stats['in_progress']}*"
        ),
    ]

    if stats["teams"] and not team_filter:
        blocks.append(divider())
        blocks.append(section_block("*By Team:*"))
        for team in stats["teams"]:
            team_stats = loader.coverage_stats(team=team)
            team_bar = progress_bar(team_stats["done"], team_stats["total"])
            blocks.append(section_block(f"{team}  {team_bar}"))

    await respond(blocks=blocks, response_type="ephemeral")


async def dashboard_handler(ack: Any, respond: Any, client: Any, args: str, command: dict) -> None:
    """Post coverage dashboard to channel."""
    await ack()

    loader, ok = await _load_specs(respond)
    if not ok:
        return

    stats = loader.coverage_stats()
    blocks = build_dashboard_blocks(loader.specs, stats)
    await respond(blocks=blocks, response_type="in_channel")


async def digest_handler(ack: Any, respond: Any, client: Any, args: str, command: dict) -> None:
    """Preview a team digest (ephemeral)."""
    await ack()

    loader, ok = await _load_specs(respond)
    if not ok:
        return

    team_filter = args.strip()

    stats = loader.coverage_stats(team=team_filter)

    teams = [team_filter] if team_filter else stats.get("teams", [])

    if not teams:
        await respond(
            blocks=[section_block(":mag: No teams found in specs.")],
            response_type="ephemeral",
        )
        return

    from .digest import build_digest_blocks

    all_blocks: list[dict] = []
    for team in teams[:5]:
        team_stats = loader.coverage_stats(team=team)
        team_blocks = build_digest_blocks(
            team=team,
            specs=loader.specs,
            coverage_pct=team_stats["pct_done"],
            coverage_delta=0,
        )
        all_blocks.extend(team_blocks)
        all_blocks.append(divider())

    await respond(blocks=all_blocks, response_type="ephemeral")


async def review_handler(ack: Any, respond: Any, client: Any, args: str, command: dict) -> None:
    """Request a spec review."""
    await ack()

    slug = args.strip()
    if not slug:
        await respond(
            blocks=[section_block("Usage: `/canon review <spec-name>`")],
            response_type="ephemeral",
        )
        return

    loader, ok = await _load_specs(respond)
    if not ok:
        return

    spec = loader.get_by_slug(slug)
    if spec is None:
        suggestions = loader.suggest_similar(slug)
        if suggestions:
            hint = ", ".join(f"`{s}`" for s in suggestions)
            msg = f":mag: Spec `{slug}` not found. Did you mean: {hint}?"
        else:
            msg = f":mag: Spec `{slug}` not found."
        await respond(
            blocks=[section_block(msg)],
            response_type="ephemeral",
        )
        return

    user_id = command.get("user_id", "someone")
    emoji = status_emoji(spec.status)
    bar = progress_bar(spec.sections_done, spec.sections_total)

    blocks: list[dict] = [
        header_block(f"Review Request: {spec.title}"),
        section_block(
            f"<@{user_id}> is requesting a review of *{spec.title}*\n"
            f"{emoji} Status: {spec.status}\n"
            f"Progress: {bar}"
        ),
    ]

    if spec.github_url:
        blocks.append(context_block([f"<{spec.github_url}|View on GitHub>"]))

    blocks.append(
        action_buttons(
            [
                ("Approve", "approve_spec", spec.slug),
                ("Request Changes", "request_changes", spec.slug),
                ("Sync Tickets", "sync_tickets", spec.slug),
            ]
        )
    )

    await respond(blocks=blocks, response_type="in_channel")

    # Also send a notification to the configured default channel (best-effort)
    try:
        from canon.main import app

        dispatcher = getattr(app.state, "notification_dispatcher", None)
        if dispatcher is not None:
            await dispatcher.send_review_requested(
                spec_title=spec.title,
                requester=f"<@{user_id}>",
                github_url=spec.github_url,
            )
    except Exception:
        logger.debug("Failed to send review requested notification", exc_info=True)


async def new_spec_handler(ack: Any, respond: Any, client: Any, args: str, command: dict) -> None:
    """Open a modal to create a new spec."""
    await ack()

    # Check permission
    user_id = command.get("user_id", "")
    identity_store = _get_identity_store()

    from .permissions import resolve_permission

    perm = await resolve_permission(user_id, identity_store)
    if perm.value not in ("write", "admin"):
        await respond(
            blocks=[
                section_block(
                    ":lock: Spec creation requires write permission. Link your GitHub account with `/canon link`."
                )
            ],
            response_type="ephemeral",
        )
        return

    title = args.strip()

    # Fetch known teams for the dropdown
    teams: list[str] = []
    try:
        loader, ok = await _load_specs(respond)
        if ok:
            stats = loader.coverage_stats()
            teams = stats.get("teams", [])
    except Exception:
        pass

    team_options = (
        [{"text": {"type": "plain_text", "text": t}, "value": t} for t in teams]
        if teams
        else [
            {"text": {"type": "plain_text", "text": "default"}, "value": "default"},
        ]
    )

    blocks: list[dict] = [
        {
            "type": "input",
            "block_id": "title_block",
            "element": {
                "type": "plain_text_input",
                "action_id": "title_input",
                "initial_value": title,
                "placeholder": {"type": "plain_text", "text": "e.g. user-authentication"},
            },
            "label": {"type": "plain_text", "text": "Title (slug)"},
        },
        {
            "type": "input",
            "block_id": "type_block",
            "element": {
                "type": "static_select",
                "action_id": "type_select",
                "options": [
                    {"text": {"type": "plain_text", "text": "spec"}, "value": "spec"},
                    {"text": {"type": "plain_text", "text": "proposal"}, "value": "proposal"},
                    {"text": {"type": "plain_text", "text": "design"}, "value": "design"},
                    {"text": {"type": "plain_text", "text": "adr"}, "value": "adr"},
                ],
                "initial_option": {"text": {"type": "plain_text", "text": "spec"}, "value": "spec"},
            },
            "label": {"type": "plain_text", "text": "Type"},
        },
        {
            "type": "input",
            "block_id": "team_block",
            "element": {
                "type": "static_select",
                "action_id": "team_select",
                "options": team_options,
            },
            "label": {"type": "plain_text", "text": "Team"},
        },
        {
            "type": "input",
            "block_id": "background_block",
            "element": {
                "type": "plain_text_input",
                "action_id": "background_input",
                "multiline": True,
                "placeholder": {"type": "plain_text", "text": "Brief motivation for this spec..."},
            },
            "label": {"type": "plain_text", "text": "Background"},
            "optional": True,
        },
    ]

    await client.views_open(
        trigger_id=command["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "new_spec_submit",
            "title": {"type": "plain_text", "text": "Create New Spec"},
            "submit": {"type": "plain_text", "text": "Create"},
            "blocks": blocks,
        },
    )


# Lazily-initialized persistent mute store
_mute_store_instance = None


def _get_mute_store():
    """Get or create the singleton MuteStore."""
    global _mute_store_instance
    if _mute_store_instance is None:
        from .mute_store import MuteStore

        _mute_store_instance = MuteStore()
    return _mute_store_instance


def get_muted_specs(user_id: str) -> set[str]:
    """Return the set of spec slugs muted by a user."""
    return _get_mute_store().get_muted(user_id)


async def mute_handler(ack: Any, respond: Any, args: str, command: dict) -> None:
    """Mute notifications for a spec."""
    await ack()
    slug = args.strip()
    if not slug:
        await respond(
            blocks=[section_block("Usage: `/canon mute <spec-slug>`")],
            response_type="ephemeral",
        )
        return

    user_id = command.get("user_id", "")
    _get_mute_store().mute(user_id, slug)

    await respond(
        blocks=[section_block(f":mute: Muted notifications for `{slug}`.")],
        response_type="ephemeral",
    )


async def unmute_handler(ack: Any, respond: Any, args: str, command: dict) -> None:
    """Unmute notifications for a spec."""
    await ack()
    slug = args.strip()
    if not slug:
        await respond(
            blocks=[section_block("Usage: `/canon unmute <spec-slug>`")],
            response_type="ephemeral",
        )
        return

    user_id = command.get("user_id", "")
    _get_mute_store().unmute(user_id, slug)

    await respond(
        blocks=[section_block(f":loud_sound: Unmuted notifications for `{slug}`.")],
        response_type="ephemeral",
    )


def _get_identity_store():
    """Get the IdentityStore from app state.

    Returns the DB-backed `slack_identity_store` (set up in main.py *after*
    db_pool is initialized) when available, falling back to the legacy
    `identity_store` for compatibility. The legacy alias is constructed
    before db_pool exists, so its writes go to an in-memory dict and are
    lost on restart — never use it for persistent linking.
    """
    try:
        from canon.main import app

        return getattr(app.state, "slack_identity_store", None) or getattr(
            app.state, "identity_store", None
        )
    except Exception:
        return None


_GITHUB_USERNAME_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")


async def link_handler(ack: Any, respond: Any, args: str, command: dict) -> None:
    """Link Slack account to GitHub username."""
    await ack()

    github_login = args.strip()
    if not github_login:
        await respond(
            blocks=[section_block("Usage: `/canon link <github-username>`")],
            response_type="ephemeral",
        )
        return

    # Validate GitHub username format BEFORE the API call. Without this, a
    # value like "../zen" is interpolated into the URL and httpx normalises
    # it to https://api.github.com/zen (the GitHub Zen endpoint, which
    # returns 200), so the bogus value would be accepted and stored.
    if not _GITHUB_USERNAME_RE.fullmatch(github_login):
        await respond(
            blocks=[
                section_block(
                    f":x: `{github_login}` isn't a valid GitHub username "
                    "(letters, digits, single hyphens, max 39 chars)."
                )
            ],
            response_type="ephemeral",
        )
        return

    identity_store = _get_identity_store()
    if identity_store is None:
        await respond(
            blocks=[section_block(":warning: Identity linking is not available.")],
            response_type="ephemeral",
        )
        return

    # Verify the GitHub username exists before linking
    try:
        import httpx

        async with httpx.AsyncClient() as http:
            resp = await http.get(f"https://api.github.com/users/{github_login}")
        if resp.status_code != 200:
            await respond(
                blocks=[
                    section_block(
                        f":x: GitHub user `{github_login}` not found. Please check the username."
                    )
                ],
                response_type="ephemeral",
            )
            return
    except Exception:
        logger.warning("GitHub username verification failed for %s", github_login, exc_info=True)
        await respond(
            blocks=[
                section_block(
                    ":warning: Could not verify GitHub username — please try again later."
                )
            ],
            response_type="ephemeral",
        )
        return

    user_id = command.get("user_id", "")
    await identity_store.link(user_id, github_login)

    track_slack(
        EVENT_IDENTITY_LINKED,
        SuperProperties(
            slack_workspace_id=command.get("team_id", ""),
            org_id="unknown",
            extension_version="0.1.0",
        ),
        {"method": "link_command"},
        distinct_id=user_id,
    )

    await respond(
        blocks=[
            section_block(f":link: Linked your Slack account to GitHub user `{github_login}`.")
        ],
        response_type="ephemeral",
    )


async def unlink_handler(ack: Any, respond: Any, command: dict) -> None:
    """Unlink Slack account from GitHub."""
    await ack()

    identity_store = _get_identity_store()
    if identity_store is None:
        await respond(
            blocks=[section_block(":warning: Identity linking is not available.")],
            response_type="ephemeral",
        )
        return

    user_id = command.get("user_id", "")
    removed = await identity_store.unlink(user_id)

    if removed:
        msg = ":broken_chain: Unlinked your GitHub account."
    else:
        msg = "No GitHub account was linked."

    await respond(
        blocks=[section_block(msg)],
        response_type="ephemeral",
    )
