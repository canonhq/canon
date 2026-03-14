"""Thin wrapper around the PostHog Python SDK for server-side analytics.

All public functions are safe to call unconditionally — they no-op when
PostHog is not configured and silently swallow exceptions so analytics
never breaks the application.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None  # posthog.Client instance when initialised

# Default distinct_id for server-originated events (no user context)
SERVER_ACTOR = "canon-server"


def init(api_key: str, host: str = "https://us.i.posthog.com") -> None:
    """Initialise the PostHog client singleton. No-op if *api_key* is empty."""
    global _client
    if not api_key:
        logger.debug("PostHog analytics disabled (no API key)")
        return
    try:
        from posthog import Posthog

        _client = Posthog(api_key, host=host, enable_exception_autocapture=True)
        logger.info("PostHog analytics initialised (host=%s)", host)
    except Exception:
        logger.warning("Failed to initialise PostHog client", exc_info=True)


def shutdown() -> None:
    """Flush pending events and tear down the client."""
    global _client
    if _client is None:
        return
    try:
        _client.flush()
        _client.shutdown()
    except Exception:
        logger.debug("Error during PostHog shutdown", exc_info=True)
    finally:
        _client = None


def track(
    event: str,
    *,
    distinct_id: str = SERVER_ACTOR,
    properties: dict[str, Any] | None = None,
    groups: dict[str, str] | None = None,
) -> None:
    """Capture an event. No-op when PostHog is not initialised."""
    if _client is None:
        return
    try:
        _client.capture(
            distinct_id=distinct_id,
            event=event,
            properties=properties,
            groups=groups,
        )
    except Exception:
        logger.debug("Failed to track event %s", event, exc_info=True)


def identify(distinct_id: str, properties: dict[str, Any] | None = None) -> None:
    """Identify a user with optional properties."""
    if _client is None:
        return
    try:
        _client.identify(distinct_id, properties)
    except Exception:
        logger.debug("Failed to identify user %s", distinct_id, exc_info=True)


def capture_exception(
    exc: BaseException | None = None,
    *,
    distinct_id: str = SERVER_ACTOR,
    properties: dict[str, Any] | None = None,
    groups: dict[str, str] | None = None,
) -> None:
    """Capture an exception. No-op when PostHog is not initialised."""
    if _client is None:
        return
    try:
        _client.capture_exception(
            exception=exc,
            distinct_id=distinct_id,
            properties=properties,
            groups=groups,
        )
    except Exception:
        logger.debug("Failed to capture exception", exc_info=True)


def group(
    group_type: str,
    group_key: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Set group properties (e.g. organization metadata)."""
    if _client is None:
        return
    try:
        _client.group_identify(group_type, group_key, properties)
    except Exception:
        logger.debug("Failed to set group %s/%s", group_type, group_key, exc_info=True)
