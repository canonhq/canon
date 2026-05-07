"""Canon spec source — wraps the existing SpecLoader."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from canon_slack.work_context.models import WorkContextItem

logger = logging.getLogger(__name__)

# Fallback timestamp when a spec has no recorded update date.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _parse_updated(updated: str) -> datetime:
    """Parse the spec's updated string (YYYY-MM-DD) into a UTC datetime.

    Returns _EPOCH if the string is absent or unparseable.
    """
    if not updated:
        return _EPOCH
    try:
        return datetime.strptime(updated, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return _EPOCH


class CanonSpecSource:
    """Fetch spec summaries from the Canon SpecLoader as WorkContextItems."""

    name = "canon_spec"

    def __init__(self, spec_loader: Any) -> None:
        self._loader = spec_loader

    def enabled_for_org(self, org_id: str) -> bool:
        return True

    async def fetch(self, query: str, recency_days: int, cap: int) -> list[WorkContextItem]:
        try:
            await self._loader.load()
            specs = self._loader.search(query)
        except Exception:
            logger.warning("CanonSpecSource.fetch failed", exc_info=True)
            return []

        items: list[WorkContextItem] = []
        for spec in specs[:cap]:
            ac_summary = f"{spec.sections_done}/{spec.sections_total} sections done"
            items.append(
                WorkContextItem(
                    source=self.name,
                    title=spec.title,
                    summary=f"Status: {spec.status}. {ac_summary}",
                    url=spec.github_url,
                    timestamp=_parse_updated(spec.updated),
                    metadata={"slug": spec.slug, "status": spec.status},
                )
            )
        return items
