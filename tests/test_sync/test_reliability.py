"""Tests for ticket-sync-reliability spec features.

Covers:
- §3.1 Fingerprint Format
- §3.2 Fingerprint-Based Dedup
- §3.3 Backfill Existing Issues
- §2  Lifecycle Sync (close/reopen)
- §5  Default to Local Adapter
- §4  Remove Legacy Specwright Labels
- §6  Per-Spec Sync Control
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from canon.parser.models import (
    ParseOptions,
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
    TicketLink,
)
from canon.parser.parse import parse_spec
from canon.sync.adapters.base import AdapterCapabilities
from canon.sync.engine import backfill_fingerprints, forward_sync, reverse_sync
from canon.sync.models import (
    CreateTicketInput,
    CreateTicketResult,
    SearchResult,
    TicketStatusResult,
    UpdateTicketInput,
)
from canon.sync.templates import make_fingerprint, render_description

# ─── Helpers ──────────────────────────────────────────────


def _make_doc(
    file_path: str = "docs/specs/auth-hardening.md",
    sync: str = "auto",
) -> SpecDocument:
    return SpecDocument(
        file_path=file_path,
        frontmatter=SpecFrontmatter(
            title="Auth Hardening",
            status="draft",
            owner="nick",
            team="platform",
            sync=sync,
        ),
        sections=[],
        raw="",
    )


def _make_section(
    section_number: str = "2.1",
    title: str = "Password Reset",
    state: str = "todo",
    ticket_link: TicketLink | None = None,
) -> SpecSection:
    return SpecSection(
        id=f"{section_number}-{title.lower().replace(' ', '-')}",
        section_number=section_number,
        title=title,
        depth=3,
        content="Section content.",
        status=SectionStatus(state=state),
        ticket_link=ticket_link,
        start_line=10,
        end_line=20,
    )


class MockAdapter:
    """Test adapter with configurable responses."""

    def __init__(
        self,
        *,
        create_result: CreateTicketResult | None = None,
        status_result: TicketStatusResult | None = None,
        search_results: list[SearchResult] | None = None,
        fingerprint_results: list[SearchResult] | None = None,
        ticket_body: str = "",
    ) -> None:
        self.create_result = create_result or CreateTicketResult(
            ticket_id="42", ticket_url="https://github.com/test/repo/issues/42"
        )
        self.status_result = status_result
        self.search_results = search_results or []
        self.fingerprint_results = fingerprint_results or []
        self.ticket_body = ticket_body
        self.created: list[CreateTicketInput] = []
        self.updated: list[UpdateTicketInput] = []
        self.status_queries: list[str] = []

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        self.created.append(input)
        return self.create_result

    async def update_ticket(self, input: UpdateTicketInput) -> None:
        self.updated.append(input)

    async def get_ticket_status(self, ticket_id: str) -> TicketStatusResult:
        self.status_queries.append(ticket_id)
        assert self.status_result is not None
        return self.status_result

    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None:
        pass

    async def search_tickets(self, project_key: str, title_pattern: str) -> list[SearchResult]:
        return self.search_results

    async def search_by_fingerprint(self, project_key: str, fingerprint: str) -> list[SearchResult]:
        return self.fingerprint_results

    async def get_ticket(self, ticket_id: str) -> dict[str, object]:
        return {"body": self.ticket_body, "number": int(ticket_id)}

    @property
    def system_name(self) -> str:
        return "github"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_fingerprint_search=True,
            supports_body_read=True,
            supports_labels=True,
        )


# ═══════════════════════════════════════════════════════════
# §3.1 Fingerprint Format
# ═══════════════════════════════════════════════════════════


class TestFingerprintFormat:
    def test_fingerprint_format(self):
        doc = _make_doc(file_path="docs/specs/auth-hardening.md")
        section = _make_section(section_number="3")
        fp = make_fingerprint(doc, section)
        assert fp == "<!-- canon:section:docs/specs/auth-hardening:3 -->"

    def test_fingerprint_uses_slug_without_extension(self):
        doc = _make_doc(file_path="docs/specs/auth-hardening.md")
        section = _make_section(section_number="2.1")
        fp = make_fingerprint(doc, section)
        assert "auth-hardening.md" not in fp
        assert "docs/specs/auth-hardening:2.1" in fp

    def test_fingerprint_stable_across_title_renames(self):
        """Fingerprint is keyed on path + number, not title."""
        doc = _make_doc()
        s1 = _make_section(section_number="3", title="Old Title")
        s2 = _make_section(section_number="3", title="New Title")
        assert make_fingerprint(doc, s1) == make_fingerprint(doc, s2)

    def test_render_description_includes_fingerprint(self):
        doc = _make_doc()
        section = _make_section()
        desc = render_description(section, doc)
        assert "<!-- canon:section:docs/specs/auth-hardening:2.1 -->" in desc

    def test_fingerprint_variable_in_custom_template(self):
        from canon.sync.mapping import TemplateConfig

        config = TemplateConfig(description="Body\n\n{{fingerprint}}")
        doc = _make_doc()
        section = _make_section()
        desc = render_description(section, doc, config)
        # Fingerprint from {{fingerprint}} — auto-append skipped since already present
        assert desc.count("canon:section:docs/specs/auth-hardening:2.1") == 1

    def test_empty_file_path_handled(self):
        doc = _make_doc(file_path="")
        section = _make_section()
        fp = make_fingerprint(doc, section)
        assert "canon:section:unknown:2.1" in fp


# ═══════════════════════════════════════════════════════════
# §3.2 Fingerprint-Based Dedup
# ═══════════════════════════════════════════════════════════


class TestFingerprintDedup:
    @pytest.mark.asyncio
    async def test_fingerprint_dedup_finds_existing_issue(self):
        """Dedup first searches by fingerprint, links to existing issue."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:todo -->

