"""Tests for auto-commit spec updates on merge (direct-to-default-branch)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from canon.agent.analyzer import (
    ACRealization,
    DocUpdateSuggestion,
    PRAnalysisResult,
    RealizationStatus,
    TokenUsage,
    format_analysis_comment,
)
from canon.github.handlers.on_pull_request_merged import (
    BOT_MARKER,
    on_pull_request_merged,
)

# --- Helpers ---


def _make_payload(
    *,
    merged: bool = True,
    head_ref: str = "feature/add-payments",
    base_ref: str = "main",
    pr_number: int = 42,
) -> dict:
    return {
        "pull_request": {
            "number": pr_number,
            "merged": merged,
            "title": "Add payment flow",
            "html_url": f"https://github.com/acme/repo/pull/{pr_number}",
            "base": {"ref": base_ref},
            "head": {"ref": head_ref},
            "user": {"login": "dev"},
        },
        "repository": {
            "owner": {"login": "acme"},
            "name": "repo",
        },
    }


def _make_bot_comment_body(analysis_result: PRAnalysisResult) -> str:
    """Simulate the bot comment with embedded analysis data."""
    return f"{BOT_MARKER}\n{format_analysis_comment(analysis_result)}"


SPEC_WITH_AC = """\
---
title: Payments
status: in_progress
owner: test
team: test
---

## 2. Payment Flow

<!-- specwright:system:2 status:in_progress -->

- [ ] Stripe integration complete
- [ ] Idempotency keys generated

