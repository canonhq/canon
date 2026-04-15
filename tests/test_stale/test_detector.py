"""Tests for staleness detection."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from canon.stale.detector import assess_staleness, detect_stale_docs


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


class TestDetectStaleDocs:
    async def test_returns_stale_docs(self):
        now = datetime.now(UTC)
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "path": "docs/specs/auth.md",
                "title": "Auth Spec",
                "last_doc_change_at": now - timedelta(days=90),
                "last_code_change_at": now - timedelta(days=1),
                "stale_since": now - timedelta(days=30),
            },
        ]

        mock_pool = _mock_pool_with_conn(mock_conn)
        search_index = MagicMock()
        search_index._pool = mock_pool

        results = await detect_stale_docs(search_index, "org/repo")

        assert len(results) == 1
        assert results[0].path == "docs/specs/auth.md"
        assert results[0].confidence == "high"  # 89 day gap > 30*2

    async def test_returns_empty_when_no_stale(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []

        mock_pool = _mock_pool_with_conn(mock_conn)
        search_index = MagicMock()
        search_index._pool = mock_pool

        results = await detect_stale_docs(search_index, "org/repo")

        assert results == []

    async def test_medium_confidence_for_small_gap(self):
        now = datetime.now(UTC)
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "path": "docs/specs/api.md",
                "title": "API Spec",
                "last_doc_change_at": now - timedelta(days=35),
                "last_code_change_at": now - timedelta(days=1),
                "stale_since": now - timedelta(days=5),
            },
        ]

        mock_pool = _mock_pool_with_conn(mock_conn)
        search_index = MagicMock()
        search_index._pool = mock_pool

        results = await detect_stale_docs(search_index, "org/repo")

        assert len(results) == 1
        assert results[0].confidence == "medium"  # 34 day gap < 30*2


class TestAssessStaleness:
    async def test_returns_true_when_client_unavailable(self):
        result = await assess_staleness(None, "doc content", "code changes")
        assert result is True

    async def test_returns_true_when_client_not_available(self):
        mock_client = MagicMock()
        mock_client.is_available = False
        result = await assess_staleness(mock_client, "doc content", "code changes")
        assert result is True