Content."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        adapter = MockAdapter(
            fingerprint_results=[
                SearchResult(
                    ticket_id="99",
                    title="existing",
                    ticket_url="https://github.com/t/r/issues/99",
                    state="open",
                )
            ],
        )

        _, sync_result = await forward_sync(result.document, adapter, "test/repo")
        # Should link to existing instead of creating
        assert len(sync_result.updated) == 1
        assert sync_result.updated[0].ticket_id == "99"
        assert len(sync_result.created) == 0

    @pytest.mark.asyncio
    async def test_title_fallback_when_no_fingerprint_match(self):
        """Falls back to title search when no fingerprint match."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:todo -->

Content."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        adapter = MockAdapter(
            fingerprint_results=[],  # No fingerprint match
            search_results=[
                SearchResult(
                    ticket_id="88",
                    title="Section One",
                    ticket_url="https://github.com/t/r/issues/88",
                    state="open",
                )
            ],
        )

        _, sync_result = await forward_sync(result.document, adapter, "test/repo")
        assert len(sync_result.updated) == 1
        assert sync_result.updated[0].ticket_id == "88"

    @pytest.mark.asyncio
    async def test_two_sections_with_similar_titles_get_distinct_issues(self):
        """Sections with similar titles in different specs get distinct fingerprints."""
        doc1 = _make_doc(file_path="docs/specs/auth.md")
        doc2 = _make_doc(file_path="docs/specs/billing.md")
        section = _make_section(section_number="1", title="Setup")

        fp1 = make_fingerprint(doc1, section)
        fp2 = make_fingerprint(doc2, section)
        assert fp1 != fp2


# ═══════════════════════════════════════════════════════════
# §3.3 Backfill Existing Issues
# ═══════════════════════════════════════════════════════════


class TestBackfillFingerprints:
    @pytest.mark.asyncio
    async def test_backfill_adds_fingerprint_to_issue_without_one(self):
        doc = _make_doc()
        doc.sections = [
            _make_section(
                ticket_link=TicketLink(system="github", ticket_id="42"),
            )
        ]
        adapter = MockAdapter(ticket_body="Original body content")

        result = await backfill_fingerprints(doc, adapter)
        assert len(result.updated) == 1
        assert len(adapter.updated) == 1
        assert "canon:section:" in adapter.updated[0].description

    @pytest.mark.asyncio
    async def test_backfill_skips_issue_with_existing_fingerprint(self):
        doc = _make_doc()
        fingerprint = make_fingerprint(doc, _make_section())
        doc.sections = [
            _make_section(
                ticket_link=TicketLink(system="github", ticket_id="42"),
            )
        ]
        adapter = MockAdapter(ticket_body=f"Body\n\n{fingerprint}")

        result = await backfill_fingerprints(doc, adapter)
        assert len(result.skipped) == 1
        assert result.skipped[0].reason == "fingerprint already present"
        assert len(adapter.updated) == 0

    @pytest.mark.asyncio
    async def test_backfill_dry_run(self):
        doc = _make_doc()
        doc.sections = [
            _make_section(
                ticket_link=TicketLink(system="github", ticket_id="42"),
            )
        ]
        adapter = MockAdapter(ticket_body="Body without fingerprint")

        result = await backfill_fingerprints(doc, adapter, dry_run=True)
        assert len(result.updated) == 1
        # Dry run: no actual API calls
        assert len(adapter.updated) == 0


# ═══════════════════════════════════════════════════════════
# §2 Lifecycle Sync
# ═══════════════════════════════════════════════════════════


class TestLifecycleSync:
    @pytest.mark.asyncio
    async def test_section_todo_to_done_closes_ticket(self):
        """Section moves todo→done between syncs, second sync closes the ticket."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:done -->
