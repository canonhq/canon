"""Tests for the on_issues GitHub webhook handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from canon.github.handlers.on_issues import on_issues
from canon.webhooks.processor import ProcessResult


def _make_payload(
    action: str = "closed",
    number: int = 42,
    state: str = "closed",
    labels: list[str] | None = None,
    owner: str = "test-org",
    repo: str = "test-repo",
) -> dict:
    return {
        "action": action,
        "issue": {
            "number": number,
            "state": state,
            "labels": [{"name": lb} for lb in (labels or [])],
        },
        "repository": {
            "name": repo,
            "owner": {"login": owner},
        },
    }


class TestOnIssues:
    @pytest.mark.asyncio
    async def test_ignores_irrelevant_actions(self):
        client = AsyncMock()
        await on_issues(client, _make_payload(action="edited"))
        # No processing should occur for "edited" action

    @pytest.mark.asyncio
    async def test_processes_closed_event(self):
        client = AsyncMock()
        mock_result = ProcessResult(
            processed=True,
            old_state="todo",
            new_state="done",
        )

        with patch(
            "canon.github.handlers.on_issues.process_ticket_event",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_process:
            await on_issues(client, _make_payload(action="closed", state="closed"))

        mock_process.assert_called_once()
        event = mock_process.call_args[0][1]
        assert event.system == "github"
        assert event.ticket_id == "42"
        assert event.github_state == "closed"
        assert event.owner == "test-org"
        assert event.repo == "test-repo"

    @pytest.mark.asyncio
    async def test_extracts_labels(self):
        client = AsyncMock()
        mock_result = ProcessResult(processed=True)

        with patch(
            "canon.github.handlers.on_issues.process_ticket_event",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_process:
            await on_issues(
                client,
                _make_payload(
                    action="labeled",
                    state="open",
                    labels=["specwright:in-progress", "bug"],
                ),
            )

        event = mock_process.call_args[0][1]
        assert event.github_labels == ["specwright:in-progress", "bug"]

    @pytest.mark.asyncio
    async def test_skips_missing_data(self):
        client = AsyncMock()
        payload = {"action": "closed", "issue": {}, "repository": {}}

        with patch(
            "canon.github.handlers.on_issues.process_ticket_event",
            new_callable=AsyncMock,
        ) as mock_process:
            await on_issues(client, payload)

        mock_process.assert_not_called()
