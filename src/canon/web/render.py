"""Render parsed SpecDocument to HTML."""

from __future__ import annotations

import re
from html import escape as esc
from typing import Literal

import mistune

from ..parser.models import AcceptanceCriterion, Scenario, SpecDocument, SpecSection

_markdown = mistune.create_markdown()

_CANON_COMMENT_RE = re.compile(r"<!--\s*(?:specwright|canon):\S+.*?-->")


def _strip_canon_comments(content: str) -> str:
    """Remove canon/specwright HTML comments from content before rendering."""
    return _CANON_COMMENT_RE.sub("", content)


STATUS_COLORS: dict[str, str] = {
    "done": "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400",
    "in_progress": "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-400",
    "blocked": "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400",
    "draft": "bg-gray-100 text-gray-600 dark:bg-slate-700/40 dark:text-slate-400",
    "todo": "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400",
    "deprecated": "bg-purple-100 text-purple-800 dark:bg-purple-900/20 dark:text-purple-400",
}


def _status_badge(state: str) -> str:
    colors = STATUS_COLORS.get(state, "bg-gray-100 text-gray-600")
    label = state.replace("_", " ").title()
    return f'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {colors}">{label}</span>'


def _ticket_link_html(ticket: object, *, repo_owner: str = "", repo_name: str = "") -> str:
    from ..parser.models import TicketLink

    if not isinstance(ticket, TicketLink):
        return ""
    tid = esc(ticket.ticket_id)
    link_class = "text-blue-600 dark:text-blue-400 hover:underline text-sm"
    if ticket.system == "jira":
        return f'<a href="https://jira.atlassian.net/browse/{tid}" class="{link_class}" target="_blank">{tid}</a>'
    if ticket.system == "linear":
        return f'<a href="https://linear.app/issue/{tid}" class="{link_class}" target="_blank">{tid}</a>'
    if ticket.system == "github":
        # Parse "owner/repo#N" or "#N" format
        raw_id = ticket.ticket_id
        if "/" in raw_id and "#" in raw_id:
            # "owner/repo#123" format
            repo_part, num = raw_id.rsplit("#", 1)
            owner_part, repo_part = repo_part.split("/", 1)
            url = f"https://github.com/{esc(owner_part)}/{esc(repo_part)}/issues/{esc(num)}"
            return f'<a href="{url}" class="{link_class}" target="_blank">{tid}</a>'
        if raw_id.startswith("#") and repo_owner and repo_name:
            num = raw_id[1:]
            url = f"https://github.com/{esc(repo_owner)}/{esc(repo_name)}/issues/{esc(num)}"
            return f'<a href="{url}" class="{link_class}" target="_blank">{tid}</a>'
        return f'<span class="text-blue-600 dark:text-blue-400 text-sm">{tid}</span>'
    return ""


DELTA_COLORS: dict[str, str] = {
    "added": "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400",
    "modified": "bg-amber-100 text-amber-800 dark:bg-amber-900/20 dark:text-amber-400",
    "removed": "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400",
}


def _delta_badge(delta: Literal["added", "modified", "removed"]) -> str:
    colors = DELTA_COLORS[delta]
    label = delta.title()
    return f'<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium {colors}">{label}</span>'


def _render_scenarios(scenarios: list[Scenario]) -> str:
    if not scenarios:
        return ""
    parts: list[str] = []
    for scenario in scenarios:
        step_items: list[str] = []
        for step in scenario.steps:
            strength = (
                f' <span class="text-xs text-purple-600 dark:text-purple-400">[{step.strength}]</span>'
                if step.strength
                else ""
            )
            step_items.append(
                f'<li class="ml-4"><span class="font-mono text-xs text-blue-700 '
                f'dark:text-blue-400">{esc(step.keyword)}</span> {esc(step.text)}{strength}</li>'
            )
        steps_html = "".join(step_items)
        parts.append(
            f'<div class="mt-2 p-2 bg-slate-50 dark:bg-slate-800/50 rounded border border-slate-200 dark:border-slate-700">'
            f'<div class="text-sm font-medium text-gray-700 dark:text-slate-300">Scenario: {esc(scenario.name)}</div>'
            f'<ul class="mt-1 space-y-0.5 text-sm">{steps_html}</ul>'
            f"</div>"
        )
    return "\n".join(parts)


def _render_ac(criteria: list[AcceptanceCriterion]) -> str:
    if not criteria:
        return ""
    items = []
    for ac in criteria:
        checked = "checked disabled" if ac.checked else "disabled"
        items.append(
            f'<li class="flex items-start gap-2">'
            f'<input type="checkbox" {checked} class="mt-1">'
            f'<span class="{"line-through text-gray-400 dark:text-slate-500" if ac.checked else ""}">{esc(ac.text)}</span>'
            f"</li>"
        )
    return f'<ul class="space-y-1 mt-2">{" ".join(items)}</ul>'


def _render_section(
    section: SpecSection, depth: int = 0, *, repo_owner: str = "", repo_name: str = ""
) -> str:
    tag = f"h{min(section.depth + 1, 6)}"
    size_class = {2: "text-xl", 3: "text-lg", 4: "text-base"}.get(section.depth, "text-base")

    ticket_html = (
        _ticket_link_html(section.ticket_link, repo_owner=repo_owner, repo_name=repo_name)
        if section.ticket_link
        else ""
    )
    blocked_html = ""
    if section.status.blocked_by:
        blocked_html = f'<span class="text-xs text-red-600 dark:text-red-400 ml-2">blocked by {esc(section.status.blocked_by)}</span>'

    delta_html = _delta_badge(section.delta) if section.delta else ""

    clean = _strip_canon_comments(section.content)
    content_html = _markdown(clean) if clean.strip() else ""
    ac_html = _render_ac(section.acceptance_criteria)
    scenarios_html = _render_scenarios(section.scenarios)

    children_html = "\n".join(
        _render_section(child, depth + 1, repo_owner=repo_owner, repo_name=repo_name)
        for child in section.children
    )

    return f"""
    <div class="spec-section ml-{min(depth * 4, 12)} mb-4 border-l-2 border-gray-200 dark:border-slate-700 pl-4" id="section-{section.id}">
      <div class="flex items-center gap-2 mb-1">
        <{tag} class="{size_class} font-semibold text-gray-900 dark:text-slate-100">{esc(section.title)}</{tag}>
        {_status_badge(section.status.state)}
        {delta_html}
        {ticket_html}
        {blocked_html}
      </div>
      <div class="prose prose-sm max-w-none text-gray-700 dark:text-slate-300">{content_html}</div>
      {ac_html}
      {scenarios_html}
      {children_html}
    </div>
    """


def render_spec_html(doc: SpecDocument, *, repo_owner: str = "", repo_name: str = "") -> str:
    """Render a full SpecDocument to HTML."""
    sections_html = "\n".join(
        _render_section(s, repo_owner=repo_owner, repo_name=repo_name) for s in doc.sections
    )
    return f'<div class="spec-content">{sections_html}</div>'


def render_markdown_html(content: str) -> str:
    """Render plain markdown to HTML, stripping canon/specwright comments."""
    clean = _strip_canon_comments(content)
    html = _markdown(clean) if clean.strip() else ""
    return f'<div class="markdown-content">{html}</div>'
