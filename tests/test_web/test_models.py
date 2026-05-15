"""Tests for web view models (Pydantic validation and serialization)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from canon.web.models import (
    AiEditRequest,
    BrokenRef,
    BrokenRefsApiResponse,
    CoverageApiResponse,
    CoverageSummary,
    CoverageTrendPoint,
    DismissBrokenRefRequest,
    DocDetail,
    DocFile,
    EditorParseRequest,
    EditorSavePRRequest,
    EditorSaveRequest,
    FacetCounts,
    OrgOverview,
    ProfileGitHubUser,
    ProfileResponse,
    RecheckBrokenRefRequest,
    RemoveTicketRefResponse,
    RepoSummary,
    SearchApiResponse,
    SpecSearchResult,
    SpecSummary,
    TaskItem,
    TasksApiResponse,
)

# ---------------------------------------------------------------------------
# SpecSummary
# ---------------------------------------------------------------------------


class TestSpecSummary:
    def test_minimal_fields(self):
        s = SpecSummary(
            file_path="docs/specs/auth.md",
            title="Auth",
            status="draft",
            owner="alice",
            team="platform",
            tags=["auth"],
            total_sections=3,
            done_sections=1,
            total_ac=6,
            done_ac=2,
        )
        assert s.file_path == "docs/specs/auth.md"
        assert s.review_status is None
        assert s.is_indexed is False
        assert s.last_doc_change_at is None
        assert s.stale_since is None
        assert s.is_stale is False

    def test_full_fields(self):
        now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        s = SpecSummary(
            file_path="docs/specs/auth.md",
            title="Auth",
            status="in_progress",
            owner="alice",
            team="platform",
            tags=["auth", "security"],
            total_sections=5,
            done_sections=3,
            total_ac=10,
            done_ac=7,
            review_status="approved",
            is_indexed=True,
            last_doc_change_at=now,
            last_code_change_at=now,
            stale_since=now,
            is_stale=True,
        )
        data = s.model_dump()
        assert data["review_status"] == "approved"
        assert data["is_indexed"] is True
        assert data["is_stale"] is True
        assert data["tags"] == ["auth", "security"]

    def test_empty_tags(self):
        s = SpecSummary(
            file_path="f.md",
            title="T",
            status="draft",
            owner="",
            team="",
            tags=[],
            total_sections=0,
            done_sections=0,
            total_ac=0,
            done_ac=0,
        )
        assert s.tags == []

    def test_roundtrip_json(self):
        s = SpecSummary(
            file_path="f.md",
            title="T",
            status="draft",
            owner="o",
            team="t",
            tags=[],
            total_sections=0,
            done_sections=0,
            total_ac=0,
            done_ac=0,
        )
        json_str = s.model_dump_json()
        restored = SpecSummary.model_validate_json(json_str)
        assert restored == s


# ---------------------------------------------------------------------------
# BrokenRef
# ---------------------------------------------------------------------------


class TestBrokenRef:
    def test_valid_systems(self):
        for system in ("jira", "linear", "github"):
            ref = BrokenRef(
                system=system,
                ticket_ref="PROJ-123",
                spec_path="org/repo/docs/specs/a.md",
                section_id="1-overview",
                section_heading="Overview",
                error_kind="not_found",
                first_failure_at=datetime(2026, 1, 1, tzinfo=UTC),
                last_check_at=datetime(2026, 1, 2, tzinfo=UTC),
                dismissed=False,
                dismissed_by=None,
            )
            assert ref.system == system

    def test_invalid_system_rejected(self):
        with pytest.raises(ValidationError):
            BrokenRef(
                system="gitlab",
                ticket_ref="PROJ-123",
                spec_path="org/repo/a.md",
                section_id="1",
                section_heading="H",
                error_kind="not_found",
                first_failure_at=datetime.now(tz=UTC),
                last_check_at=datetime.now(tz=UTC),
                dismissed=False,
                dismissed_by=None,
            )

    def test_valid_error_kinds(self):
        for kind in ("not_found", "forbidden", "unauthorized"):
            ref = BrokenRef(
                system="jira",
                ticket_ref="T-1",
                spec_path="p",
                section_id="s",
                section_heading="h",
                error_kind=kind,
                first_failure_at=datetime.now(tz=UTC),
                last_check_at=datetime.now(tz=UTC),
                dismissed=False,
                dismissed_by=None,
            )
            assert ref.error_kind == kind

    def test_invalid_error_kind_rejected(self):
        with pytest.raises(ValidationError):
            BrokenRef(
                system="jira",
                ticket_ref="T-1",
                spec_path="p",
                section_id="s",
                section_heading="h",
                error_kind="timeout",
                first_failure_at=datetime.now(tz=UTC),
                last_check_at=datetime.now(tz=UTC),
                dismissed=False,
                dismissed_by=None,
            )

    def test_dismissed_with_user(self):
        ref = BrokenRef(
            system="linear",
            ticket_ref="LIN-42",
            spec_path="org/repo/spec.md",
            section_id="2",
            section_heading="Design",
            error_kind="forbidden",
            first_failure_at=datetime.now(tz=UTC),
            last_check_at=datetime.now(tz=UTC),
            dismissed=True,
            dismissed_by="alice@example.com",
        )
        assert ref.dismissed is True
        assert ref.dismissed_by == "alice@example.com"


# ---------------------------------------------------------------------------
# DocFile
# ---------------------------------------------------------------------------


class TestDocFile:
    def test_defaults(self):
        d = DocFile(path="docs/arch.md", name="arch.md", github_url="https://github.com/x")
        assert d.title == ""
        assert d.doc_type == "doc"
        assert d.is_indexed is False

    def test_custom_fields(self):
        d = DocFile(
            path="docs/adr/001.md",
            name="001.md",
            github_url="https://github.com/x/y",
            title="ADR-001",
            doc_type="adr",
            is_indexed=True,
        )
        assert d.doc_type == "adr"
        assert d.is_indexed is True


# ---------------------------------------------------------------------------
# RepoSummary
# ---------------------------------------------------------------------------


class TestRepoSummary:
    def test_minimal(self):
        r = RepoSummary(
            owner="org",
            repo="my-repo",
            full_name="org/my-repo",
            description="A repo",
            default_branch="main",
            has_specs=False,
            spec_count=0,
            specs=[],
            config=None,
            docs=[],
        )
        assert r.broken_refs_count == 0
        assert r.config is None
        assert r.docs == []

    def test_with_specs_and_docs(self):
        spec = SpecSummary(
            file_path="f.md",
            title="T",
            status="done",
            owner="o",
            team="t",
            tags=[],
            total_sections=1,
            done_sections=1,
            total_ac=2,
            done_ac=2,
        )
        doc = DocFile(path="README.md", name="README.md", github_url="https://gh.com")
        r = RepoSummary(
            owner="org",
            repo="r",
            full_name="org/r",
            description="",
            default_branch="main",
            has_specs=True,
            spec_count=1,
            specs=[spec],
            config=None,
            docs=[doc],
            broken_refs_count=3,
        )
        assert r.spec_count == 1
        assert len(r.specs) == 1
        assert len(r.docs) == 1
        assert r.broken_refs_count == 3


# ---------------------------------------------------------------------------
# OrgOverview
# ---------------------------------------------------------------------------


class TestOrgOverview:
    def test_defaults(self):
        o = OrgOverview(
            org="acme",
            repos_with_specs=[],
            repos_without_specs=[],
            total_specs=0,
            total_repos=0,
        )
        assert o.total_docs == 0
        assert o.total_broken_refs == 0

    def test_with_counts(self):
        o = OrgOverview(
            org="acme",
            repos_with_specs=[],
            repos_without_specs=[],
            total_specs=10,
            total_repos=5,
            total_docs=3,
            total_broken_refs=2,
        )
        assert o.total_specs == 10
        assert o.total_broken_refs == 2


# ---------------------------------------------------------------------------
# DocDetail
# ---------------------------------------------------------------------------


class TestDocDetail:
    def test_defaults(self):
        d = DocDetail(
            path="docs/guide.md",
            title="Guide",
            rendered_html="<p>Hello</p>",
            repo_owner="org",
            repo_name="repo",
            github_url="https://github.com/org/repo/blob/main/docs/guide.md",
        )
        assert d.doc_type == "doc"

    def test_custom_doc_type(self):
        d = DocDetail(
            path="docs/adr/001.md",
            title="ADR-001",
            rendered_html="<h1>ADR</h1>",
            repo_owner="org",
            repo_name="repo",
            github_url="https://github.com/org/repo",
            doc_type="adr",
        )
        assert d.doc_type == "adr"


# ---------------------------------------------------------------------------
# SpecSearchResult
# ---------------------------------------------------------------------------


class TestSpecSearchResult:
    def test_defaults(self):
        r = SpecSearchResult(
            file_path="docs/specs/auth.md",
            title="Auth",
            status="draft",
            owner="alice",
            team="platform",
            repo_full_name="org/repo",
            repo_owner="org",
            repo_name="repo",
            tags=["auth"],
        )
        assert r.heading == ""
        assert r.snippet == ""
        assert r.score == 0.0
        assert r.doc_type == "spec"
        assert r.review_status is None

    def test_with_search_metadata(self):
        r = SpecSearchResult(
            file_path="docs/specs/auth.md",
            title="Auth",
            status="in_progress",
            owner="bob",
            team="security",
            repo_full_name="org/repo",
            repo_owner="org",
            repo_name="repo",
            tags=[],
            heading="Login Flow",
            snippet="Implements OAuth2...",
            score=0.95,
            doc_type="proposal",
            review_status="in_review",
        )
        assert r.score == 0.95
        assert r.doc_type == "proposal"


# ---------------------------------------------------------------------------
# FacetCounts
# ---------------------------------------------------------------------------


class TestFacetCounts:
    def test_empty_defaults(self):
        f = FacetCounts()
        assert f.status == {}
        assert f.repo == {}
        assert f.team == {}
        assert f.tag == {}

    def test_populated(self):
        f = FacetCounts(
            status={"draft": 3, "done": 7},
            repo={"org/repo": 10},
            team={"platform": 5},
            tag={"auth": 2},
        )
        assert f.status["draft"] == 3
        assert f.tag["auth"] == 2


# ---------------------------------------------------------------------------
# SearchApiResponse
# ---------------------------------------------------------------------------


class TestSearchApiResponse:
    def test_empty(self):
        r = SearchApiResponse(results=[], total=0, facets=FacetCounts())
        assert r.total == 0
        assert r.results == []

    def test_with_results(self):
        result = SpecSearchResult(
            file_path="f.md",
            title="T",
            status="draft",
            owner="o",
            team="t",
            repo_full_name="org/r",
            repo_owner="org",
            repo_name="r",
            tags=[],
        )
        r = SearchApiResponse(results=[result], total=1, facets=FacetCounts())
        assert r.total == 1
        assert len(r.results) == 1


# ---------------------------------------------------------------------------
# BrokenRefsApiResponse
# ---------------------------------------------------------------------------


class TestBrokenRefsApiResponse:
    def test_pagination_fields(self):
        r = BrokenRefsApiResponse(items=[], total=0, limit=20, offset=0)
        assert r.limit == 20
        assert r.offset == 0


# ---------------------------------------------------------------------------
# DismissBrokenRefRequest / RecheckBrokenRefRequest
# ---------------------------------------------------------------------------


class TestDismissAndRecheckRequests:
    def test_dismiss_valid_systems(self):
        for system in ("jira", "linear", "github"):
            req = DismissBrokenRefRequest(system=system, ticket_ref="T-1")
            assert req.system == system

    def test_dismiss_invalid_system(self):
        with pytest.raises(ValidationError):
            DismissBrokenRefRequest(system="gitlab", ticket_ref="T-1")

    def test_recheck_valid(self):
        req = RecheckBrokenRefRequest(system="jira", ticket_ref="PROJ-42")
        assert req.ticket_ref == "PROJ-42"

    def test_recheck_invalid_system(self):
        with pytest.raises(ValidationError):
            RecheckBrokenRefRequest(system="asana", ticket_ref="T-1")


# ---------------------------------------------------------------------------
# RemoveTicketRefResponse
# ---------------------------------------------------------------------------


class TestRemoveTicketRefResponse:
    def test_fields(self):
        r = RemoveTicketRefResponse(pr_number=42, pr_url="https://github.com/org/repo/pull/42")
        assert r.pr_number == 42
        assert "pull/42" in r.pr_url


# ---------------------------------------------------------------------------
# EditorSaveRequest / EditorSavePRRequest / EditorParseRequest
# ---------------------------------------------------------------------------


class TestEditorRequests:
    def test_save_request_defaults(self):
        req = EditorSaveRequest(content="# Spec", sha="abc123")
        assert req.message == ""

    def test_save_request_with_message(self):
        req = EditorSaveRequest(content="# Spec", sha="abc123", message="Update spec")
        assert req.message == "Update spec"

    def test_save_pr_request_defaults(self):
        req = EditorSavePRRequest(content="# Spec", sha="abc123")
        assert req.branch_name == ""
        assert req.pr_title == ""
        assert req.pr_body == ""

    def test_save_pr_request_inherits_from_save(self):
        req = EditorSavePRRequest(
            content="# Spec",
            sha="abc123",
            message="commit msg",
            branch_name="feat/update",
            pr_title="Update spec",
            pr_body="Details here",
        )
        assert req.message == "commit msg"
        assert req.branch_name == "feat/update"

    def test_parse_request_max_length(self):
        # Valid: within limit
        req = EditorParseRequest(content="x" * 1000)
        assert len(req.content) == 1000

    def test_parse_request_exceeds_max_length(self):
        with pytest.raises(ValidationError, match=r"string_too_long|max_length"):
            EditorParseRequest(content="x" * 500_001)

    def test_parse_request_requires_content(self):
        with pytest.raises(ValidationError):
            EditorParseRequest()


# ---------------------------------------------------------------------------
# CoverageSummary
# ---------------------------------------------------------------------------


class TestCoverageSummary:
    def test_defaults(self):
        c = CoverageSummary()
        assert c.total_specs == 0
        assert c.section_coverage_pct == 0.0
        assert c.ac_coverage_pct == 0.0
        assert c.realization_rate_pct == 0.0
        assert c.health_score == 0.0

    def test_populated(self):
        c = CoverageSummary(
            total_specs=5,
            total_sections=20,
            done_sections=15,
            total_ac=50,
            done_ac=40,
            realized_ac=35,
            section_coverage_pct=75.0,
            ac_coverage_pct=80.0,
            realization_rate_pct=87.5,
            health_score=82.0,
        )
        assert c.total_specs == 5
        assert c.health_score == 82.0


# ---------------------------------------------------------------------------
# CoverageTrendPoint
# ---------------------------------------------------------------------------


class TestCoverageTrendPoint:
    def test_defaults(self):
        p = CoverageTrendPoint(date="2026-01-15")
        assert p.total_sections == 0
        assert p.done_sections == 0
        assert p.realized_ac == 0

    def test_populated(self):
        p = CoverageTrendPoint(
            date="2026-01-15",
            total_sections=10,
            done_sections=8,
            total_ac=20,
            done_ac=16,
            realized_ac=14,
        )
        assert p.date == "2026-01-15"
        assert p.realized_ac == 14


# ---------------------------------------------------------------------------
# CoverageApiResponse
# ---------------------------------------------------------------------------


class TestCoverageApiResponse:
    def test_defaults(self):
        r = CoverageApiResponse(summary=CoverageSummary())
        assert r.trend == []
        assert r.breakdown_by_repo == {}
        assert r.breakdown_by_team == {}

    def test_with_breakdowns(self):
        r = CoverageApiResponse(
            summary=CoverageSummary(total_specs=3),
            trend=[CoverageTrendPoint(date="2026-01-01")],
            breakdown_by_repo={"org/repo": CoverageSummary(total_specs=2)},
            breakdown_by_team={"platform": CoverageSummary(total_specs=1)},
        )
        assert len(r.trend) == 1
        assert r.breakdown_by_repo["org/repo"].total_specs == 2
        assert r.breakdown_by_team["platform"].total_specs == 1


# ---------------------------------------------------------------------------
# TaskItem
# ---------------------------------------------------------------------------


class TestTaskItem:
    def test_defaults(self):
        t = TaskItem(section_id="1-overview", title="Overview", status="todo")
        assert t.section_number is None
        assert t.blocked_by is None
        assert t.total_ac == 0
        assert t.done_ac == 0
        assert t.ticket_system is None
        assert t.ticket_id is None
        assert t.spec_title == ""
        assert t.spec_file_path == ""
        assert t.repo_owner == ""
        assert t.repo_name == ""
        assert t.acceptance_criteria == []

    def test_full_task(self):
        t = TaskItem(
            section_id="2-design",
            section_number="2",
            title="Design",
            status="in_progress",
            blocked_by="1-overview",
            total_ac=3,
            done_ac=1,
            ticket_system="jira",
            ticket_id="PROJ-42",
            spec_title="Auth Spec",
            spec_file_path="docs/specs/auth.md",
            repo_owner="org",
            repo_name="repo",
            acceptance_criteria=[{"text": "AC 1", "checked": False}],
        )
        assert t.blocked_by == "1-overview"
        assert t.ticket_system == "jira"
        assert len(t.acceptance_criteria) == 1


# ---------------------------------------------------------------------------
# TasksApiResponse
# ---------------------------------------------------------------------------


class TestTasksApiResponse:
    def test_defaults(self):
        r = TasksApiResponse()
        assert r.tasks == []
        assert r.total == 0

    def test_with_tasks(self):
        task = TaskItem(section_id="1", title="T", status="todo")
        r = TasksApiResponse(tasks=[task], total=1)
        assert r.total == 1


# ---------------------------------------------------------------------------
# AiEditRequest
# ---------------------------------------------------------------------------


class TestAiEditRequest:
    def test_valid_actions(self):
        for action in ("improve", "generate_acs", "expand"):
            req = AiEditRequest(
                action=action,
                section_title="Overview",
                section_content="Some content",
            )
            assert req.action == action

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            AiEditRequest(
                action="summarize",
                section_title="Overview",
                section_content="Content",
            )

    def test_section_title_max_length(self):
        with pytest.raises(ValidationError, match=r"string_too_long|max_length"):
            AiEditRequest(
                action="improve",
                section_title="x" * 501,
                section_content="Content",
            )

    def test_section_content_max_length(self):
        with pytest.raises(ValidationError, match=r"string_too_long|max_length"):
            AiEditRequest(
                action="improve",
                section_title="Title",
                section_content="x" * 100_001,
            )

    def test_acceptance_criteria_default_empty(self):
        req = AiEditRequest(
            action="improve",
            section_title="Title",
            section_content="Content",
        )
        assert req.acceptance_criteria == []

    def test_with_acceptance_criteria(self):
        req = AiEditRequest(
            action="generate_acs",
            section_title="Title",
            section_content="Content",
            acceptance_criteria=["AC 1", "AC 2"],
        )
        assert len(req.acceptance_criteria) == 2


# ---------------------------------------------------------------------------
# ProfileGitHubUser
# ---------------------------------------------------------------------------


class TestProfileGitHubUser:
    def test_defaults(self):
        u = ProfileGitHubUser(login="octocat")
        assert u.name == ""

    def test_with_name(self):
        u = ProfileGitHubUser(login="octocat", name="The Octocat")
        assert u.name == "The Octocat"


# ---------------------------------------------------------------------------
# ProfileResponse
# ---------------------------------------------------------------------------


class TestProfileResponse:
    def test_required_fields_only(self):
        p = ProfileResponse(
            sub="auth0|123",
            email="user@example.com",
            name="User",
            picture="https://example.com/pic.jpg",
            org_login="org",
            permissions=["specs:read"],
            all_permissions=["specs:read"],
            auth_method="session",
            inferred_role="viewer",
        )
        assert p.org_id == ""
        assert p.github_user is None
        assert p.last_login_at is None
        assert p.permission_descriptions == {}

    def test_full_profile(self):
        p = ProfileResponse(
            sub="auth0|123",
            email="user@example.com",
            name="User",
            picture="https://example.com/pic.jpg",
            org_login="org",
            org_id="org_abc",
            permissions=["specs:read", "specs:write"],
            all_permissions=["specs:read", "specs:write", "specs:admin"],
            permission_descriptions={"specs:read": "Read specs"},
            auth_method="session",
            github_user=ProfileGitHubUser(login="user", name="User"),
            last_login_at="2026-01-01T00:00:00Z",
            inferred_role="editor",
        )
        data = p.model_dump()
        assert data["org_id"] == "org_abc"
        assert data["github_user"]["login"] == "user"
        assert data["inferred_role"] == "editor"
