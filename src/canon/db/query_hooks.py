"""Database query performance hooks for SRE instrumentation."""

from __future__ import annotations

import logging
import re

from canon import analytics

logger = logging.getLogger(__name__)

# Extract table name from simple queries
_TABLE_RE = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+(\w+)", re.IGNORECASE)


def _extract_query_type(query: str) -> str:
    """Extract a short label like 'SELECT spec_documents' from a query."""
    op = query.strip().split()[0].upper() if query.strip() else "UNKNOWN"
    match = _TABLE_RE.search(query)
    table = match.group(1) if match else "unknown"
    return f"{op} {table}"


def log_slow_query(
    *,
    query: str,
    duration_ms: float,
    threshold_ms: int = 500,
) -> None:
    """Track a db_query_slow event if duration exceeds threshold."""
    if duration_ms < threshold_ms:
        return

    query_type = _extract_query_type(query)
    table = query_type.split(" ", 1)[1] if " " in query_type else "unknown"
    logger.warning("Slow query detected: %s (%.1fms)", query_type, duration_ms)
    analytics.track(
        "db_query_slow",
        properties={
            "query_type": query_type,
            "duration_ms": duration_ms,
            "table": table,
        },
    )
