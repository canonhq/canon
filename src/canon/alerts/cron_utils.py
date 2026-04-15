"""Utilities for cron job instrumentation."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any

from canon import analytics


def tracked_cron(job_name: str) -> Callable:
    """Decorator that tracks async cron job execution via PostHog.

    All Canon cron jobs are async. This decorator wraps them with timing
    and success/failure tracking via analytics.track("cron_job_executed").
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            success = True
            error_message = ""
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                success = False
                error_message = str(exc)
                raise
            finally:
                duration_ms = round((time.monotonic() - start) * 1000, 1)
                analytics.track(
                    "cron_job_executed",
                    properties={
                        "job_name": job_name,
                        "success": success,
                        "duration_ms": duration_ms,
                        "error_message": error_message,
                    },
                )

        return wrapper

    return decorator
