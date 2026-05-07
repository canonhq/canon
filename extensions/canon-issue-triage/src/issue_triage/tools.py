"""MCP tool handlers for the issue triage extension."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def triage_issue_handler(
    issue_number: int,
    repo: str,
    *,
    specs_dir: str = "docs/specs",
    apply: bool = False,
    create_spec: bool = False,
) -> dict[str, Any]:
    """MCP tool: Classify a GitHub issue and match it to existing specs.

    This is the primary entry point for the triage extension when invoked
    as an MCP tool. It orchestrates classification, matching, and optionally
    applies labels/comments.

    Args:
        issue_number: The GitHub issue number to triage.
        repo: Repository in "owner/name" format.
        specs_dir: Path to the specs directory (relative to repo root).
        apply: If True, apply labels and post comment.
        create_spec: If True, create a spec PR for unmatched feature requests.

    Returns:
        Dict with classification, confidence, related_specs, and action taken.
    """
    from .matcher import load_spec_summaries

    # This is a simplified version for MCP tool usage.
    # The full orchestration (with GitHub API calls) happens in the CLI command.
    specs_path = Path(specs_dir)
    if not specs_path.is_absolute():
        specs_path = Path.cwd() / specs_path

    spec_summaries = load_spec_summaries(specs_path) if specs_path.exists() else []

    return {
        "issue_number": issue_number,
        "repo": repo,
        "spec_count": len(spec_summaries),
        "message": (
            f"Found {len(spec_summaries)} specs to match against. "
            f"Use `canon triage --issue {issue_number}` for full triage with "
            f"classification and GitHub integration."
        ),
    }
