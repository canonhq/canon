"""Pydantic models for work_context."""

from __future__ import annotations

import html
from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Intent(StrEnum):
    LOOKUP = "lookup"
    DISCUSSION = "discussion"
    INVESTIGATION = "investigation"


class RecencyProfile(StrEnum):
    RECENT = "recent"
    HISTORICAL = "historical"
    MIXED = "mixed"

    def days_for_source(self, source_name: str) -> int:
        """Return the recency window in days for a given source."""
        if self is RecencyProfile.RECENT:
            return 7
        if self is RecencyProfile.HISTORICAL:
            return 90
        # MIXED: short for messages, long for everything else
        if source_name == "slack_thread":
            return 7
        return 90


class WorkContextItem(BaseModel):
    source: str  # "github_pr", "linear_ticket", "slack_thread", etc.
    title: str
    summary: str
    url: str
    timestamp: datetime
    relevance_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class PersonalContext(BaseModel):
    github_login: str
    team: str | None = None
    owned_specs: list[tuple[str, str]] = Field(default_factory=list)
    # (slug, status); future: followed_specs, muted_specs

    def render(self) -> str:
        safe_login = html.escape(self.github_login, quote=False)
        lines = [
            "<personal_context>",
            f"User GitHub login: {safe_login}",
        ]
        if self.team:
            safe_team = html.escape(self.team, quote=False)
            lines.append(f"User team: {safe_team}")
        if self.owned_specs:
            lines.append("User owns these specs:")
            for slug, status in self.owned_specs:
                safe_slug = html.escape(slug, quote=False)
                safe_status = html.escape(status, quote=False)
                lines.append(f"  - {safe_slug} ({safe_status})")
        lines.append("</personal_context>")
        return "\n".join(lines)


_SOURCE_LABEL: dict[str, str] = {
    "canon_spec": "Specs",
    "canon_pr_analysis": "Recent PR Analysis",
    "github_pr": "PRs",
    "github_commit": "Commits",
    "linear_ticket": "Tickets",
    "jira_ticket": "Tickets",
    "github_issue": "Tickets",
    "slack_thread": "Slack Threads",
}


class ContextBundle(BaseModel):
    items: list[WorkContextItem] = Field(default_factory=list)
    personal_context: PersonalContext | None = None
    sources_attempted: int = 0
    sources_succeeded: int = 0
    total_tokens: int = 0  # estimated, set by ranker

    def total_items(self) -> int:
        return len(self.items)

    def format_for_claude(self) -> str:
        """Render bundle into the work-context block of the system prompt."""
        sections: list[str] = []
        if self.personal_context is not None:
            sections.append(self.personal_context.render())

        # Group items by user-facing label (multiple ticket sources collapse to "Tickets")
        grouped: dict[str, list[WorkContextItem]] = defaultdict(list)
        for item in self.items:
            label = _SOURCE_LABEL.get(item.source, item.source)
            grouped[label].append(item)

        for label, items in grouped.items():
            sections.append(f"<{label.lower().replace(' ', '_')}>")
            sections.append(f"## {label}")
            for item in items:
                safe_title = html.escape(item.title, quote=False)
                safe_summary = html.escape(item.summary, quote=False)
                safe_url = html.escape(item.url, quote=False)
                sections.append(
                    f"- **{safe_title}** "
                    f"({item.timestamp.strftime('%Y-%m-%d')}) — "
                    f"{safe_summary}\n  {safe_url}"
                )
            sections.append(f"</{label.lower().replace(' ', '_')}>")

        return "\n".join(sections)
