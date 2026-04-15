"""Port of on-pull-request-merged tests — auto-commit on merge."""

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

# ─── Helpers ──────────────────────────────────────────


def _make_payload(
    *,
    merged: bool = True,
    head_ref: str = "feature/add-payments",
    comments: list[dict] | None = None,
) -> dict:
    return {
        "pull_request": {
            "number": 42,
            "merged": merged,
            "title": "Add payment flow",
            "html_url": "https://github.com/acme/repo/pull/42",
            "base": {"ref": "main"},
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


BASE_ANALYSIS = PRAnalysisResult(
    summary="This PR adds payment processing.",
    spec_references=[],
    discrepancies=[],
    doc_updates=[
        DocUpdateSuggestion(
            spec_file="docs/specs/payments.md",
            section_id="2-payment-flow",
            current_text="Payment flow is not yet implemented.",
            suggested_text="Payment flow is implemented via Stripe in src/payments/.",
            reason="Section updated to reflect implementation",
        )
    ],
    tokens_used=TokenUsage(input=1000, output=500),
)

SPEC_RAW = """---
title: Payments
status: { state: in_progress }
---

## 2. Payment Flow

Payment flow is not yet implemented.
"""


def _make_client(
    *,
    comments: list[dict] | None = None,
    config_content: str | None = None,
    specs: list[dict] | None = None,
    find_open_pr: object | None = None,
) -> MagicMock:
    """Create a mock GitHubClient."""
    client = MagicMock()

    # Config loading
    if config_content is not None:
        client.get_file_content = AsyncMock(return_value=(config_content, "sha123"))
    else:
        client.get_file_content = AsyncMock(side_effect=Exception("Not found"))

    # Comments
    client.list_issue_comments = AsyncMock(return_value=comments or [])
    client.create_comment = AsyncMock(return_value={})

    # Spec loading
    if specs is None:
        specs = [
            {
                "file_path": "docs/specs/payments.md",
                "document": MagicMock(raw=SPEC_RAW),
                "raw": SPEC_RAW,
            }
        ]

    async def mock_list_directory(owner, repo, path, ref=None):
        return [{"type": "file", "name": "payments.md", "path": "docs/specs/payments.md"}]

    client.list_directory = AsyncMock(side_effect=mock_list_directory)

    # get_file_content needs to handle CANON.yaml / SPECWRIGHT.yaml and spec file loads
    file_contents = {}
    for s in specs:
        file_contents[s["file_path"]] = (s["raw"], "sha123")

    async def mock_get_file_content(owner, repo, path, ref=None):
        if path in file_contents:
            return file_contents[path]
        if config_content is not None and path in ("CANON.yaml", "SPECWRIGHT.yaml"):
            return (config_content, "sha123")
        raise Exception("Not found")

    client.get_file_content = AsyncMock(side_effect=mock_get_file_content)

    # PR file listing (for review_status advancement)
    client.list_pull_files = AsyncMock(return_value=[])
    client.list_pull_reviews = AsyncMock(return_value=[])

    # Direct commit API (auto-commit path) -- succeeds by default
    client.create_or_update_file = AsyncMock(return_value={"content": {"sha": "new_sha"}})

    # Doc PR operations (fallback path)
    from canon.github.client import DocPRResult

    client.find_open_doc_pr = AsyncMock(return_value=find_open_pr)
    client.create_doc_pr = AsyncMock(
        return_value=DocPRResult(pr_number=50, pr_url="https://github.com/acme/repo/pull/50")
    )
    client.update_doc_pr = AsyncMock(
        return_value=DocPRResult(pr_number=45, pr_url="https://github.com/acme/repo/pull/45")
    )

    return client


# ─── Tests ────────────────────────────────────────────


class TestOnPullRequestMerged:
    async def test_skips_non_merged_prs(self):
        client = _make_client()
        payload = _make_payload(merged=False)
        await on_pull_request_merged(client, payload)
        client.list_issue_comments.assert_not_called()

    async def test_skips_canon_doc_update_prs(self):
        client = _make_client()
        payload = _make_payload(head_ref="canon/doc-update-pr-10")
        await on_pull_request_merged(client, payload)
        client.list_issue_comments.assert_not_called()

    async def test_skips_when_doc_updates_disabled(self):
        config_yaml = """
specs:
  auto_tickets: true
agents:
  doc_updates: false
  pr_analysis: true
"""
        client = _make_client(config_content=config_yaml)
        payload = _make_payload()
        await on_pull_request_merged(client, payload)
        client.create_doc_pr.assert_not_called()

    async def test_skips_when_no_bot_comment(self):
        client = _make_client(comments=[])
        payload = _make_payload()
        await on_pull_request_merged(client, payload)
        client.create_doc_pr.assert_not_called()

    async def test_skips_when_no_embedded_analysis(self):
        client = _make_client(comments=[{"id": 1, "body": f"{BOT_MARKER}\nJust a comment"}])
        payload = _make_payload()
        await on_pull_request_merged(client, payload)
        client.create_doc_pr.assert_not_called()

    async def test_skips_when_no_doc_updates_or_conflicts(self):
        no_updates = PRAnalysisResult(
            summary="test",
            spec_references=[],
            discrepancies=[],
            doc_updates=[],
            tokens_used=TokenUsage(input=100, output=50),
        )
        client = _make_client(comments=[{"id": 100, "body": _make_bot_comment_body(no_updates)}])
        payload = _make_payload()
        await on_pull_request_merged(client, payload)
        client.create_doc_pr.assert_not_called()

    async def test_auto_commits_doc_update(self):
        client = _make_client(comments=[{"id": 100, "body": _make_bot_comment_body(BASE_ANALYSIS)}])
        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Auto-commit path: create_or_update_file called, NOT create_doc_pr
        client.create_or_update_file.assert_called()
        client.create_doc_pr.assert_not_called()

        # Verify the committed content contains the expected update
        commit_call = client.create_or_update_file.call_args
        content = commit_call[0][3]
        assert "Payment flow is implemented via Stripe" in content
        # Commit message references PR number
        message = commit_call[0][4]
        assert "#42" in message

        # Should leave a summary comment on the original PR
        client.create_comment.assert_called_once()

    async def test_auto_commits_regardless_of_existing_doc_pr(self):
        """Auto-commit path commits directly; existing doc PRs are irrelevant."""
        from canon.github.client import DocPRResult

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(BASE_ANALYSIS)}],
            find_open_pr=DocPRResult(pr_number=45, pr_url="https://github.com/acme/repo/pull/45"),
        )
        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Auto-commit path is used — doc PR operations are NOT called
        client.create_or_update_file.assert_called()
        client.create_doc_pr.assert_not_called()
        client.update_doc_pr.assert_not_called()

    async def test_handles_commit_failure_gracefully(self):
        """When auto-commit fails, falls back to doc-update PR; when both fail, no crash."""
        client = _make_client(comments=[{"id": 100, "body": _make_bot_comment_body(BASE_ANALYSIS)}])
        client.create_or_update_file = AsyncMock(side_effect=Exception("409 Conflict"))
        client.create_doc_pr = AsyncMock(side_effect=Exception("Branch already exists"))
        payload = _make_payload()

        # Should not raise even when both paths fail
        await on_pull_request_merged(client, payload)

    async def test_doc_update_for_non_spec_file(self):
        """Doc updates targeting non-spec files fetch content and auto-commit."""
        non_spec_update = PRAnalysisResult(
            summary="test",
            spec_references=[],
            discrepancies=[],
            doc_updates=[
                DocUpdateSuggestion(
                    spec_file="docs/adrs/0001-auth.md",
                    section_id="decision",
                    current_text="We use session cookies.",
                    suggested_text="We use JWT tokens.",
                    reason="Auth method changed",
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        adr_raw = "## Decision\n\nWe use session cookies.\n"
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(non_spec_update)}],
        )

        # Override get_file_content to serve the ADR file
        async def mock_get_file_content(owner, repo, path, ref=None):
            if path == "docs/adrs/0001-auth.md":
                return (adr_raw, "sha456")
            if path in ("CANON.yaml", "SPECWRIGHT.yaml"):
                raise Exception("Not found")
            # For spec loading
            raise Exception("Not found")

        client.get_file_content = AsyncMock(side_effect=mock_get_file_content)
        # No specs in repo
        client.list_directory = AsyncMock(return_value=[])

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Auto-commit path used
        client.create_or_update_file.assert_called_once()
        commit_call = client.create_or_update_file.call_args
        assert commit_call[0][2] == "docs/adrs/0001-auth.md"
        assert "JWT tokens" in commit_call[0][3]
        client.create_doc_pr.assert_not_called()

    async def test_fetch_failure_for_non_spec_file(self):
        """Continues gracefully when a non-spec file fetch fails."""
        mixed_update = PRAnalysisResult(
            summary="test",
            spec_references=[],
            discrepancies=[],
            doc_updates=[
                DocUpdateSuggestion(
                    spec_file="docs/adrs/missing.md",
                    section_id="decision",
                    current_text="old",
                    suggested_text="new",
                    reason="Updated",
                ),
                DocUpdateSuggestion(
                    spec_file="docs/specs/payments.md",
                    section_id="2-payment-flow",
                    current_text="Payment flow is not yet implemented.",
                    suggested_text="Payment flow is implemented.",
                    reason="Updated",
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(mixed_update)}],
        )

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Should still auto-commit the spec file that succeeded
        client.create_or_update_file.assert_called_once()
        commit_call = client.create_or_update_file.call_args
        assert commit_call[0][2] == "docs/specs/payments.md"
        client.create_doc_pr.assert_not_called()

    async def test_handles_multiple_doc_updates(self):
        multi_update = PRAnalysisResult(
            summary="test",
            spec_references=[],
            discrepancies=[],
            doc_updates=[
                DocUpdateSuggestion(
                    spec_file="docs/specs/payments.md",
                    section_id="2-payment-flow",
                    current_text="Payment flow is not yet implemented.",
                    suggested_text="Payment flow is implemented.",
                    reason="Updated to reflect implementation",
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

        auth_raw = "## 1. Login\n\nOAuth not supported.\n"
        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(multi_update)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=SPEC_RAW),
                    "raw": SPEC_RAW,
                },
                {
                    "file_path": "docs/specs/auth.md",
                    "document": MagicMock(raw=auth_raw),
                    "raw": auth_raw,
                },
            ],
        )

        # Override list_directory and get_file_content for multiple specs
        async def mock_list_dir(owner, repo, path, ref=None):
            return [
                {"type": "file", "name": "payments.md", "path": "docs/specs/payments.md"},
                {"type": "file", "name": "auth.md", "path": "docs/specs/auth.md"},
            ]

        client.list_directory = AsyncMock(side_effect=mock_list_dir)

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # Auto-commit called once per file
        assert client.create_or_update_file.call_count == 2
        paths = sorted(c[0][2] for c in client.create_or_update_file.call_args_list)
        assert paths == ["docs/specs/auth.md", "docs/specs/payments.md"]
        client.create_doc_pr.assert_not_called()


