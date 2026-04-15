"""Tests for webhook event processor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canon.parser.parse import parse_spec
from canon.webhooks.processor import (
    TicketEvent,
    _find_linked_section,
    _resolve_new_state,
    process_ticket_event,
)

SPEC_WITH_GITHUB_TICKET = """\
---
title: Test Spec
status: draft
owner: test
team: test
ticket_project: test-org/test-repo
---

## 1. Background

<!-- specwright:system:1 status:done -->

Background content.

## 2. Feature A

<!-- specwright:system:2 status:todo -->
<!-- specwright:ticket:github:42 -->

Feature A content.

## 3. Feature B

<!-- specwright:system:3 status:in_progress -->
<!-- specwright:ticket:jira:PROJ-123 -->

Feature B content.
"""


SPEC_WITH_LINEAR_TICKET = """\
---
title: Linear Spec
status: draft
owner: test
team: test
---

## 1. Task

<!-- specwright:system:1 status:in_progress -->
<!-- specwright:ticket:linear:LIN-abc -->

Task content.
"""


class TestFindLinkedSection:
    def test_finds_github_ticket(self):
        result = parse_spec(SPEC_WITH_GITHUB_TICKET)
        section = _find_linked_section(result.document, "github", "42")
        assert section is not None
        assert section.title == "Feature A"
        assert section.ticket_link.ticket_id == "42"

    def test_finds_jira_ticket(self):
        result = parse_spec(SPEC_WITH_GITHUB_TICKET)
        section = _find_linked_section(result.document, "jira", "PROJ-123")
        assert section is not None
        assert section.title == "Feature B"

    def test_returns_none_for_missing_ticket(self):
        result = parse_spec(SPEC_WITH_GITHUB_TICKET)
        section = _find_linked_section(result.document, "github", "999")
        assert section is None

    def test_returns_none_for_wrong_system(self):
        result = parse_spec(SPEC_WITH_GITHUB_TICKET)
        section = _find_linked_section(result.document, "linear", "42")
        assert section is None


class TestResolveNewState:
    def test_github_closed_resolves_to_done(self):
        event = TicketEvent(
            system="github",
            ticket_id="42",
            raw_status="closed",
            github_state="closed",
            github_labels=[],
        )
        state = _resolve_new_state(event, None)
        assert state == "done"

    def test_github_open_resolves_to_todo(self):
        event = TicketEvent(
            system="github",
            ticket_id="42",
            raw_status="open",
            github_state="open",
            github_labels=[],
        )
        state = _resolve_new_state(event, None)
        assert state == "todo"

    def test_github_label_overrides_state(self):
        event = TicketEvent(
            system="github",
            ticket_id="42",
            raw_status="open",
            github_state="open",
            github_labels=["specwright:in-progress"],
        )
        state = _resolve_new_state(event, None)
        assert state == "in_progress"

    def test_jira_done_category(self):
        event = TicketEvent(
            system="jira",
            ticket_id="PROJ-1",
            raw_status="done",
        )
        state = _resolve_new_state(event, None)
        assert state == "done"

    def test_linear_completed(self):
        event = TicketEvent(
            system="linear",
            ticket_id="LIN-1",
            raw_status="completed",
        )
        state = _resolve_new_state(event, None)
        assert state == "done"


class TestProcessTicketEvent:
    @pytest.mark.asyncio
    async def test_missing_owner_repo(self):
        client = MagicMock()
        event = TicketEvent(system="github", ticket_id="42", raw_status="closed")
        result = await process_ticket_event(client, event)
        assert result.processed is False
        assert "Missing owner/repo" in result.error

    @pytest.mark.asyncio
    async def test_idempotent_no_change(self):
        """When the spec section already has the target state, no commit is made."""
        mock_client = AsyncMock()

        # Mock load_repo_config
        mock_config = MagicMock()
        mock_config.ticket_system = None
        mock_config.project_key = None
        mock_config.ticket_mapping = None
        mock_config.specs.doc_paths = ["docs/specs/*.md"]

        # Mock list_directory
        mock_client.list_directory = AsyncMock(
            return_value=[
                {"type": "file", "name": "test.md", "path": "docs/specs/test.md"},
            ]
        )

        # The spec has section 2 with status:todo linked to github:42
        # If the event says "open" (→ todo), no change should occur
        mock_client.get_file_content = AsyncMock(return_value=(SPEC_WITH_GITHUB_TICKET, "sha123"))
        mock_client.get_default_branch = AsyncMock(return_value="main")

        event = TicketEvent(
            system="github",
            ticket_id="42",
            raw_status="open",
            github_state="open",
            github_labels=[],
            owner="test-org",
            repo="test-repo",
        )

        with (
            patch(
                "canon.webhooks.processor.load_repo_config",
                return_value=mock_config,
            ),
            patch(
                "canon.webhooks.processor.load_org_mapping_config",
                return_value=None,
            ),
        ):
            result = await process_ticket_event(mock_client, event)

        assert result.processed is True
        assert result.old_state == "todo"
        assert result.new_state == "todo"
        # No commit should have been made
        mock_client.create_or_update_file.assert_not_called()
        # Default branch should not be fetched on the idempotent path
        mock_client.get_default_branch.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_status_change(self):
        """When the ticket status changes, the spec is updated and committed."""
        mock_client = AsyncMock()

        mock_config = MagicMock()
        mock_config.ticket_system = None
        mock_config.project_key = None
        mock_config.ticket_mapping = None
        mock_config.specs.doc_paths = ["docs/specs/*.md"]

        mock_client.list_directory = AsyncMock(
            return_value=[
                {"type": "file", "name": "test.md", "path": "docs/specs/test.md"},
            ]
        )
        mock_client.get_file_content = AsyncMock(return_value=(SPEC_WITH_GITHUB_TICKET, "sha123"))
        mock_client.get_default_branch = AsyncMock(return_value="main")
        mock_client.create_or_update_file = AsyncMock()

        event = TicketEvent(
            system="github",
            ticket_id="42",
            raw_status="closed",
            github_state="closed",
            github_labels=[],
            owner="test-org",
            repo="test-repo",
        )

        with (
            patch(
                "canon.webhooks.processor.load_repo_config",
                return_value=mock_config,
            ),
            patch(
                "canon.webhooks.processor.load_org_mapping_config",
                return_value=None,
            ),
        ):
            result = await process_ticket_event(mock_client, event)

        assert result.processed is True
        assert result.old_state == "todo"
        assert result.new_state == "done"
        assert result.spec_file == "docs/specs/test.md"
        mock_client.create_or_update_file.assert_called_once()

        # Verify the commit message
        call_args = mock_client.create_or_update_file.call_args
        commit_msg = (
            call_args.args[4] if len(call_args.args) > 4 else call_args.kwargs.get("message", "")
        )
        assert "github ticket 42" in commit_msg
        assert "done" in commit_msg

    @pytest.mark.asyncio
    async def test_no_linked_section_found(self):
        """When no spec section links to the ticket, processing reports not found."""
        mock_client = AsyncMock()

        mock_config = MagicMock()
        mock_config.ticket_system = None
        mock_config.project_key = None
        mock_config.ticket_mapping = None
        mock_config.specs.doc_paths = ["docs/specs/*.md"]

        mock_client.list_directory = AsyncMock(
            return_value=[
                {"type": "file", "name": "test.md", "path": "docs/specs/test.md"},
            ]
        )
        mock_client.get_file_content = AsyncMock(return_value=(SPEC_WITH_GITHUB_TICKET, "sha123"))

        event = TicketEvent(
            system="github",
            ticket_id="999",  # Not linked in the spec
            raw_status="closed",
            github_state="closed",
            github_labels=[],
            owner="test-org",
            repo="test-repo",
        )

        with (
            patch(
                "canon.webhooks.processor.load_repo_config",
                return_value=mock_config,
            ),
            patch(
                "canon.webhooks.processor.load_org_mapping_config",
                return_value=None,
            ),
        ):
            result = await process_ticket_event(mock_client, event)

        assert result.processed is False
        assert "No linked spec section" in result.error

    @pytest.mark.asyncio
    async def test_retries_on_stale_sha_conflict(self):
        """On 409 Conflict, processor re-fetches file and retries the commit."""
        mock_client = AsyncMock()

        mock_config = MagicMock()
        mock_config.ticket_system = None
        mock_config.project_key = None
        mock_config.ticket_mapping = None
        mock_config.specs.doc_paths = ["docs/specs/*.md"]

        mock_client.list_directory = AsyncMock(
            return_value=[
                {"type": "file", "name": "test.md", "path": "docs/specs/test.md"},
            ]
        )
        # First call returns sha1, second call (after conflict) returns sha2
        mock_client.get_file_content = AsyncMock(
            side_effect=[
                (SPEC_WITH_GITHUB_TICKET, "sha1"),
                (SPEC_WITH_GITHUB_TICKET, "sha2"),
            ]
        )
        mock_client.get_default_branch = AsyncMock(return_value="main")

        # First commit fails with 409, second succeeds
        from httpx import HTTPStatusError, Request, Response

        conflict_response = Response(409, request=Request("PUT", "https://api.github.com/"))
        mock_client.create_or_update_file = AsyncMock(
            side_effect=[
                HTTPStatusError(
                    "409 Conflict", request=conflict_response.request, response=conflict_response
                ),
                None,  # Success on retry
            ]
        )

        event = TicketEvent(
            system="github",
            ticket_id="42",
            raw_status="closed",
            github_state="closed",
            github_labels=[],
            owner="test-org",
            repo="test-repo",
        )

        with (
            patch(
                "canon.webhooks.processor.load_repo_config",
                return_value=mock_config,
            ),
            patch(
                "canon.webhooks.processor.load_org_mapping_config",
                return_value=None,
            ),
        ):
            result = await process_ticket_event(mock_client, event)

        assert result.processed is True
        assert result.new_state == "done"
        # Should have committed twice (first failed, second succeeded)
        assert mock_client.create_or_update_file.call_count == 2
        # Second commit should use sha2
        second_call = mock_client.create_or_update_file.call_args_list[1]
        assert second_call.args[5] == "sha2"  # file_sha argument

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self):
        """After exhausting retries on 409, returns infrastructure error."""
        mock_client = AsyncMock()

        mock_config = MagicMock()
        mock_config.ticket_system = None
        mock_config.project_key = None
        mock_config.ticket_mapping = None
        mock_config.specs.doc_paths = ["docs/specs/*.md"]

        mock_client.list_directory = AsyncMock(
            return_value=[
                {"type": "file", "name": "test.md", "path": "docs/specs/test.md"},
            ]
        )
        # Every re-fetch returns a new SHA but commit always fails
        mock_client.get_file_content = AsyncMock(
            side_effect=[
                (SPEC_WITH_GITHUB_TICKET, "sha1"),
                (SPEC_WITH_GITHUB_TICKET, "sha2"),
                (SPEC_WITH_GITHUB_TICKET, "sha3"),
                (SPEC_WITH_GITHUB_TICKET, "sha4"),
            ]
        )
        mock_client.get_default_branch = AsyncMock(return_value="main")

        from httpx import HTTPStatusError, Request, Response

        conflict_response = Response(409, request=Request("PUT", "https://api.github.com/"))
        conflict_err = HTTPStatusError(
            "409 Conflict", request=conflict_response.request, response=conflict_response
        )
        mock_client.create_or_update_file = AsyncMock(side_effect=conflict_err)

        event = TicketEvent(
            system="github",
            ticket_id="42",
            raw_status="closed",
            github_state="closed",
            github_labels=[],
            owner="test-org",
            repo="test-repo",
        )

        with (
            patch(
                "canon.webhooks.processor.load_repo_config",
                return_value=mock_config,
            ),
            patch(
                "canon.webhooks.processor.load_org_mapping_config",
                return_value=None,
            ),
        ):
            result = await process_ticket_event(mock_client, event)

        assert result.processed is False
        assert result.error_kind == "infrastructure"
        assert "409" in result.error or "conflict" in result.error.lower()
        # Should have attempted commit 3 times (initial + 2 retries)
        assert mock_client.create_or_update_file.call_count == 3
