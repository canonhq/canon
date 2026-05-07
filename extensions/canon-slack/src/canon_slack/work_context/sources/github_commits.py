"""GitHub commit source — graceful no-op (deferred to follow-up PR).

The required GitHubClient API (``list_commits(repo, recency_days, limit)``)
does not yet exist on ``canon.github.client.GitHubClient``. Like
``GitHubPRSource``, the underlying ``InstallationRegistry`` also lacks the
composed ``repos_for_org(org_id) -> list[str]`` helper.

Until those APIs are added (in a follow-up PR), this source advertises
itself as disabled so the orchestrator skips it cleanly.

To activate:
1. Add ``GitHubClient.list_commits(repo, recency_days, limit)`` using the
   GitHub ``GET /repos/{owner}/{repo}/commits?since=...`` API
2. Add ``InstallationRegistry.repos_for_org(org_id) -> list[str]`` helper
3. Replace the stub below with a query that filters commits whose message
   or changed-file paths contain query keywords
"""

from __future__ import annotations

import logging
from typing import Any

from canon_slack.work_context.models import WorkContextItem

logger = logging.getLogger(__name__)


class GitHubCommitSource:
    """Work-context source for recent GitHub commits.

    Currently a no-op: ``enabled_for_org`` returns ``False`` because the
    required GitHubClient and InstallationRegistry APIs do not exist.
    """

    name = "github_commit"

    def __init__(self, gh_client: Any, installations: Any, org_id: str) -> None:
        self._gh = gh_client
        self._installations = installations
        self._org_id = org_id

    def enabled_for_org(self, org_id: str) -> bool:
        return False

    async def fetch(self, query: str, recency_days: int, cap: int) -> list[WorkContextItem]:
        return []
