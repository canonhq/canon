"""PR analysis history source — graceful no-op.

There is no ``pr_analyses`` table in the Canon schema.  PR analysis
results are written to ``agent_events`` (event_type ``"pr_comment"``)
and ``realization_evidence``, both keyed by *repo* (``"owner/repo"``),
not by *org_id*.  Joining from org_id → repos requires an installation
lookup that is not currently available in the work-context pipeline.

Until a dedicated, org-scoped table is added this source advertises
itself as disabled so the orchestrator skips it cleanly.
"""

from __future__ import annotations

import logging
from typing import Any

from canon_slack.work_context.models import WorkContextItem

logger = logging.getLogger(__name__)


class CanonPRAnalysisSource:
    """Work-context source for Canon PR analysis history.

    Currently a no-op: ``enabled_for_org`` returns ``False`` because no
    org-scoped PR analysis table exists.  When such a table is added,
    replace this stub with a real DB query.
    """

    name = "canon_pr_analysis"

    def __init__(self, pool: Any, org_id: str) -> None:
        self._pool = pool
        self._org_id = org_id

    def enabled_for_org(self, org_id: str) -> bool:
        # No PR analysis table yet — graceful no-op.
        return False

    async def fetch(self, query: str, recency_days: int, cap: int) -> list[WorkContextItem]:
        return []
