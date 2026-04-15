"""GitHub webhook event handlers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def _log_bg_exception(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()):
        logger.error("Background task failed", exc_info=exc)


def fire_and_forget(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """Schedule a coroutine as a background task with GC protection."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(_log_bg_exception)
    return task
