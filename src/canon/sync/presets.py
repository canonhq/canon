"""Status map presets for common ticket system workflows."""

from __future__ import annotations

PRESETS: dict[str, dict] = {
    "standard_jira": {
        "label": "Standard Jira",
        "description": "Default Jira workflow (Backlog → To Do → In Progress → Done)",
        "system": "jira",
        "forward": {
            "draft": "Backlog",
            "todo": "To Do",
            "in_progress": "In Progress",
            "done": "Done",
            "blocked": "Blocked",
            "deprecated": "Won't Do",
        },
        "reverse": {
            "Backlog": "draft",
            "To Do": "todo",
            "In Progress": "in_progress",
            "Done": "done",
            "Blocked": "blocked",
            "Won't Do": "deprecated",
        },
    },
    "agile_board": {
        "label": "Agile Board (Jira)",
        "description": "Agile workflow with QA gate (Open → Dev → QA → Done)",
        "system": "jira",
        "forward": {
            "draft": "Backlog",
            "todo": "Open",
            "in_progress": "In Development",
            "done": "Closed",
            "blocked": "On Hold",
            "deprecated": "Won't Fix",
        },
        "reverse": {
            "Backlog": "draft",
            "Open": "todo",
            "In Development": "in_progress",
            "In QA": "in_progress",
            "Awaiting Deployment": "in_progress",
            "Closed": "done",
            "On Hold": "blocked",
            "Won't Fix": "deprecated",
        },
    },
    "product_led": {
        "label": "Product-Led (Jira)",
        "description": "Product workflow with review stages (Icebox → Prioritized → In Progress → Shipped)",
        "system": "jira",
        "forward": {
            "draft": "Icebox",
            "todo": "Prioritized",
            "in_progress": "In Progress",
            "done": "Shipped",
            "blocked": "Needs Input",
            "deprecated": "Archived",
        },
        "reverse": {
            "Icebox": "draft",
            "Prioritized": "todo",
            "Product Review": "in_progress",
            "In Progress": "in_progress",
            "Staging": "in_progress",
            "Shipped": "done",
            "Needs Input": "blocked",
            "Archived": "deprecated",
        },
    },
    "standard_linear": {
        "label": "Standard Linear",
        "description": "Default Linear workflow (Backlog → Todo → In Progress → Done)",
        "system": "linear",
        "forward": {
            "draft": "Backlog",
            "todo": "Todo",
            "in_progress": "In Progress",
            "done": "Done",
            "blocked": "Blocked",
            "deprecated": "Canceled",
        },
        "reverse": {
            "Backlog": "draft",
            "Todo": "todo",
            "In Progress": "in_progress",
            "Done": "done",
            "Blocked": "blocked",
            "Canceled": "deprecated",
        },
    },
    "standard_github": {
        "label": "Standard GitHub Issues",
        "description": "GitHub Issues with canon labels (open/closed + status labels)",
        "system": "github",
        "forward": {
            "draft": "open|canon:draft",
            "todo": "open|canon:todo",
            "in_progress": "open|canon:in_progress",
            "done": "closed|canon:done",
            "blocked": "open|canon:blocked",
            "deprecated": "closed|canon:deprecated",
        },
        "reverse": {
            "open|canon:draft": "draft",
            "open|canon:todo": "todo",
            "open|canon:in_progress": "in_progress",
            "closed|canon:done": "done",
            "open|canon:blocked": "blocked",
            "closed|canon:deprecated": "deprecated",
        },
    },
}


def get_presets(system: str | None = None) -> dict[str, dict]:
    """Return presets, optionally filtered by ticket system."""
    if system:
        return {k: v for k, v in PRESETS.items() if v.get("system") == system}
    return PRESETS
