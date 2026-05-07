"""Ticket source — graceful no-op (deferred to follow-up PR).

Each sync adapter in ``src/canon/sync/adapters/`` already exposes a
``search_tickets(project_key, title_pattern)`` method, but its signature
is project-scoped + title-prefix and doesn't fit the work-context loader
contract (free-text query + recency window + limit).

Until the adapters gain a query-shaped search (follow-up PR), this source
advertises itself as disabled so the orchestrator skips it cleanly.

Activation options (pick one in the follow-up):
1. Extend the existing ``search_tickets`` signature on each adapter to
   accept ``query`` and ``recency_days`` (preferred; one method per
   adapter rather than two).
2. Add a sibling ``search_tickets_by_query(query, recency_days, limit)``
   method on each adapter and have this source dispatch to it.

Either way, replace the stub below with a fan-out across ``self._adapters``
using ``asyncio.gather(... return_exceptions=True)`` so a single adapter
failure doesn't break the rest.
"""

from __future__ import annotations

import logging
from typing import Any

from canon_slack.work_context.models import WorkContextItem

logger = logging.getLogger(__name__)


class TicketSource:
    """Work-context source for tickets across connected sync adapters.

    Currently a no-op: ``enabled_for_org`` returns ``False`` because the
    adapters' existing ``search_tickets(project_key, title_pattern)`` doesn't
    fit the work-context contract.
    """

    name = "ticket"

    def __init__(self, adapters: dict[str, Any], org_id: str) -> None:
        self._adapters = adapters
        self._org_id = org_id

    def enabled_for_org(self, org_id: str) -> bool:
        return False

    async def fetch(self, query: str, recency_days: int, cap: int) -> list[WorkContextItem]:
        return []