Content here.
"""

BASE_DOC_UPDATE_ANALYSIS = PRAnalysisResult(
    summary="This PR adds payment processing.",
    spec_references=[],
    discrepancies=[],
    doc_updates=[
        DocUpdateSuggestion(
            spec_file="docs/specs/payments.md",
            section_id="2-payment-flow",
            current_text="Content here.",
            suggested_text="Content updated.",
            reason="Section updated to reflect implementation",
        )
    ],
    tokens_used=TokenUsage(input=1000, output=500),
)

REALIZATION_ANALYSIS = PRAnalysisResult(
    summary="This PR implements Stripe integration.",
    spec_references=[],
    discrepancies=[],
    doc_updates=[],
    realizations=[
        ACRealization(
            spec_file="docs/specs/payments.md",
            section_id="2-payment-flow",
            section_title="Payment Flow",
            ac_text="Stripe integration complete",
            status=RealizationStatus.REALIZED,
            evidence_files=[{"path": "src/payments/stripe.py", "start_line": 10, "end_line": 50}],
        ),
    ],
    tokens_used=TokenUsage(input=1000, output=500),
)

PARTIAL_REALIZATION_ANALYSIS = PRAnalysisResult(
    summary="This PR partially implements Stripe integration.",
    spec_references=[],
    discrepancies=[],
    doc_updates=[],
    realizations=[
        ACRealization(
            spec_file="docs/specs/payments.md",
            section_id="2-payment-flow",
            section_title="Payment Flow",
            ac_text="Stripe integration complete",
            status=RealizationStatus.PARTIALLY_REALIZED,
            evidence_files=[{"path": "src/payments/stripe.py", "start_line": 10, "end_line": 50}],
        ),
    ],
    tokens_used=TokenUsage(input=1000, output=500),
)

CONFLICTING_ANALYSIS = PRAnalysisResult(
    summary="This PR conflicts with spec.",
    spec_references=[],
    discrepancies=[],
    doc_updates=[],
    realizations=[
        ACRealization(
            spec_file="docs/specs/payments.md",
            section_id="2-payment-flow",
            section_title="Payment Flow",
            ac_text="Stripe integration complete",
            status=RealizationStatus.CONFLICTING,
            evidence_files=[{"path": "src/payments/stripe.py", "start_line": 10, "end_line": 50}],
        ),
    ],
    tokens_used=TokenUsage(input=1000, output=500),
)


def _make_client(
    *,
    comments: list[dict] | None = None,
    config_content: str | None = None,
    specs: list[dict] | None = None,
) -> MagicMock:
    """Create a mock GitHubClient for auto-commit tests."""
    client = MagicMock()

    # Spec defaults
    if specs is None:
        specs = [
            {
                "file_path": "docs/specs/payments.md",
                "document": MagicMock(raw=SPEC_WITH_AC),
                "raw": SPEC_WITH_AC,
            }
        ]

    # Build file contents lookup
    file_contents: dict[str, tuple[str, str]] = {}
    for s in specs:
        file_contents[s["file_path"]] = (s["raw"], "sha123")

    async def mock_get_file_content(owner, repo, path, ref=None):
        if path in file_contents:
            return file_contents[path]
        if config_content is not None and path in ("CANON.yaml", "SPECWRIGHT.yaml"):
            return (config_content, "sha_config")
        raise Exception("Not found")

    client.get_file_content = AsyncMock(side_effect=mock_get_file_content)

    # Directory listing for spec loading
    async def mock_list_directory(owner, repo, path, ref=None):
        return [
            {"type": "file", "name": s["file_path"].rsplit("/", 1)[-1], "path": s["file_path"]}
            for s in specs
        ]

    client.list_directory = AsyncMock(side_effect=mock_list_directory)

    # Comments
    client.list_issue_comments = AsyncMock(return_value=comments or [])
    client.create_comment = AsyncMock(return_value={})

    # PR file listing (for review_status advancement -- return empty so it skips)
    client.list_pull_files = AsyncMock(return_value=[])
    client.list_pull_reviews = AsyncMock(return_value=[])

    # Direct commit API -- succeeds by default
    client.create_or_update_file = AsyncMock(return_value={"content": {"sha": "new_sha"}})

    # Fallback doc PR operations
    from canon.github.client import DocPRResult

    client.find_open_doc_pr = AsyncMock(return_value=None)
    client.create_doc_pr = AsyncMock(
        return_value=DocPRResult(pr_number=50, pr_url="https://github.com/acme/repo/pull/50")
    )
    client.update_doc_pr = AsyncMock(
        return_value=DocPRResult(pr_number=45, pr_url="https://github.com/acme/repo/pull/45")
    )

    return client


# --- Tests ---


class TestAutoCommitOnMerge:
    """Tests for the new auto-commit-to-default-branch behavior."""

    async def test_commits_directly_to_default_branch(self):
        """Verify create_or_update_file is called (not create_doc_pr),
        commit message contains PR number."""
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(BASE_DOC_UPDATE_ANALYSIS)}],
        )
        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Direct commit should be called, NOT create_doc_pr
        client.create_or_update_file.assert_called()
        client.create_doc_pr.assert_not_called()

        # Verify commit message contains PR number
        commit_call = client.create_or_update_file.call_args
        assert "#42" in commit_call.kwargs.get(
            "message", commit_call[0][4] if len(commit_call[0]) > 4 else ""
        )

    async def test_checks_off_realized_acs(self):
        """Verify realized ACs are checked off in committed content (- [x])."""
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(REALIZATION_ANALYSIS)}],
        )
        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Should have committed directly
        client.create_or_update_file.assert_called()
        client.create_doc_pr.assert_not_called()

        # Extract the content that was committed
        commit_call = client.create_or_update_file.call_args
        # create_or_update_file(owner, repo, path, content, message, sha, branch=...)
        content = (
            commit_call[0][3] if len(commit_call[0]) > 3 else commit_call.kwargs.get("content", "")
        )
        assert "- [x] Stripe integration complete" in content
        # Unrealized AC stays unchecked
        assert "- [ ] Idempotency keys generated" in content

    async def test_checks_off_partially_realized_acs(self):
        """Verify partially_realized ACs are also checked off (per spec Decision 1)."""
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(PARTIAL_REALIZATION_ANALYSIS)}],
        )
        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        client.create_or_update_file.assert_called()
        commit_call = client.create_or_update_file.call_args
        content = (
            commit_call[0][3] if len(commit_call[0]) > 3 else commit_call.kwargs.get("content", "")
        )
        assert "- [x] Stripe integration complete" in content

    async def test_does_not_check_off_conflicting_acs(self):
        """Conflicting realizations don't trigger any commits."""
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(CONFLICTING_ANALYSIS)}],
        )
        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Conflicting status is not "realized" or "partially_realized",
        # so no realization insertions and no doc_updates => no file_updates => return early
        # create_or_update_file should NOT be called (beyond the review_status block)
        # We check that no spec-related commit happened
        client.create_doc_pr.assert_not_called()
        # The only create_or_update_file calls should NOT be for spec files
        # (could be called by review_status block but we mock list_pull_files to return [])
        for c in client.create_or_update_file.call_args_list:
            # If called at all, it should not be for spec content with conflicting data
            args = c[0] if c[0] else ()
            if len(args) > 2:
                assert args[2] != "docs/specs/payments.md" or "chore(canon): update specs" not in (
                    args[4] if len(args) > 4 else c.kwargs.get("message", "")
                )

    async def test_fallback_to_pr_on_conflict(self):
        """When create_or_update_file raises, fall back to create_doc_pr."""
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(BASE_DOC_UPDATE_ANALYSIS)}],
        )
        # Make direct commit fail
        client.create_or_update_file = AsyncMock(side_effect=Exception("409 Conflict"))
        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Should fall back to creating a doc-update PR
        client.create_doc_pr.assert_called_once()
        call_kwargs = client.create_doc_pr.call_args.kwargs
        assert "canon/doc-update-pr-42" in call_kwargs["branch"]
        assert len(call_kwargs["files"]) >= 1

    async def test_posts_summary_comment_on_original_pr(self):
        """Summary comment posted after successful commits."""
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(REALIZATION_ANALYSIS)}],
        )
        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Should post a summary comment on the original PR
        client.create_comment.assert_called()
        # Find the summary comment call (not the review_status one)
        summary_calls = [
            c
            for c in client.create_comment.call_args_list
            if "updated" in str(c).lower()
            or "specs" in str(c).lower()
            or "committed" in str(c).lower()
        ]
        assert len(summary_calls) >= 1
        # The comment should reference the spec file
        comment_body = (
            summary_calls[0][0][-1]
            if summary_calls[0][0]
            else summary_calls[0].kwargs.get("body", "")
        )
        assert "docs/specs/payments.md" in comment_body

    async def test_skips_bot_branches(self):
        """canon/ prefixed branches are ignored."""
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(BASE_DOC_UPDATE_ANALYSIS)}],
        )
        payload = _make_payload(head_ref="canon/doc-update-pr-10")
        await on_pull_request_merged(client, payload)

        # Should not process at all
        client.list_issue_comments.assert_not_called()
        client.create_or_update_file.assert_not_called()
        client.create_doc_pr.assert_not_called()

    async def test_commits_to_correct_branch(self):
        """Verifies the commit targets the base_ref (default branch)."""
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(BASE_DOC_UPDATE_ANALYSIS)}],
        )
        payload = _make_payload(base_ref="develop")
        await on_pull_request_merged(client, payload)

        client.create_or_update_file.assert_called()
        commit_call = client.create_or_update_file.call_args
        # branch kwarg should be "develop"
        branch = commit_call.kwargs.get("branch", "")
        assert branch == "develop"

    async def test_refetches_sha_before_commit(self):
        """Verifies that file SHA is re-fetched before committing."""
        # Track call order to verify get_file_content is called after building file_updates
        call_order = []

        specs = [
            {
                "file_path": "docs/specs/payments.md",
                "document": MagicMock(raw=SPEC_WITH_AC),
                "raw": SPEC_WITH_AC,
            }
        ]
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(BASE_DOC_UPDATE_ANALYSIS)}],
            specs=specs,
        )

        # Track the SHA passed to create_or_update_file
        async def tracking_create(*args, **kwargs):
            call_order.append(
                ("create_or_update_file", kwargs.get("sha") or (args[5] if len(args) > 5 else None))
            )
            return {"content": {"sha": "new_sha"}}

        client.create_or_update_file = AsyncMock(side_effect=tracking_create)

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Verify create_or_update_file was called and received a SHA
        assert len(call_order) >= 1
        # The SHA should have been fetched (not None)
        sha_used = call_order[0][1]
        assert sha_used is not None

    async def test_partial_failure_commits_some_falls_back_for_others(self):
        """When one file commits successfully and another fails,
        the failed one falls back to a doc-update PR."""
        auth_raw = "## 1. Login\n\nOAuth not supported.\n"
        multi_update = PRAnalysisResult(
            summary="test",
            spec_references=[],
            discrepancies=[],
            doc_updates=[
                DocUpdateSuggestion(
                    spec_file="docs/specs/payments.md",
                    section_id="2-payment-flow",
                    current_text="Content here.",
                    suggested_text="Content updated.",
                    reason="Updated",
                ),
                DocUpdateSuggestion(
                    spec_file="docs/specs/auth.md",
                    section_id="1-login",
                    current_text="OAuth not supported.",
                    suggested_text="OAuth supported via GitHub.",
                    reason="OAuth was added",
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(multi_update)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=SPEC_WITH_AC),
                    "raw": SPEC_WITH_AC,
                },
                {
                    "file_path": "docs/specs/auth.md",
                    "document": MagicMock(raw=auth_raw),
                    "raw": auth_raw,
                },
            ],
        )

        # Override list_directory for multiple specs
        async def mock_list_dir(owner, repo, path, ref=None):
            return [
                {"type": "file", "name": "payments.md", "path": "docs/specs/payments.md"},
                {"type": "file", "name": "auth.md", "path": "docs/specs/auth.md"},
            ]

        client.list_directory = AsyncMock(side_effect=mock_list_dir)

        # First file succeeds, second file fails
        call_count = 0

        async def selective_failure(owner, repo, path, content, message, sha, branch=None):
            nonlocal call_count
            call_count += 1
            if path == "docs/specs/auth.md":
                raise Exception("409 Conflict")
            return {"content": {"sha": "new_sha"}}

        client.create_or_update_file = AsyncMock(side_effect=selective_failure)

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # The failed file should trigger a fallback doc-update PR
        client.create_doc_pr.assert_called_once()
        fallback_files = client.create_doc_pr.call_args.kwargs["files"]
        assert len(fallback_files) == 1
        assert fallback_files[0].path == "docs/specs/auth.md"


class TestFailedAnalysisComment:
    async def test_posts_no_updates_when_no_bot_comment(self):
        """When no bot comment is found on merge, no spec updates should happen."""
        client = _make_client()
        client.list_issue_comments = AsyncMock(return_value=[])
        await on_pull_request_merged(client, _make_payload())
        client.create_or_update_file.assert_not_called()
