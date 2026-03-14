"""OpenTelemetry log export to PostHog.

Configures a ``logging.Handler`` that ships Python log records to PostHog's
OTLP HTTP endpoint.  All public functions are safe to call unconditionally —
they no-op when the feature is disabled and silently swallow exceptions so
logging infrastructure never breaks the application.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.sdk._logs import LoggerProvider

logger = logging.getLogger(__name__)

_provider: LoggerProvider | None = None
_handler: logging.Handler | None = None

_POSTHOG_LOGS_PATH = "/i/v1/logs"


def _endpoint_for_host(host: str) -> str:
    """Derive the OTLP logs endpoint from a PostHog ingest host."""
    return host.rstrip("/") + _POSTHOG_LOGS_PATH


def init(
    api_key: str,
    *,
    min_level: str = "WARNING",
    posthog_host: str = "https://us.i.posthog.com",
) -> None:
    """Attach an OTel log handler to the root logger.

    No-op when *api_key* is empty.  The handler only forwards records at
    *min_level* or above to avoid noise and cost.  The *posthog_host* is
    the same ingest host used for analytics events (e.g. EU region).
    """
    global _provider, _handler

    if not api_key:
        logger.debug("PostHog OTel logs disabled (no API key)")
        return

    try:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter,
        )
        from opentelemetry.sdk._logs import LoggerProvider as _LP
        from opentelemetry.sdk._logs import LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        endpoint = _endpoint_for_host(posthog_host)

        exporter = OTLPLogExporter(
            endpoint=endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
        )

        _provider = _LP()
        _provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

        level = getattr(logging, min_level.upper(), logging.WARNING)
        _handler = LoggingHandler(level=level, logger_provider=_provider)

        logging.getLogger().addHandler(_handler)
        logger.info(
            "PostHog OTel logs initialised (endpoint=%s, min_level=%s)",
            endpoint,
            min_level.upper(),
        )
    except Exception:
        logger.warning("Failed to initialise PostHog OTel logs", exc_info=True)


def shutdown() -> None:
    """Flush pending log records and remove the handler."""
    global _provider, _handler

    if _handler is not None:
        with contextlib.suppress(Exception):
            logging.getLogger().removeHandler(_handler)
        _handler = None

    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:
            logger.debug("Error during OTel log provider shutdown", exc_info=True)
        _provider = None