<!-- canon:ticket:github:42 -->

Done section."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="42",
                status=SectionStatus(state="todo"),
                raw_status="open",
            ),
        )

        _, sync_result = await forward_sync(
            result.document, adapter, "test/repo", lifecycle_sync=True
        )
        assert len(sync_result.closed) == 1
        assert sync_result.closed[0].ticket_id == "42"

    @pytest.mark.asyncio
    async def test_section_done_to_in_progress_reopens_ticket(self):
        """Section moves done→in_progress, sync reopens the ticket."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:in_progress -->
<!-- canon:ticket:github:42 -->

Back in progress."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="42",
                status=SectionStatus(state="done"),
                raw_status="closed",
            ),
        )

        _, sync_result = await forward_sync(
            result.document, adapter, "test/repo", lifecycle_sync=True
        )
        assert len(sync_result.reopened) == 1
        assert sync_result.reopened[0].ticket_id == "42"

    @pytest.mark.asyncio
    async def test_lifecycle_sync_false_skips_close_reopen(self):
        """lifecycle_sync: false skips all close/reopen actions."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:done -->
<!-- canon:ticket:github:42 -->

Done section."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="42",
                status=SectionStatus(state="todo"),
                raw_status="open",
            ),
        )

        _, sync_result = await forward_sync(
            result.document, adapter, "test/repo", lifecycle_sync=False
        )
        assert len(sync_result.closed) == 0
        assert len(sync_result.reopened) == 0

    @pytest.mark.asyncio
    async def test_close_stale_works_with_lifecycle_sync_false(self):
        """--close-stale (close_only override) closes but never reopens."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:done -->
<!-- canon:ticket:github:42 -->

Done section."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="42",
                status=SectionStatus(state="todo"),
                raw_status="open",
            ),
        )

        # --close-stale overrides to "close_only" (closes done, never reopens)
        _, sync_result = await forward_sync(
            result.document, adapter, "test/repo", lifecycle_sync="close_only"
        )
        assert len(sync_result.closed) == 1
        assert len(sync_result.reopened) == 0

    @pytest.mark.asyncio
    async def test_close_only_does_not_reopen(self):
        """lifecycle_sync: 'close_only' closes but does not reopen.

        Uses a closed ticket status so that the reopen path *would*
        trigger under lifecycle_sync=True, verifying that 'close_only'
        actually prevents the reopen.
        """
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Done Section

<!-- canon:system:1 status:done -->
<!-- canon:ticket:github:42 -->

Done.

## 2. Reopened Section

<!-- canon:system:2 status:in_progress -->
<!-- canon:ticket:github:43 -->

Back to in_progress."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        # Return closed status — section 2 (in_progress) would be reopened
        # under lifecycle_sync=True, but 'close_only' should prevent it.
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="42",
                status=SectionStatus(state="done"),
                raw_status="closed",
            ),
        )

        _, sync_result = await forward_sync(
            result.document, adapter, "test/repo", lifecycle_sync="close_only"
        )
        # Section 1 (done) already closed — no re-close
        assert len(sync_result.closed) == 0
        # Section 2 (in_progress) ticket is closed but close_only prevents reopen
        assert len(sync_result.reopened) == 0

    @pytest.mark.asyncio
    async def test_draft_and_blocked_sections_skipped(self):
        """Sections in draft or blocked state are still skipped."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Draft Section

<!-- canon:system:1 status:draft -->
<!-- canon:ticket:github:42 -->

Draft.

## 2. Blocked Section

<!-- canon:system:2 status:blocked -->
<!-- canon:ticket:github:43 -->

