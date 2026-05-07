"""View models for the Spec Explorer web app."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..config.parse import CanonConfig
from ..parser.models import SpecDocument


class SpecSummary(BaseModel):
    """Summary of a single spec for dashboard display."""

    file_path: str
    title: str
    status: str
    owner: str
    team: str
    tags: list[str]
    total_sections: int
    done_sections: int
    total_ac: int
    done_ac: int
    review_status: str | None = None
    is_indexed: bool = False
    last_doc_change_at: datetime | None = None
    last_code_change_at: datetime | None = None
    stale_since: datetime | None = None
    is_stale: bool = False


class BrokenRef(BaseModel):
    """A spec section that references a ticket the cron has flagged broken."""

    system: Literal["jira", "linear", "github"]
    ticket_ref: str  # Fully-qualified per canon.sync.ticket_ref.qualify
    spec_path: str  # `{repo_full_name}/{file_path}` — used for navigation
    section_id: str
    section_heading: str
    error_kind: Literal["not_found", "forbidden", "unauthorized"]
    first_failure_at: datetime
    last_check_at: datetime
    dismissed: bool
    dismissed_by: str | None


class DocFile(BaseModel):
    """An unstructured markdown file (not a spec)."""

    path: str
    name: str
    github_url: str
    title: str = ""
    doc_type: str = "doc"
    is_indexed: bool = False


class RepoSummary(BaseModel):
    """Summary of a repository for dashboard display."""

    owner: str
    repo: str
    full_name: str
    description: str
    default_branch: str
    has_specs: bool
    spec_count: int
    specs: list[SpecSummary]
    config: CanonConfig | None
    docs: list[DocFile]
    broken_refs_count: int = 0


class OrgOverview(BaseModel):
    """Full org dashboard data."""

    org: str
    repos_with_specs: list[RepoSummary]
    repos_without_specs: list[RepoSummary]
    total_specs: int
    total_repos: int
    total_docs: int = 0
    total_broken_refs: int = 0


class SpecDetail(BaseModel):
    """Full spec detail for the spec page."""

    document: SpecDocument
    rendered_html: str
    repo_owner: str
    repo_name: str
    github_url: str
    config: CanonConfig | None
    broken_sections: list[BrokenRef] = []


class DocDetail(BaseModel):
    """Full doc detail for the doc page."""

    path: str
    title: str
    rendered_html: str
    repo_owner: str
    repo_name: str
    github_url: str
    doc_type: str = "doc"


class SpecSearchResult(BaseModel):
    """A search result matching a spec or doc."""

    file_path: str
    title: str
    status: str
    owner: str
    team: str
    repo_full_name: str
    repo_owner: str
    repo_name: str
    tags: list[str]
    heading: str = ""
    snippet: str = ""
    score: float = 0.0
    doc_type: str = "spec"
    review_status: str | None = None


class FacetCounts(BaseModel):
    """Aggregate counts for faceted filtering."""

    status: dict[str, int] = {}
    repo: dict[str, int] = {}
    team: dict[str, int] = {}
    tag: dict[str, int] = {}


class SearchApiResponse(BaseModel):
    """JSON response for the /api/search endpoint."""

    results: list[SpecSearchResult]
    total: int
    facets: FacetCounts


class BrokenRefsApiResponse(BaseModel):
    """JSON response for GET /{org}/api/broken-refs."""

    items: list[BrokenRef]
    total: int
    limit: int
    offset: int


class DismissBrokenRefRequest(BaseModel):
    """Request to dismiss a broken ticket reference."""

    system: Literal["jira", "linear", "github"]
    ticket_ref: str


class RecheckBrokenRefRequest(BaseModel):
    """Request to recheck a broken ticket reference."""

    system: Literal["jira", "linear", "github"]
    ticket_ref: str


class RemoveTicketRefResponse(BaseModel):
    """Response after removing a ticket reference."""

    pr_number: int
    pr_url: str


class EditorSaveRequest(BaseModel):
    """Request body for saving a spec via direct commit."""

    content: str
    sha: str
    message: str = ""


class EditorSavePRRequest(EditorSaveRequest):
    """Request body for saving a spec via a new PR."""

    branch_name: str = ""
    pr_title: str = ""
    pr_body: str = ""


class EditorParseRequest(BaseModel):
    """Request body for parsing spec content into structured sections."""

    content: str = Field(..., max_length=500_000)


class CoverageSummary(BaseModel):
    """Aggregate coverage metrics for an org/repo/team."""

    total_specs: int = 0
    total_sections: int = 0
    done_sections: int = 0
    total_ac: int = 0
    done_ac: int = 0
    realized_ac: int = 0
    section_coverage_pct: float = 0.0
    ac_coverage_pct: float = 0.0
    realization_rate_pct: float = 0.0
    health_score: float = 0.0


class CoverageTrendPoint(BaseModel):
    """A single data point in a coverage time series."""

    date: str
    total_sections: int = 0
    done_sections: int = 0
    total_ac: int = 0
    done_ac: int = 0
    realized_ac: int = 0


class CoverageApiResponse(BaseModel):
    """JSON response for the /api/coverage endpoint."""

    summary: CoverageSummary
    trend: list[CoverageTrendPoint] = []
    breakdown_by_repo: dict[str, CoverageSummary] = {}
    breakdown_by_team: dict[str, CoverageSummary] = {}


class TaskItem(BaseModel):
    """A single actionable task (spec section) for the tasks view."""

    section_id: str
    section_number: str | None = None
    title: str
    status: str
    blocked_by: str | None = None
    total_ac: int = 0
    done_ac: int = 0
    ticket_system: str | None = None
    ticket_id: str | None = None
    spec_title: str = ""
    spec_file_path: str = ""
    repo_owner: str = ""
    repo_name: str = ""
    acceptance_criteria: list[dict[str, object]] = []


class TasksApiResponse(BaseModel):
    """JSON response for the /api/tasks endpoint."""

    tasks: list[TaskItem] = []
    total: int = 0


class AiEditRequest(BaseModel):
    """Request body for AI-assisted section editing."""

    action: Literal["improve", "generate_acs", "expand"]
    section_title: str = Field(..., max_length=500)
    section_content: str = Field(..., max_length=100_000)
    acceptance_criteria: list[str] = []


class ProfileGitHubUser(BaseModel):
    """GitHub identity embedded in a profile response."""

    login: str
    name: str = ""


class ProfileResponse(BaseModel):
    """JSON response for the /api/profile endpoint."""

    sub: str
    email: str
    name: str
    picture: str
    org_login: str
    org_id: str = ""
    permissions: list[str]
    all_permissions: list[str]
    permission_descriptions: dict[str, str] = {}
    auth_method: str
    github_user: ProfileGitHubUser | None = None
    last_login_at: str | None = None
    inferred_role: str
