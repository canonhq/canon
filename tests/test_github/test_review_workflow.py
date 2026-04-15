"""Tests for review_status auto-advancement on approved PR merge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from canon.github.handlers.on_pull_request_merged import on_pull_request_merged


def _make_payload(*, head_ref: str = "feature/update-spec") -> dict:
    return {
        "pull_request": {
            "number": 99,
            "merged": True,
            "title": "Update spec docs",
            "html_url": "https://github.com/acme/repo/pull/99",
            "base": {"ref": "main"},
            "head": {"ref": head_ref},
            "user": {"login": "dev"},
            "labels": [],
        },
        "repository": {
            "owner": {"login": "acme"},
            "name": "repo",
        },
    }


SPEC_CONTENT_DRAFT = """---
title: Test Spec
status: draft
owner: alice
team: platform
review_status: draft
---

## 1. Section One

Content.
"""

SPEC_CONTENT_NO_REVIEW = """---
title: Test Spec
status: draft
owner: alice
team: platform
---

## 1. Section One

Content.
"""

SPEC_CONTENT_APPROVED = """---
title: Test Spec
status: draft
owner: alice
team: platform
review_status: approved
---

## 1. Section One

Content.
"""


CANON_YAML = """
team: platform
specs:
  require_review: true
agents:
  doc_updates: true
"""


def _make_client(
    *,
    spec_content: str = SPEC_CONTENT_DRAFT,
    pr_files: list[dict] | None = None,
    reviews: list[dict] | None = None,
    comments: list[dict] | None = None,
) -> MagicMock:
    client = MagicMock()

    async def _get_file(owner, repo, path, ref=None):
        if path.endswith(".md"):
            return (spec_content, "sha123")
        if path in ("CANON.yaml", "SPECWRIGHT.yaml"):
            return (CANON_YAML, "sha456")
        raise FileNotFoundError(path)

    client.get_file_content = AsyncMock(side_effect=_get_file)
    client.list_pull_files = AsyncMock(
        return_value=pr_files or [{"filename": "docs/specs/test.md", "status": "modified"}]
    )
    client.list_pull_reviews = AsyncMock(
        return_value=reviews or [{"state": "APPROVED", "user": {"login": "reviewer"}}]
    )
    client.create_or_update_file = AsyncMock(return_value={})
    client.list_issue_comments = AsyncMock(return_value=comments or [])
    client.list_directory = AsyncMock(return_value=[])
    client.create_comment = AsyncMock(return_value={})
    client.upsert_bot_comment = AsyncMock(return_value=None)
    return client


def _find_review_status_update_calls(client: MagicMock) -> list:
    """Find create_or_update_file calls that update review_status to approved."""
    update_calls = []
    for call in client.create_or_update_file.call_args_list:
        # Args: (owner, repo, path, content, message, sha, ...)
        args = call[0]
        if len(args) >= 4:
            content = args[3]
            if "review_status: approved" in content:
                update_calls.append(call)
    return update_calls


class TestReviewStatusAdvancement:
    @pytest.mark.asyncio
    async def test_advances_draft_to_approved_on_approved_merge(self):
        client = _make_client(spec_content=SPEC_CONTENT_DRAFT)
        payload = _make_payload()

        await on_pull_request_merged(client, payload)

        update_calls = _find_review_status_update_calls(client)
        assert len(update_calls) >= 1
        # Verify the content arg contains the updated frontmatter
        content_arg = update_calls[0][0][3]
        assert "review_status: approved" in content_arg

    @pytest.mark.asyncio
    async def test_advances_none_review_to_approved(self):
        client = _make_client(spec_content=SPEC_CONTENT_NO_REVIEW)
        payload = _make_payload()

        await on_pull_request_merged(client, payload)

        update_calls = _find_review_status_update_calls(client)
        assert len(update_calls) >= 1

    @pytest.mark.asyncio
    async def test_skips_already_approved(self):
        client = _make_client(spec_content=SPEC_CONTENT_APPROVED)
        payload = _make_payload()

        await on_pull_request_merged(client, payload)

        update_calls = _find_review_status_update_calls(client)
        assert len(update_calls) == 0

    @pytest.mark.asyncio
    async def test_skips_when_no_approval_reviews(self):
        client = _make_client(
            spec_content=SPEC_CONTENT_DRAFT,
            reviews=[{"state": "COMMENTED", "user": {"login": "reviewer"}}],
        )
        payload = _make_payload()

        await on_pull_request_merged(client, payload)

        update_calls = _find_review_status_update_calls(client)
        assert len(update_calls) == 0

    @pytest.mark.asyncio
    async def test_skips_when_no_spec_files_changed(self):
        client = _make_client(
            pr_files=[{"filename": "src/main.py", "status": "modified"}],
        )
        payload = _make_payload()

        await on_pull_request_merged(client, payload)

        update_calls = _find_review_status_update_calls(client)
        assert len(update_calls) == 0
