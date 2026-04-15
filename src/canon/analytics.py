"""Thin wrapper around the PostHog Python SDK for server-side analytics.

All public functions are safe to call unconditionally — they no-op when
PostHog is not configured and silently swallow exceptions so analytics
never breaks the application.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None  # posthog.Client instance when initialised

# Default distinct_id for server-originated events (no user context)
SERVER_ACTOR = "canon-server"


_super_properties: dict[str, Any] = {}


def init(
    api_key: str,
    host: str = "https://us.i.posthog.com",
    *,
    super_properties: dict[str, Any] | None = None,
) -> None:
    """Initialise the PostHog client singleton. No-op if *api_key* is empty.

    *super_properties* are merged into every ``track()`` call automatically,
    providing environment context (environment, version, hostname) without
    requiring each call site to pass them.
    """
    global _client, _super_properties
    if super_properties:
        _super_properties = {k: v for k, v in super_properties.items() if v}
    if not api_key:
        logger.debug("PostHog analytics disabled (no API key)")
        return
    try:
        from posthog import Posthog

        _client = Posthog(api_key, host=host, enable_exception_autocapture=True)
        logger.info("PostHog analytics initialised (host=%s)", host)
    except Exception:
        logger.warning("Failed to initialise PostHog client", exc_info=True)


def get_client() -> Any:
    """Return the PostHog client instance, or None if not initialised.

    Used by the PostHog Anthropic wrapper in ClaudeClient, and as a
    feature-detection check for PostHog-aware code paths.
    """
    return _client


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
        merged = {**_super_properties, **(properties or {})}
        _client.capture(
            distinct_id=distinct_id,
            event=event,
            properties=merged or None,
            groups=groups,
        )
    except Exception:
        logger.debug("Failed to track event %s", event, exc_info=True)


# Anthropic pricing per token (USD).  Updated 2026-04.
# Keyed by model prefix — longest match wins.
_MODEL_COSTS: dict[str, tuple[float, float]] = {
    # (input_cost_per_token, output_cost_per_token)
    "claude-opus-4": (15.0 / 1_000_000, 75.0 / 1_000_000),
    "claude-sonnet-4": (3.0 / 1_000_000, 15.0 / 1_000_000),
    "claude-haiku-3.5": (0.80 / 1_000_000, 4.0 / 1_000_000),
    "claude-haiku": (0.25 / 1_000_000, 1.25 / 1_000_000),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> tuple[float, float]:
    """Return (input_cost_usd, output_cost_usd) for *model*.

    Uses longest-prefix match against ``_MODEL_COSTS``.  Returns (0, 0)
    for unknown models rather than guessing.
    """
    best = ""
    for prefix in _MODEL_COSTS:
        if model.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    if not best:
        logger.warning("No cost data for model %r — reporting $0", model)
        return 0.0, 0.0
    cost_in, cost_out = _MODEL_COSTS[best]
    return input_tokens * cost_in, output_tokens * cost_out


def track_ai_generation(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_seconds: float,
    feature: str,
    action: str = "",
    distinct_id: str = SERVER_ACTOR,
    groups: dict[str, str] | None = None,
    extra_properties: dict[str, Any] | None = None,
) -> None:
    """Emit a ``$ai_generation`` event for PostHog LLM analytics.

    Used by async streaming call sites (spec_editor, spec_generator) that
    use vanilla AsyncAnthropic and cannot leverage the automatic PostHog
    Anthropic wrapper.  The sync path in ClaudeClient emits these events
    automatically via the posthog.ai.anthropic wrapper instead.
    """
    input_cost, output_cost = estimate_cost(model, input_tokens, output_tokens)
    props: dict[str, Any] = {
        "$ai_model": model,
        "$ai_provider": "anthropic",
        "$ai_input_tokens": input_tokens,
        "$ai_output_tokens": output_tokens,
        "$ai_input_cost": input_cost,
        "$ai_output_cost": output_cost,
        "$ai_latency": latency_seconds,
        "$ai_trace_id": str(uuid.uuid4()),
        "feature": feature,
    }
    if action:
        props["action"] = action
    if extra_properties:
        props.update(extra_properties)
    track("$ai_generation", distinct_id=distinct_id, properties=props, groups=groups)


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
        merged = {**_super_properties, **(properties or {})}
        _client.capture_exception(
            exception=exc,
            distinct_id=distinct_id,
            properties=merged or None,
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