Blocked."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        adapter = MockAdapter()

        _, sync_result = await forward_sync(
            result.document, adapter, "test/repo", lifecycle_sync=True
        )
        assert len(sync_result.closed) == 0
        assert len(sync_result.reopened) == 0

    @pytest.mark.asyncio
    async def test_dry_run_reports_lifecycle_actions(self):
        """--dry-run checks ticket status but skips writes."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:done -->
<!-- canon:ticket:github:42 -->

Done section."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        # Ticket is open — dry-run should report it would be closed
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="42",
                status=SectionStatus(state="todo"),
                raw_status="open",
            ),
        )

        _, sync_result = await forward_sync(
            result.document,
            adapter,
            "test/repo",
            lifecycle_sync=True,
            dry_run=True,
        )
        assert len(sync_result.closed) == 1
        assert len(adapter.updated) == 0  # Dry run: no write calls
        assert len(adapter.status_queries) == 1  # But status was checked

    @pytest.mark.asyncio
    async def test_forward_sync_skips_mismatched_ticket_system(self):
        """Lifecycle sync skips sections linked to a different ticket system."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Jira Section

<!-- canon:system:1 status:done -->
<!-- canon:ticket:jira:PROJ-99 -->

Done section linked to Jira."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        # MockAdapter.system_name is "github" — section is linked to "jira"
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="PROJ-99",
                status=SectionStatus(state="todo"),
                raw_status="open",
            ),
        )

        _, sync_result = await forward_sync(
            result.document, adapter, "test/repo", lifecycle_sync=True
        )
        # Should skip the Jira-linked section, not call the GitHub adapter
        assert len(sync_result.closed) == 0
        assert len(adapter.status_queries) == 0
        skipped_reasons = [s.reason for s in sync_result.skipped]
        assert any("jira" in r and "github" in r for r in skipped_reasons)

    @pytest.mark.asyncio
    async def test_reverse_sync_skips_mismatched_ticket_system(self):
        """Reverse sync skips sections linked to a different ticket system."""
        doc = _make_doc()
        doc.sections = [
            _make_section(
                section_number="1",
                title="Jira Task",
                state="todo",
                ticket_link=TicketLink(system="jira", ticket_id="PROJ-99", url=""),
            ),
        ]
        doc.raw = "placeholder"
        # MockAdapter.system_name is "github" — section is linked to "jira"
        adapter = MockAdapter(
            status_result=TicketStatusResult(
                ticket_id="PROJ-99",
                status=SectionStatus(state="in_progress"),
                raw_status="In Progress",
            ),
        )

        _, sync_result = await reverse_sync(doc, adapter, repo="test/repo")
        # Should skip the Jira-linked section, not call the GitHub adapter
        assert len(sync_result.status_changed) == 0
        assert len(adapter.status_queries) == 0
        skipped_reasons = [s.reason for s in sync_result.skipped]
        assert any("jira" in r and "github" in r for r in skipped_reasons)


# ═══════════════════════════════════════════════════════════
# §5 Default to Local Adapter
# ═══════════════════════════════════════════════════════════


class TestDefaultLocalAdapter:
    def test_has_local_credentials_with_github_token(self):
        from canon.cli.sync_cmd import _has_local_credentials

        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test123"}):
            assert _has_local_credentials() is True

    def test_has_local_credentials_without_token(self):
        from canon.cli.sync_cmd import _has_local_credentials

        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        with patch.dict("os.environ", env, clear=True), patch("subprocess.run") as mock_run:
            mock_run.return_value = type("Result", (), {"returncode": 1, "stdout": ""})()
            assert _has_local_credentials() is False

    def test_has_local_credentials_with_gh_cli(self):
        from canon.cli.sync_cmd import _has_local_credentials

        with patch.dict("os.environ", {}, clear=True), patch("subprocess.run") as mock_run:
            mock_run.return_value = type(
                "Result", (), {"returncode": 0, "stdout": "ghp_token123\n"}
            )()
            assert _has_local_credentials() is True


# ═══════════════════════════════════════════════════════════
# §4 Remove Legacy Specwright Labels
# ═══════════════════════════════════════════════════════════