class TestRealizationInMergedPR:
    """Tests for realization evidence comment insertion on merge."""

    SPEC_WITH_AC = """---
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

    @staticmethod
    def _get_committed_content(client, path="docs/specs/payments.md"):
        """Extract committed content from create_or_update_file calls."""
        for c in client.create_or_update_file.call_args_list:
            if c[0][2] == path:
                return c[0][3]
        raise AssertionError(f"No commit found for {path}")

    async def test_inserts_realization_comments_on_merge(self):
        """Realized ACs get evidence comments inserted via auto-commit."""
        analysis = PRAnalysisResult(
            summary="test",
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
                    evidence_files=[
                        {"path": "src/payments/stripe.py", "start_line": 10, "end_line": 50}
                    ],
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(analysis)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=self.SPEC_WITH_AC),
                    "raw": self.SPEC_WITH_AC,
                },
            ],
        )

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        client.create_or_update_file.assert_called_once()
        content = self._get_committed_content(client)
        assert "canon:realized-in:PR#42" in content
        assert "src/payments/stripe.py" in content
        # Realized AC should be checked off
        assert "- [x] Stripe integration complete" in content
        # Unrealized AC stays unchecked
        assert "- [ ] Idempotency keys generated" in content
        # Section still in_progress (not all ACs done)
        assert "status:in_progress" in content
        client.create_doc_pr.assert_not_called()

    async def test_skips_not_addressed_realizations(self):
        """Only 'realized' and 'partially_realized' produce evidence comments."""
        analysis = PRAnalysisResult(
            summary="test",
            spec_references=[],
            discrepancies=[],
            doc_updates=[],
            realizations=[
                ACRealization(
                    spec_file="docs/specs/payments.md",
                    section_id="2-payment-flow",
                    section_title="Payment Flow",
                    ac_text="Stripe integration complete",
                    status=RealizationStatus.NOT_ADDRESSED,
                ),
                ACRealization(
                    spec_file="docs/specs/payments.md",
                    section_id="2-payment-flow",
                    section_title="Payment Flow",
                    ac_text="Idempotency keys generated",
                    status=RealizationStatus.CONFLICTING,
                    evidence_files=[{"path": "src/pay.py", "start_line": 5}],
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(analysis)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=self.SPEC_WITH_AC),
                    "raw": self.SPEC_WITH_AC,
                },
            ],
        )

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        # No realizations qualify — no auto-commit or doc-update PR
        client.create_doc_pr.assert_not_called()

    async def test_partially_realized_checked_off(self):
        """Partially-realized ACs get evidence comments and are checked off (Decision 1)."""
        analysis = PRAnalysisResult(
            summary="test",
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
                    evidence_files=[
                        {"path": "src/payments/stripe.py", "start_line": 10, "end_line": 50}
                    ],
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(analysis)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=self.SPEC_WITH_AC),
                    "raw": self.SPEC_WITH_AC,
                },
            ],
        )

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        client.create_or_update_file.assert_called_once()
        content = self._get_committed_content(client)
        # Evidence comment inserted
        assert "canon:realized-in:PR#42" in content
        # Partially realized ACs are checked off per spec Decision 1
        assert "- [x] Stripe integration complete" in content
        client.create_doc_pr.assert_not_called()

    async def test_auto_advances_section_when_all_acs_realized(self):
        """Section status advances to done when all ACs are checked off."""
        analysis = PRAnalysisResult(
            summary="test",
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
                    evidence_files=[{"path": "src/stripe.py", "start_line": 1, "end_line": 10}],
                ),
                ACRealization(
                    spec_file="docs/specs/payments.md",
                    section_id="2-payment-flow",
                    section_title="Payment Flow",
                    ac_text="Idempotency keys generated",
                    status=RealizationStatus.REALIZED,
                    evidence_files=[{"path": "src/keys.py", "start_line": 1, "end_line": 5}],
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(analysis)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=self.SPEC_WITH_AC),
                    "raw": self.SPEC_WITH_AC,
                },
            ],
        )

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        client.create_or_update_file.assert_called_once()
        content = self._get_committed_content(client)
        # Both ACs checked off
        assert "- [x] Stripe integration complete" in content
        assert "- [x] Idempotency keys generated" in content
        # Section auto-advanced to done
        assert "status:done" in content
        assert "status:in_progress" not in content
        client.create_doc_pr.assert_not_called()

    async def test_no_advance_when_some_acs_unchecked(self):
        """Section stays in_progress when not all ACs are checked."""
        # Only one of two ACs realized
        analysis = PRAnalysisResult(
            summary="test",
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
                    evidence_files=[{"path": "src/stripe.py", "start_line": 1, "end_line": 10}],
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(analysis)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=self.SPEC_WITH_AC),
                    "raw": self.SPEC_WITH_AC,
                },
            ],
        )

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        content = self._get_committed_content(client)
        assert "- [x] Stripe integration complete" in content
        assert "- [ ] Idempotency keys generated" in content
        # Status NOT advanced — still in_progress
        assert "status:in_progress" in content

    async def test_no_advance_when_section_already_done(self):
        """Sections already at done aren't re-processed."""
        spec_done = """---
title: Payments
status: done
owner: test
team: test
---

## 2. Payment Flow

<!-- specwright:system:2 status:done -->

- [x] Stripe integration complete
- [ ] Idempotency keys generated

Content here.
"""
        analysis = PRAnalysisResult(
            summary="test",
            spec_references=[],
            discrepancies=[],
            doc_updates=[],
            realizations=[
                ACRealization(
                    spec_file="docs/specs/payments.md",
                    section_id="2-payment-flow",
                    section_title="Payment Flow",
                    ac_text="Idempotency keys generated",
                    status=RealizationStatus.REALIZED,
                    evidence_files=[{"path": "src/keys.py", "start_line": 1, "end_line": 5}],
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(analysis)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=spec_done),
                    "raw": spec_done,
                },
            ],
        )

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        content = self._get_committed_content(client)
        # AC checked off and evidence added
        assert "- [x] Idempotency keys generated" in content
        # Status stays done (not re-advanced)
        assert "status:done" in content

    async def test_no_advance_when_section_blocked(self):
        """Blocked sections are not auto-advanced even if all ACs are checked."""
        spec_blocked = """---
title: Payments
status: in_progress
owner: test
team: test
---

## 2. Payment Flow

<!-- specwright:system:2 status:blocked -->

- [ ] Stripe integration complete
- [ ] Idempotency keys generated

Content here.
"""
        analysis = PRAnalysisResult(
            summary="test",
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
                    evidence_files=[{"path": "src/stripe.py", "start_line": 1, "end_line": 10}],
                ),
                ACRealization(
                    spec_file="docs/specs/payments.md",
                    section_id="2-payment-flow",
                    section_title="Payment Flow",
                    ac_text="Idempotency keys generated",
                    status=RealizationStatus.REALIZED,
                    evidence_files=[{"path": "src/keys.py", "start_line": 1, "end_line": 5}],
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(analysis)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=spec_blocked),
                    "raw": spec_blocked,
                },
            ],
        )

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        content = self._get_committed_content(client)
        # ACs are checked off
        assert "- [x] Stripe integration complete" in content
        assert "- [x] Idempotency keys generated" in content
        # But status stays blocked — requires human to clear the blocker
        assert "status:blocked" in content
        assert "status:done" not in content

    async def test_skips_auto_advance_with_duplicate_ac_text(self):
        """Auto-advance is skipped when duplicate AC text exists across sections."""
        spec_dup = """---
title: Payments
status: in_progress
owner: test
team: test
---

## 2. Payment Flow

<!-- specwright:system:2 status:in_progress -->

- [ ] Error handling implemented

## 3. Refund Flow

<!-- specwright:system:3 status:todo -->

- [ ] Error handling implemented

Content here.
"""
        analysis = PRAnalysisResult(
            summary="test",
            spec_references=[],
            discrepancies=[],
            doc_updates=[],
            realizations=[
                ACRealization(
                    spec_file="docs/specs/payments.md",
                    section_id="2-payment-flow",
                    section_title="Payment Flow",
                    ac_text="Error handling implemented",
                    status=RealizationStatus.REALIZED,
                    evidence_files=[{"path": "src/errors.py", "start_line": 1, "end_line": 10}],
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(analysis)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=spec_dup),
                    "raw": spec_dup,
                },
            ],
        )

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        content = self._get_committed_content(client)
        # Realization evidence and check-off still applied (pre-existing behavior)
        assert "canon:realized-in:PR#42" in content
        # But auto-advance is skipped due to duplicate AC text
        assert "status:in_progress" in content
        assert "status:done" not in content

    async def test_realization_with_doc_update_combined(self):
        """Doc updates and realizations are both applied in the same commit."""
        analysis = PRAnalysisResult(
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
            ],
            realizations=[
                ACRealization(
                    spec_file="docs/specs/payments.md",
                    section_id="2-payment-flow",
                    section_title="Payment Flow",
                    ac_text="Stripe integration complete",
                    status=RealizationStatus.REALIZED,
                    evidence_files=[{"path": "stripe.py", "start_line": 1, "end_line": 10}],
                ),
            ],
            tokens_used=TokenUsage(input=1000, output=500),
        )

        client = _make_client(
            comments=[{"id": 100, "body": _make_bot_comment_body(analysis)}],
            specs=[
                {
                    "file_path": "docs/specs/payments.md",
                    "document": MagicMock(raw=self.SPEC_WITH_AC),
                    "raw": self.SPEC_WITH_AC,
                },
            ],
        )

        payload = _make_payload()
        await on_pull_request_merged(client, payload)

        client.create_or_update_file.assert_called_once()
        content = self._get_committed_content(client)
        # Both text replacement and realization comment should be present
        assert "Content updated." in content
        assert "canon:realized-in:PR#42" in content
        client.create_doc_pr.assert_not_called()
