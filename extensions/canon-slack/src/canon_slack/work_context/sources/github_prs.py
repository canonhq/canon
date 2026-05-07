"""GitHub PR source — graceful no-op pending API additions.

This source is **intentionally disabled** because the two APIs it requires
do not currently exist in the Canon codebase:

1. ``GitHubClient.search_prs(repo, query, recency_days, limit)``
   There is no PR-search or PR-list method on ``GitHubClient``.  The client
   has ``get_pull_request`` (single PR by number) and ``list_pull_files``,
   but no way to enumerate open/recently-merged PRs or filter them by keyword.
   To enable this source, add a method such as::

       async def list_pulls(
           self, owner: str, repo: str,
           *, state: str = "all", per_page: int = 30
       ) -> list[dict]:
           return await self._get_list(
               f"/repos/{owner}/{repo}/pulls",
               state=state,
               sort="updated",
               direction="desc",
               per_page=str(per_page),
           )

   Or use the GitHub Search API (``GET /search/issues?q=is:pr+repo:…``) for
   keyword matching:

       async def search_prs(
           self, repo: str, query: str, recency_days: int, limit: int
       ) -> list[dict]:
           from datetime import datetime, timedelta, UTC
           since = (datetime.now(UTC) - timedelta(days=recency_days)).strftime(
               "%Y-%m-%d"
           )
           q = f"is:pr repo:{repo} {query} updated:>{since}"
           data = await self._get("/search/issues", q=q, per_page=str(limit))
           return data.get("items", [])

2. ``repos_for_org(org_id)`` on the installations helper
   ``InstallationRegistry`` has ``get_installation_by_oidc_org(oidc_org_id)``
   which returns a single ``Installation`` record (with ``installation_id``).
   From that, ``GitHubClient.list_installation_repos()`` (scoped to the
   installation via ``for_installation()``) already returns all repos.  The
   missing piece is a thin async helper that composes those two calls and
   returns ``["owner/repo", ...]`` strings.

Once both additions are in place, delete this stub and activate the full
implementation shown in the canonical task spec.
"""

from __future__ import annotations

import logging
from typing import Any

from canon_slack.work_context.models import WorkContextItem

logger = logging.getLogger(__name__)


class GitHubPRSource:
    """Work-context source for recent GitHub pull requests.

    Currently a no-op: ``enabled_for_org`` returns ``False`` because
    ``GitHubClient`` has no PR-search/list endpoint and no
    ``repos_for_org`` helper exists.  See module docstring for what is
    needed to activate this source.
    """

    name = "github_pr"

    def __init__(self, gh_client: Any, installations: Any, org_id: str) -> None:
        self._gh = gh_client
        self._installations = installations
        self._org_id = org_id

    def enabled_for_org(self, org_id: str) -> bool:
        # Disabled: missing GitHubClient.search_prs and repos_for_org helper.
        return False

    async def fetch(self, query: str, recency_days: int, cap: int) -> list[WorkContextItem]:
        return []
