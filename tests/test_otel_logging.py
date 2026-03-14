"""Tests for the OpenTelemetry log export module."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from canon import otel_logging


@pytest.fixture(autouse=True)
def _reset():
    """Ensure module state is reset between tests."""
    otel_logging._provider = None
    otel_logging._handler = None
    yield
    # Clean up any handler left on root logger
    if otel_logging._handler is not None:
        logging.getLogger().removeHandler(otel_logging._handler)
    otel_logging._provider = None
    otel_logging._handler = None


def _otel_patches():
    """Return a context manager that patches all OTel classes, yielding mocks."""

    class _Ctx:
        def __init__(self):
            self.exporter_cls = MagicMock()
            self.provider_cls = MagicMock()
            self.handler_cls = MagicMock()
            self.processor_cls = MagicMock()

        def __enter__(self):
            self._stack = [
                patch(
                    "opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter",
                    self.exporter_cls,
                ),
                patch("opentelemetry.sdk._logs.LoggerProvider", self.provider_cls),
                patch("opentelemetry.sdk._logs.LoggingHandler", self.handler_cls),
                patch(
                    "opentelemetry.sdk._logs.export.BatchLogRecordProcessor",
                    self.processor_cls,
                ),
            ]
            for p in self._stack:
                p.__enter__()
            return self

        def __exit__(self, *args):
            for p in reversed(self._stack):
                p.__exit__(*args)

    return _Ctx()


# ── init ────────────────────────────────────────────────────


def test_init_noop_without_key():
    otel_logging.init("")
    assert otel_logging._provider is None
    assert otel_logging._handler is None


def test_init_creates_provider_and_handler():
    with _otel_patches() as m:
        otel_logging.init("phc_test_key")

    # Exporter created with default US endpoint
    m.exporter_cls.assert_called_once_with(
        endpoint="https://us.i.posthog.com/i/v1/logs",
        headers={"Authorization": "Bearer phc_test_key"},
    )

    # Provider created and processor added
    m.provider_cls.assert_called_once()
    m.provider_cls.return_value.add_log_record_processor.assert_called_once_with(
        m.processor_cls.return_value,
    )

    # Handler created at WARNING level by default
    m.handler_cls.assert_called_once_with(
        level=logging.WARNING,
        logger_provider=m.provider_cls.return_value,
    )

    assert otel_logging._provider is m.provider_cls.return_value
    assert otel_logging._handler is m.handler_cls.return_value


def test_init_custom_min_level():
    with _otel_patches() as m:
        otel_logging.init("phc_test_key", min_level="ERROR")

    m.handler_cls.assert_called_once_with(
        level=logging.ERROR,
        logger_provider=m.provider_cls.return_value,
    )


def test_init_derives_endpoint_from_posthog_host():
    with _otel_patches() as m:
        otel_logging.init("phc_test_key", posthog_host="https://eu.i.posthog.com")

    m.exporter_cls.assert_called_once_with(
        endpoint="https://eu.i.posthog.com/i/v1/logs",
        headers={"Authorization": "Bearer phc_test_key"},
    )


def test_init_strips_trailing_slash_from_host():
    with _otel_patches() as m:
        otel_logging.init("phc_test_key", posthog_host="https://eu.i.posthog.com/")

    m.exporter_cls.assert_called_once_with(
        endpoint="https://eu.i.posthog.com/i/v1/logs",
        headers={"Authorization": "Bearer phc_test_key"},
    )


def test_init_swallows_exception():
    with patch(
        "opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter",
        side_effect=RuntimeError("boom"),
    ):
        otel_logging.init("phc_test_key")

    assert otel_logging._provider is None
    assert otel_logging._handler is None


def test_init_adds_handler_to_root_logger():
    mock_handler = MagicMock(spec=logging.Handler)

    with _otel_patches() as m:
        m.handler_cls.return_value = mock_handler
        otel_logging.init("phc_test_key")

    assert mock_handler in logging.getLogger().handlers


# ── endpoint_for_host ───────────────────────────────────────


def test_endpoint_for_host_default():
    assert (
        otel_logging._endpoint_for_host("https://us.i.posthog.com")
        == "https://us.i.posthog.com/i/v1/logs"
    )


def test_endpoint_for_host_eu():
    assert (
        otel_logging._endpoint_for_host("https://eu.i.posthog.com")
        == "https://eu.i.posthog.com/i/v1/logs"
    )


def test_endpoint_for_host_trailing_slash():
    assert (
        otel_logging._endpoint_for_host("https://eu.i.posthog.com/")
        == "https://eu.i.posthog.com/i/v1/logs"
    )


# ── shutdown ────────────────────────────────────────────────


def test_shutdown_noop_when_not_initialised():
    otel_logging.shutdown()
    assert otel_logging._provider is None
    assert otel_logging._handler is None


def test_shutdown_removes_handler_and_shuts_down_provider():
    mock_provider = MagicMock()
    mock_handler = MagicMock(spec=logging.Handler)

    otel_logging._provider = mock_provider
    otel_logging._handler = mock_handler
    logging.getLogger().addHandler(mock_handler)

    otel_logging.shutdown()

    mock_provider.shutdown.assert_called_once()
    assert mock_handler not in logging.getLogger().handlers
    assert otel_logging._provider is None
    assert otel_logging._handler is None


def test_shutdown_swallows_provider_exception():
    mock_provider = MagicMock()
    mock_provider.shutdown.side_effect = RuntimeError("shutdown error")
    mock_handler = MagicMock(spec=logging.Handler)

    otel_logging._provider = mock_provider
    otel_logging._handler = mock_handler

    otel_logging.shutdown()

    assert otel_logging._provider is None
    assert otel_logging._handler is None
