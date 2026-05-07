"""WorkContextSource Protocol — every loader implements this."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from canon_slack.work_context.models import WorkContextItem


@runtime_checkable
class WorkContextSource(Protocol):
    """A loader that fetches a single category of context for @canon."""

    name: str

    def enabled_for_org(self, org_id: str) -> bool:
        """Return True if this source can produce results for the given org.

        Should be cheap (no network calls). Used to skip sources whose
        upstream isn't connected for this org (e.g., LinearTicketSource
        returns False if Linear isn't configured).
        """
        ...

    async def fetch(self, query: str, recency_days: int, cap: int) -> list[WorkContextItem]:
        """Fetch up to `cap` items relevant to `query` from the last `recency_days`.

        On any failure, return []. Log warnings; do not raise.
        """
        ...
