"""Tests for the analytics module (PostHog wrapper)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from canon import analytics


@pytest.fixture(autouse=True)
def _reset_client():
    """Ensure the module-level client is reset between tests."""
    analytics._client = None
    yield
    analytics._client = None


# ── init ────────────────────────────────────────────────────


def test_init_noop_without_key():
    analytics.init("")
    assert analytics._client is None


def test_init_creates_client():
    mock_cls = MagicMock()
    with patch("posthog.Posthog", mock_cls):
        analytics.init("phc_test_key", "https://us.i.posthog.com")
    mock_cls.assert_called_once_with(
        "phc_test_key", host="https://us.i.posthog.com", enable_exception_autocapture=True
    )
    assert analytics._client is mock_cls.return_value


def test_init_swallows_exception():
    with patch("posthog.Posthog", side_effect=RuntimeError("boom")):
        analytics.init("phc_test_key")
    assert analytics._client is None


# ── track ───────────────────────────────────────────────────


def test_track_noop_when_not_initialised():
    # Should not raise
    analytics.track("test_event", properties={"a": 1})


def test_track_captures_event():
    mock_client = MagicMock()
    analytics._client = mock_client

    analytics.track(
        "pr_analyzed",
        distinct_id="user@example.com",
        properties={"repo": "org/repo"},
        groups={"organization": "org"},
    )

    mock_client.capture.assert_called_once_with(
        distinct_id="user@example.com",
        event="pr_analyzed",
        properties={"repo": "org/repo"},
        groups={"organization": "org"},
    )


def test_track_uses_default_distinct_id():
    mock_client = MagicMock()
    analytics._client = mock_client

    analytics.track("webhook_received")

    mock_client.capture.assert_called_once()
    call_kwargs = mock_client.capture.call_args[1]
    assert call_kwargs["distinct_id"] == analytics.SERVER_ACTOR


def test_track_swallows_exception():
    mock_client = MagicMock()
    mock_client.capture.side_effect = RuntimeError("network error")
    analytics._client = mock_client

    # Should not raise
    analytics.track("some_event")


# ── get_client ──────────────────────────────────────────────


def test_get_client_returns_none_when_not_initialised():
    assert analytics.get_client() is None


def test_get_client_returns_client_after_init():
    mock_cls = MagicMock()
    with patch("posthog.Posthog", mock_cls):
        analytics.init("phc_test_key")
    assert analytics.get_client() is mock_cls.return_value


# ── track_ai_generation ────────────────────────────────────


def test_track_ai_generation_emits_event():
    mock_client = MagicMock()
    analytics._client = mock_client

    analytics.track_ai_generation(
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        latency_seconds=1.5,
        feature="pr_analysis",
        action="analyze",
        groups={"organization": "acme"},
    )

    mock_client.capture.assert_called_once()
    call_kwargs = mock_client.capture.call_args[1]
    assert call_kwargs["event"] == "$ai_generation"
    assert call_kwargs["distinct_id"] == analytics.SERVER_ACTOR
    assert call_kwargs["groups"] == {"organization": "acme"}
    props = call_kwargs["properties"]
    assert props["$ai_model"] == "claude-sonnet-4-6"
    assert props["$ai_provider"] == "anthropic"
    assert props["$ai_input_tokens"] == 100
    assert props["$ai_output_tokens"] == 50
    assert props["$ai_latency"] == 1.5
    assert props["feature"] == "pr_analysis"
    assert props["action"] == "analyze"
    assert "$ai_trace_id" in props


def test_track_ai_generation_noop_when_not_configured():
    # Should not raise when PostHog is not configured
    analytics.track_ai_generation(
        model="test",
        input_tokens=0,
        output_tokens=0,
        latency_seconds=0,
        feature="test",
    )


def test_track_ai_generation_includes_extra_properties():
    mock_client = MagicMock()
    analytics._client = mock_client

    analytics.track_ai_generation(
        model="test",
        input_tokens=10,
        output_tokens=20,
        latency_seconds=0.5,
        feature="spec_edit",
        extra_properties={"repo": "org/repo"},
    )

    props = mock_client.capture.call_args[1]["properties"]
    assert props["repo"] == "org/repo"


# ── identify ────────────────────────────────────────────────


def test_identify_noop_when_not_initialised():
    analytics.identify("user@example.com", {"name": "Test"})


def test_identify_calls_client():
    mock_client = MagicMock()
    analytics._client = mock_client

    analytics.identify("auth0|abc123", {"email": "user@example.com", "name": "Test User"})

    mock_client.identify.assert_called_once_with(
        "auth0|abc123", {"email": "user@example.com", "name": "Test User"}
    )


def test_identify_swallows_exception():
    mock_client = MagicMock()
    mock_client.identify.side_effect = RuntimeError("fail")
    analytics._client = mock_client

    analytics.identify("user@example.com")


# ── group ───────────────────────────────────────────────────


def test_group_noop_when_not_initialised():
    analytics.group("organization", "acme-corp")


def test_group_calls_client():
    mock_client = MagicMock()
    analytics._client = mock_client

    analytics.group("organization", "acme-corp", {"plan": "enterprise"})

    mock_client.group_identify.assert_called_once_with(
        "organization", "acme-corp", {"plan": "enterprise"}
    )


def test_group_swallows_exception():
    mock_client = MagicMock()
    mock_client.group_identify.side_effect = RuntimeError("fail")
    analytics._client = mock_client

    analytics.group("organization", "acme-corp")


# ── shutdown ────────────────────────────────────────────────


def test_shutdown_noop_when_not_initialised():
    analytics.shutdown()
    assert analytics._client is None


def test_shutdown_flushes_and_clears():
    mock_client = MagicMock()
    analytics._client = mock_client

    analytics.shutdown()

    mock_client.flush.assert_called_once()
    mock_client.shutdown.assert_called_once()
    assert analytics._client is None


def test_shutdown_swallows_exception():
    mock_client = MagicMock()
    mock_client.flush.side_effect = RuntimeError("flush error")
    analytics._client = mock_client

    analytics.shutdown()
    assert analytics._client is None
