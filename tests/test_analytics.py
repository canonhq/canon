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
