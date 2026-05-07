"""Helpers for working with qualified ticket references.

A ``ticket_ref`` is the fully-qualified identifier used as the key into
``ticket_ref_status``. GitHub issues are repo-scoped (#123 in
``org/repo-a`` is a different ticket than #123 in ``org/repo-b``), so
the ref includes the repo prefix. Jira/Linear IDs already encode the
project so the repo is irrelevant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

# 24h between forced re-checks of a 'broken' ref. Conservative — costs
# one adapter call per broken ref per day to detect auto-healing
# (e.g. a re-opened issue).
RECHECK_INTERVAL = timedelta(hours=24)


class _RowLike(Protocol):
    status: str
    last_recheck_at: datetime | None


def qualify(system: str, repo: str | None, ticket_id: str) -> str:
    """Build the fully-qualified ticket_ref used as the
    ``ticket_ref_status`` key.

    Format depends on system:
      github : ``org/repo#123``
      jira   : ``PROJ-123``
      linear : ``TEAM-123``
    """
    if system == "github":
        if not repo:
            raise ValueError("repo is required for github ticket refs")
        return f"{repo}#{ticket_id.lstrip('#')}"
    return ticket_id


def due_for_recheck(row: _RowLike) -> bool:
    """Return True iff a 'broken' row's 24h re-check window has elapsed.

    'ok' rows go through the regular check path. 'dismissed' rows are
    sticky — only explicit user action clears them.
    """
    if row.status != "broken":
        return False
    if row.last_recheck_at is None:
        return True
    return (datetime.now(UTC) - row.last_recheck_at) >= RECHECK_INTERVAL
