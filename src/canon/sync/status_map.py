"""Bidirectional status mapping between spec states and ticket systems.

Supports both the built-in default mappings and user-defined custom mappings
via StatusMapConfig. The existing public API is preserved for backward
compatibility; new code should prefer resolve_forward / resolve_reverse.
"""

from __future__ import annotations

import logging

from canon.parser.models import SectionStatus
from canon.sync.mapping import StatusMapConfig

logger = logging.getLogger(__name__)

# ─── Built-in defaults (match original hardcoded dicts) ──────────

DEFAULT_JIRA_STATUS_MAP = StatusMapConfig(
    forward={
        "draft": "Backlog",
        "todo": "To Do",
        "in_progress": "In Progress",
        "done": "Done",
        "blocked": "Blocked",
        "deprecated": "Won't Do",
    },
    reverse={
        "new": "todo",
        "indeterminate": "in_progress",
        "done": "done",
    },
    fallback="draft",
)

DEFAULT_LINEAR_STATUS_MAP = StatusMapConfig(
    forward={
        "draft": "Backlog",
        "todo": "Todo",
        "in_progress": "In Progress",
        "done": "Done",
        "blocked": "In Progress",
        "deprecated": "Canceled",
    },
    reverse={
        "backlog": "draft",
        "unstarted": "todo",
        "started": "in_progress",
        "completed": "done",
        "canceled": "deprecated",
    },
    fallback="draft",
)

DEFAULT_GITHUB_STATUS_MAP = StatusMapConfig(
    forward={
        "draft": "open|canon:draft",
        "todo": "open|canon:todo",
        "in_progress": "open|canon:in-progress",
        "done": "closed|canon:done",
        "blocked": "open|canon:blocked",
        "deprecated": "closed|canon:deprecated",
    },
    reverse={
        "canon:draft": "draft",
        "canon:todo": "todo",
        "canon:in-progress": "in_progress",
        "canon:done": "done",
        "canon:blocked": "blocked",
        "canon:deprecated": "deprecated",
        # Legacy label compat
        "specwright:draft": "draft",
        "specwright:todo": "todo",
        "specwright:in-progress": "in_progress",
        "specwright:done": "done",
        "specwright:blocked": "blocked",
        "specwright:deprecated": "deprecated",
    },
    fallback="draft",
)

DEFAULT_STATUS_MAPS: dict[str, StatusMapConfig] = {
    "jira": DEFAULT_JIRA_STATUS_MAP,
    "linear": DEFAULT_LINEAR_STATUS_MAP,
    "github": DEFAULT_GITHUB_STATUS_MAP,
}


# ─── Configurable resolution ────────────────────────────────────


def resolve_forward(
    system: str,
    spec_state: str,
    config: StatusMapConfig | None = None,
) -> str:
    """Resolve a spec state to a ticket status string.

    Uses ``config.forward`` when provided. For any spec states not
    covered by the custom map, falls back to the built-in default for
    ``system``. This merge-with-fallback behavior means a partial
    custom map only needs to override the states that differ.
    """
    effective = config if config and config.forward else DEFAULT_STATUS_MAPS.get(system)
    if effective and spec_state in effective.forward:
        return effective.forward[spec_state]
    # Fall back to system default even when custom config is partial
    default = DEFAULT_STATUS_MAPS.get(system)
    if default and spec_state in default.forward:
        return default.forward[spec_state]
    return "Backlog"


def resolve_reverse(
    system: str,
    ticket_status: str,
    config: StatusMapConfig | None = None,
) -> SectionStatus:
    """Resolve a ticket status string to a spec SectionStatus.

    Checks ``config.reverse`` first (if provided), then the built-in
    default for ``system``. Unmapped values fall back to the config's
    ``fallback`` or "draft".
    """
    # Check custom reverse map first
    if config and config.reverse and ticket_status in config.reverse:
        state = config.reverse[ticket_status]
        return SectionStatus(state=state)  # type: ignore[arg-type]

    # Check default reverse map
    default = DEFAULT_STATUS_MAPS.get(system)
    if default and ticket_status in default.reverse:
        state = default.reverse[ticket_status]
        return SectionStatus(state=state)  # type: ignore[arg-type]

    # Fallback
    fallback = config.fallback if config else "draft"
    return SectionStatus(state=fallback)  # type: ignore[arg-type]


# ─── GitHub-specific helpers (state+label compound status) ───────


class GitHubIssueStatus:
    def __init__(self, state: str, label: str) -> None:
        self.state = state
        self.label = label


def resolve_forward_github(
    spec_state: str,
    config: StatusMapConfig | None = None,
) -> GitHubIssueStatus:
    """Resolve spec state to GitHub issue state + label.

    Custom forward maps for GitHub use "state|label" format.
    """
    raw = resolve_forward("github", spec_state, config)
    if "|" in raw:
        state, label = raw.split("|", 1)
        return GitHubIssueStatus(state, label)
    # Custom value without "|" — warn about likely misconfiguration
    if config and config.forward and spec_state in config.forward:
        logger.warning(
            "Custom GitHub forward status %r for state %r missing 'state|label' format, "
            "falling back to default label",
            raw,
            spec_state,
        )
    return GitHubIssueStatus("open", f"canon:{spec_state}")


def resolve_reverse_github(
    issue_state: str,
    labels: list[str],
    config: StatusMapConfig | None = None,
) -> SectionStatus:
    """Resolve GitHub issue state + labels to spec status.

    Checks canon:* (or legacy specwright:*) labels first (most specific), then issue state.
    """
    # Check labels against reverse map
    for label in labels:
        result = resolve_reverse("github", label, config)
        if result.state != (config.fallback if config else "draft"):
            return result

    # Fallback: open → todo, closed → done
    if issue_state == "closed":
        return SectionStatus(state="done")
    return SectionStatus(state="todo")


# ─── Legacy public API (preserved for backward compatibility) ────


def spec_status_to_jira(status: SectionStatus) -> str:
    return resolve_forward("jira", status.state)


def spec_status_to_linear(status: SectionStatus) -> str:
    return resolve_forward("linear", status.state)


def jira_category_to_spec_status(category_key: str) -> SectionStatus:
    return resolve_reverse("jira", category_key)


def linear_type_to_spec_status(state_type: str) -> SectionStatus:
    return resolve_reverse("linear", state_type)


def spec_status_to_github(status: SectionStatus) -> GitHubIssueStatus:
    return resolve_forward_github(status.state)


def github_to_spec_status(issue_state: str, labels: list[str]) -> SectionStatus:
    return resolve_reverse_github(issue_state, labels)
