"""WorkContextCoordinator: parallel fetch + ranking + token budget + telemetry."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable

from canon_slack.telemetry import (
    EVENT_SOURCE_FETCHED,
    EVENT_WORK_CONTEXT_ASSEMBLED,
    SuperProperties,
    track_slack,
)
from canon_slack.work_context.models import (
    ContextBundle,
    Intent,
    PersonalContext,
    RecencyProfile,
    WorkContextItem,
)
from canon_slack.work_context.ranking import apply_token_budget, score_items
from canon_slack.work_context.sources.base import WorkContextSource

logger = logging.getLogger(__name__)

DEFAULT_PER_SOURCE_TIMEOUT_S = 5.0
DEFAULT_MAX_TOKENS = 6000
DEFAULT_PER_SOURCE_CAP = 10


class WorkContextCoordinator:
    def __init__(
        self,
        sources: list[WorkContextSource],
        super_props: SuperProperties,
        distinct_id: str,
        per_source_timeout: float = DEFAULT_PER_SOURCE_TIMEOUT_S,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        per_source_cap: int = DEFAULT_PER_SOURCE_CAP,
    ) -> None:
        self._sources = sources
        self._super_props = super_props
        self._distinct_id = distinct_id
        self._per_source_timeout = per_source_timeout
        self._max_tokens = max_tokens
        self._per_source_cap = per_source_cap

    async def load(
        self,
        query: str,
        org_id: str,
        intent: Intent,
        recency: RecencyProfile,
        personal_context: PersonalContext | None = None,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> ContextBundle:
        start = time.monotonic()

        enabled = [s for s in self._sources if s.enabled_for_org(org_id)]
        sources_attempted = len(enabled)

        async def _safe_fetch(src: WorkContextSource) -> list[WorkContextItem]:
            t0 = time.monotonic()
            recency_days = recency.days_for_source(src.name)
            try:
                items = await asyncio.wait_for(
                    src.fetch(query, recency_days, self._per_source_cap),
                    timeout=self._per_source_timeout,
                )
                track_slack(
                    EVENT_SOURCE_FETCHED,
                    self._super_props,
                    {
                        "source": src.name,
                        "success": True,
                        "error_type": None,
                        "duration_ms": int((time.monotonic() - t0) * 1000),
                        "items_returned": len(items),
                        "recency_days": recency_days,
                        "cap": self._per_source_cap,
                    },
                    distinct_id=self._distinct_id,
                )
                return items
            except TimeoutError:
                track_slack(
                    EVENT_SOURCE_FETCHED,
                    self._super_props,
                    {
                        "source": src.name,
                        "success": False,
                        "error_type": "timeout",
                        "duration_ms": int((time.monotonic() - t0) * 1000),
                        "items_returned": 0,
                        "recency_days": recency_days,
                        "cap": self._per_source_cap,
                    },
                    distinct_id=self._distinct_id,
                )
                return []
            except Exception as exc:
                track_slack(
                    EVENT_SOURCE_FETCHED,
                    self._super_props,
                    {
                        "source": src.name,
                        "success": False,
                        "error_type": type(exc).__name__,
                        "duration_ms": int((time.monotonic() - t0) * 1000),
                        "items_returned": 0,
                        "recency_days": recency_days,
                        "cap": self._per_source_cap,
                    },
                    distinct_id=self._distinct_id,
                )
                logger.warning("Coordinator: source %s failed", src.name, exc_info=True)
                return []

        # Run all sources in parallel; collect via as_completed for progress UI.
        # Wrap each fetch as a coroutine that returns (source_name, items) so
        # we don't lose the mapping when as_completed wraps the futures.
        async def _fetch_with_name(src: WorkContextSource) -> tuple[str, list[WorkContextItem]]:
            items = await _safe_fetch(src)
            return src.name, items

        coros = [_fetch_with_name(s) for s in enabled]
        completed: list[tuple[str, list[WorkContextItem]]] = []
        for fut in asyncio.as_completed(coros):
            name, items = await fut
            completed.append((name, items))
            if progress_callback is not None:
                with contextlib.suppress(Exception):
                    completed_names = " ".join(f"{n}{'✓' if got else '✗'}" for n, got in completed)
                    await progress_callback(completed_names)

        # Aggregate
        all_items: list[WorkContextItem] = []
        sources_succeeded = 0
        for _name, items in completed:
            if items:
                sources_succeeded += 1
            all_items.extend(items)

        total_before_cap = len(all_items)
        score_items(all_items, query=query)
        kept = apply_token_budget(all_items, max_tokens=self._max_tokens)

        bundle = ContextBundle(
            items=kept,
            personal_context=personal_context,
            sources_attempted=sources_attempted,
            sources_succeeded=sources_succeeded,
            total_tokens=sum(len(i.title) // 4 + len(i.summary) // 4 for i in kept),
        )

        track_slack(
            EVENT_WORK_CONTEXT_ASSEMBLED,
            self._super_props,
            {
                "sources_attempted": sources_attempted,
                "sources_succeeded": sources_succeeded,
                "total_items_before_cap": total_before_cap,
                "total_items_after_cap": len(kept),
                "total_tokens": bundle.total_tokens,
                "personal_context_injected": personal_context is not None,
                "intent": intent.value,
                "duration_ms": int((time.monotonic() - start) * 1000),
            },
            distinct_id=self._distinct_id,
        )

        return bundle
