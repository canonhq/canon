"""OpenTelemetry log and trace export to PostHog.

Configures a ``logging.Handler`` that ships Python log records to PostHog's
OTLP HTTP endpoint, and a ``TracerProvider`` that creates per-request spans
so log records carry correlated trace/span IDs.

All public functions are safe to call unconditionally — they no-op when the
feature is disabled and silently swallow exceptions so telemetry
infrastructure never breaks the application.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger(__name__)

_log_provider: LoggerProvider | None = None
_trace_provider: TracerProvider | None = None
_handler: logging.Handler | None = None

_POSTHOG_LOGS_PATH = "/i/v1/logs"
_POSTHOG_TRACES_PATH = "/i/v1/traces"


def _endpoint_for_host(host: str, path: str) -> str:
    """Derive an OTLP endpoint from a PostHog ingest host."""
    return host.rstrip("/") + path


def init(
    api_key: str,
    *,
    min_level: str = "WARNING",
    posthog_host: str = "https://us.i.posthog.com",
) -> None:
    """Attach OTel log handler and tracer to the application.

    No-op when *api_key* is empty.  The handler only forwards records at
    *min_level* or above to avoid noise and cost.  The *posthog_host* is
    the same ingest host used for analytics events (e.g. EU region).
    """
    global _log_provider, _trace_provider, _handler

    if not api_key:
        logger.debug("PostHog OTel disabled (no API key)")
        return

    try:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk._logs import LoggerProvider as _LP
        from opentelemetry.sdk._logs import LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider as _TP
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "canon"})
        headers = {"Authorization": f"Bearer {api_key}"}

        # --- Tracing ---
        span_exporter = OTLPSpanExporter(
            endpoint=_endpoint_for_host(posthog_host, _POSTHOG_TRACES_PATH),
            headers=headers,
        )
        _trace_provider = _TP(resource=resource)
        _trace_provider.add_span_processor(BatchSpanProcessor(span_exporter))

        # Set as global so LoggingHandler can read the active span context
        from opentelemetry import trace

        trace.set_tracer_provider(_trace_provider)

        # --- Logging ---
        log_exporter = OTLPLogExporter(
            endpoint=_endpoint_for_host(posthog_host, _POSTHOG_LOGS_PATH),
            headers=headers,
        )
        _log_provider = _LP(resource=resource)
        _log_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

        level = getattr(logging, min_level.upper(), logging.WARNING)
        _handler = LoggingHandler(level=level, logger_provider=_log_provider)

        logging.getLogger().addHandler(_handler)
        logger.info(
            "PostHog OTel initialised (host=%s, min_level=%s, tracing=enabled)",
            posthog_host,
            min_level.upper(),
        )
    except Exception:
        logger.warning("Failed to initialise PostHog OTel", exc_info=True)


def instrument_fastapi(app: object) -> None:
    """Instrument a FastAPI app for automatic per-request span creation.

    Must be called after ``init()``.  No-op if tracing is not configured
    or the instrumentation package is not installed.
    """
    if _trace_provider is None:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,  # type: ignore[arg-type]
            tracer_provider=_trace_provider,
            excluded_urls="healthz,readyz",
        )
        logger.info("FastAPI OTEL instrumentation enabled")
    except Exception:
        logger.warning("Failed to instrument FastAPI with OTel", exc_info=True)


def shutdown() -> None:
    """Flush pending log/trace records and remove the handler."""
    global _log_provider, _trace_provider, _handler

    if _handler is not None:
        with contextlib.suppress(Exception):
            logging.getLogger().removeHandler(_handler)
        _handler = None

    if _log_provider is not None:
        try:
            _log_provider.shutdown()
        except Exception:
            logger.debug("Error during OTel log provider shutdown", exc_info=True)
        _log_provider = None

    if _trace_provider is not None:
        try:
            _trace_provider.shutdown()
        except Exception:
            logger.debug("Error during OTel trace provider shutdown", exc_info=True)
        _trace_provider = None