class TestLegacyLabelRemoval:
    def test_create_ticket_only_produces_canon_labels(self):
        """create_ticket should only apply canon:* labels, not specwright:*."""
        from canon.sync.status_map import spec_status_to_github

        target = spec_status_to_github(SectionStatus(state="todo"))
        assert target.label == "canon:todo"
        assert "specwright" not in target.label

    def test_reverse_sync_reads_specwright_labels(self):
        """Reverse sync should still understand specwright:* labels."""
        from canon.sync.status_map import github_to_spec_status

        result = github_to_spec_status("open", ["specwright:in-progress"])
        assert result.state == "in_progress"

    def test_reverse_sync_prefers_canon_labels(self):
        """canon:* labels take precedence over specwright:*."""
        from canon.sync.status_map import github_to_spec_status

        result = github_to_spec_status("open", ["canon:todo", "specwright:in-progress"])
        assert result.state == "todo"


# ═══════════════════════════════════════════════════════════
# §6 Per-Spec Sync Control
# ═══════════════════════════════════════════════════════════


class TestPerSpecSyncControl:
    @pytest.mark.asyncio
    async def test_sync_false_skips_spec(self):
        """spec with sync: false is skipped."""
        raw = """---
title: Test
status: draft
owner: test
team: test
sync: "false"
---

## 1. Section One

<!-- canon:system:1 status:todo -->

Content."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        adapter = MockAdapter()

        _, sync_result = await forward_sync(result.document, adapter, "test/repo")
        assert len(sync_result.skipped) == 1
        assert "sync disabled" in sync_result.skipped[0].reason
        assert len(sync_result.created) == 0

    @pytest.mark.asyncio
    async def test_sync_true_bypasses_require_review(self):
        """spec with sync: true syncs regardless of require_review."""
        raw = """---
title: Test
status: draft
owner: test
team: test
sync: "true"
---

## 1. Section One

<!-- canon:system:1 status:todo -->

Content."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        adapter = MockAdapter()

        _, sync_result = await forward_sync(
            result.document, adapter, "test/repo", require_review=True
        )
        # Should NOT be blocked by require_review
        assert len(sync_result.errors) == 0
        assert len(sync_result.created) == 1

    @pytest.mark.asyncio
    async def test_sync_auto_defers_to_global(self):
        """spec with sync: auto (default) defers to global config."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

<!-- canon:system:1 status:todo -->

Content."""
        result = parse_spec(raw, ParseOptions(file_path="docs/specs/test.md"))
        adapter = MockAdapter()

        _, sync_result = await forward_sync(
            result.document, adapter, "test/repo", require_review=True
        )
        # Should be blocked by require_review
        assert len(sync_result.errors) == 1
        assert "review approval" in sync_result.errors[0].error

    def test_parser_extracts_sync_field(self):
        """Parser extracts sync field from frontmatter."""
        raw = """---
title: Test
status: draft
owner: test
team: test
sync: "false"
---

## 1. Section One

Content."""
        result = parse_spec(raw)
        assert result.document.frontmatter.sync == "false"

    def test_parser_defaults_sync_to_auto(self):
        """Parser defaults sync to auto when not specified."""
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section One

Content."""
        result = parse_spec(raw)
        assert result.document.frontmatter.sync == "auto"


# ═══════════════════════════════════════════════════════════
# Config: lifecycle_sync in SpecsConfig
# ═══════════════════════════════════════════════════════════


class TestLifecycleSyncConfig:
    def test_lifecycle_sync_true(self):
        from canon.config.parse import parse_canon_yaml

        result = parse_canon_yaml("specs:\n  lifecycle_sync: true\n")
        assert result.config.specs.lifecycle_sync is True

    def test_lifecycle_sync_false(self):
        from canon.config.parse import parse_canon_yaml

        result = parse_canon_yaml("specs:\n  lifecycle_sync: false\n")
        assert result.config.specs.lifecycle_sync is False

    def test_lifecycle_sync_close_only(self):
        from canon.config.parse import parse_canon_yaml

        result = parse_canon_yaml('specs:\n  lifecycle_sync: "close_only"\n')
        assert result.config.specs.lifecycle_sync == "close_only"

    def test_lifecycle_sync_defaults_to_true(self):
        from canon.config.parse import parse_canon_yaml

        result = parse_canon_yaml("specs:\n  auto_tickets: true\n")
        assert result.config.specs.lifecycle_sync is True

    def test_lifecycle_sync_invalid_value(self):
        from canon.config.parse import parse_canon_yaml

        result = parse_canon_yaml('specs:\n  lifecycle_sync: "maybe"\n')
        assert any("lifecycle_sync" in d.message for d in result.diagnostics)
