"""WorkContextAgent — v2 will be a tool-using Claude loop. v1 delegates to coordinator."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from canon_slack.work_context.coordinator import WorkContextCoordinator
from canon_slack.work_context.models import (
    ContextBundle,
    Intent,
    PersonalContext,
    RecencyProfile,
)

logger = logging.getLogger(__name__)


class WorkContextAgent:
    """Stub for v2 agent mode. v1 simply delegates to deterministic coordinator.

    Investigation-classified queries route through this class so v2 can
    swap the implementation without touching mentions.py.
    """

    def __init__(self, coordinator: WorkContextCoordinator) -> None:
        self._coordinator = coordinator

    async def investigate(
        self,
        query: str,
        org_id: str,
        recency: RecencyProfile,
        personal_context: PersonalContext | None = None,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> ContextBundle:
        logger.info("WorkContextAgent.investigate (v1 delegating to coordinator)")
        return await self._coordinator.load(
            query=query,
            org_id=org_id,
            intent=Intent.INVESTIGATION,
            recency=recency,
            personal_context=personal_context,
            progress_callback=progress_callback,
        )
