"""Tests for stale issue reporter."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from canon.stale.detector import StaleDoc
from canon.stale.issue_reporter import (
    STALE_MARKER,
    format_stale_issue_body,
    upsert_stale_issue,
)


class TestFormatStaleIssueBody:
    def test_includes_marker(self):
        body = format_stale_issue_body([])
        assert STALE_MARKER in body

    def test_includes_table_headers(self):
        body = format_stale_issue_body([])
        assert "| Document |" in body

    def test_includes_stale_docs(self):
        now = datetime(2026, 2, 1, tzinfo=UTC)
        docs = [
            StaleDoc(
                repo="org/repo",
                path="docs/specs/auth.md",
                title="Auth",
                last_doc_change=now,
                last_code_change=now,
                stale_since=now,
                confidence="high",
            ),
        ]
        body = format_stale_issue_body(docs)
        assert "`docs/specs/auth.md`" in body
        assert "2026-02-01" in body
        assert ":red_circle:" in body

    def test_medium_confidence_badge(self):
        docs = [
            StaleDoc(
                repo="org/repo",
                path="docs/api.md",
                title="API",
                confidence="medium",
            ),
        ]
        body = format_stale_issue_body(docs)
        assert ":yellow_circle:" in body


class TestUpsertStaleIssue:
    async def test_creates_issue_when_none_exists(self):
        mock_client = AsyncMock()
        mock_client.list_issues.return_value = []
        mock_client.create_issue.return_value = {"number": 99}

        docs = [
            StaleDoc(repo="org/repo", path="docs/auth.md", title="Auth"),
        ]

        result = await upsert_stale_issue(mock_client, "org", "repo", docs)

        assert result == 99
        mock_client.create_issue.assert_awaited_once()
        call_kwargs = mock_client.create_issue.call_args
        assert "Stale documentation" in call_kwargs[1]["title"]

    async def test_updates_existing_issue(self):
        mock_client = AsyncMock()
        mock_client.list_issues.return_value = [
            {"number": 42, "body": f"old content\n{STALE_MARKER}\nmore"},
        ]

        docs = [
            StaleDoc(repo="org/repo", path="docs/auth.md", title="Auth"),
        ]

        result = await upsert_stale_issue(mock_client, "org", "repo", docs)

        assert result == 42
        mock_client.update_issue.assert_awaited_once()

    async def test_closes_issue_when_no_stale_docs(self):
        mock_client = AsyncMock()
        mock_client.list_issues.return_value = [
            {"number": 42, "body": f"old content\n{STALE_MARKER}"},
        ]

        result = await upsert_stale_issue(mock_client, "org", "repo", [])

        assert result == 42
        call_kwargs = mock_client.update_issue.call_args
        assert call_kwargs[1]["state"] == "closed"

    async def test_noop_when_no_stale_docs_and_no_issue(self):
        mock_client = AsyncMock()
        mock_client.list_issues.return_value = []

        result = await upsert_stale_issue(mock_client, "org", "repo", [])

        assert result is None
        mock_client.create_issue.assert_not_awaited()
