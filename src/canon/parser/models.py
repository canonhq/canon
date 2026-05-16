"""Pydantic models for parsed spec documents."""

from __future__ import annotations

import re
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, computed_field

# --- Type aliases (single source of truth for Literal + validation sets) ---

DocType = Literal["spec", "proposal", "design", "adr"]
ReviewStatus = Literal["draft", "in_review", "approved"]
AiExposure = Literal["full", "metadata", "none"]

VALID_DOC_TYPES: frozenset[str] = frozenset(get_args(DocType))
VALID_REVIEW_STATUSES: frozenset[str] = frozenset(get_args(ReviewStatus))
VALID_AI_EXPOSURES: frozenset[str] = frozenset(get_args(AiExposure))

# --- Section Status ---


class SectionStatus(BaseModel):
    state: Literal["draft", "todo", "in_progress", "done", "blocked", "deprecated"]
    blocked_by: str | None = None


# --- Ticket Link ---


class TicketLink(BaseModel):
    system: Literal["jira", "linear", "github"]
    ticket_id: str
    url: str | None = None


# --- Realization Reference ---


class RealizationRef(BaseModel):
    pr_number: int | None = None
    file_path: str = ""
    lines: str = ""  # e.g. "42-60"


# --- BDD Scenarios ---


class ScenarioStep(BaseModel):
    keyword: Literal["GIVEN", "WHEN", "THEN", "AND", "BUT"]
    text: str
    strength: Literal["MUST", "MUST_NOT", "SHOULD", "SHOULD_NOT", "MAY"] | None = None
    line: int


class Scenario(BaseModel):
    name: str
    steps: list[ScenarioStep] = Field(min_length=1)
    start_line: int
    end_line: int


# --- Acceptance Criteria ---


class AcceptanceCriterion(BaseModel):
    text: str
    checked: bool
    line: int
    realized_in: list[RealizationRef] = []
    strength: Literal["MUST", "MUST_NOT", "SHOULD", "SHOULD_NOT", "MAY"] | None = None


# --- Spec Section ---

_AC_HEADING_RE = re.compile(r"^###\s+Acceptance\s+Criteria\s*$", re.IGNORECASE)
_SYSTEM_COMMENT_RE = re.compile(
    r"<!--\s*(?:specwright|canon):(?:system:\S+\s+status:\S+|ticket:\w+:\S+(?:\s+url:\S+)?)\s*-->"
)


class SpecSection(BaseModel):
    id: str
    section_number: str | None
    title: str
    depth: int
    content: str
    ticket_link: TicketLink | None = None
    status: SectionStatus
    acceptance_criteria: list[AcceptanceCriterion] = []
    scenarios: list[Scenario] = []
    delta: Literal["added", "modified", "removed"] | None = None
    children: list[SpecSection] = []
    start_line: int
    end_line: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def prose_content(self) -> str:
        """Content with AC block and system comments stripped.

        Cuts at the ``### Acceptance Criteria`` heading (everything from
        there to end of section is excluded) and drops inline
        canon/specwright system comments.
        """
        lines = self.content.split("\n")
        prose: list[str] = []
        for line in lines:
            if _AC_HEADING_RE.match(line.strip()):
                break
            if _SYSTEM_COMMENT_RE.search(line):
                continue
            prose.append(line)
        while prose and prose[-1].strip() == "":
            prose.pop()
        return "\n".join(prose)


# --- Frontmatter ---


class SpecFrontmatter(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    status: str
    owner: str
    team: str
    ticket_project: str | None = None
    created: str | None = None
    updated: str | None = None
    tags: list[str] = []
    doc_type: DocType = Field(default="spec", alias="type", serialization_alias="type")
    depends_on: list[str] = []
    supersedes: str | None = None
    review_status: ReviewStatus | None = None
    sync: Literal["true", "false", "auto"] = "auto"
    ai_exposure: AiExposure | None = None


# --- Diagnostics ---


class Diagnostic(BaseModel):
    severity: Literal["error", "warning", "info"]
    message: str
    line: int | None = None
    file_path: str | None = None


# --- Document ---


class SpecDocument(BaseModel):
    file_path: str
    frontmatter: SpecFrontmatter
    sections: list[SpecSection]
    raw: str


# --- Parse Options ---


def flatten_sections(sections: list[SpecSection]) -> list[SpecSection]:
    """Recursively flatten a section tree into a pre-order list."""
    result: list[SpecSection] = []
    for section in sections:
        result.append(section)
        if section.children:
            result.extend(flatten_sections(section.children))
    return result


def resolve_ai_exposure(
    frontmatter: SpecFrontmatter,
    restricted_tags: list[str] | None = None,
    config_default: AiExposure | None = None,
) -> AiExposure:
    """Resolve effective ai_exposure for a spec.

    Resolution order: frontmatter (if explicitly set) > restricted_tags match >
    CANON.yaml default > "full".
    """
    # If frontmatter explicitly sets ai_exposure, it always wins
    if frontmatter.ai_exposure is not None:
        return frontmatter.ai_exposure

    # Check restricted_tags match
    if restricted_tags and any(tag in restricted_tags for tag in frontmatter.tags):
        return "metadata"

    # CANON.yaml default
    if config_default and config_default in VALID_AI_EXPOSURES:
        return config_default

    return "full"


class ParseOptions(BaseModel):
    file_path: str | None = None
    include_content: bool = True


# --- Parse Result ---


class ParseResult(BaseModel):
    document: SpecDocument
    diagnostics: list[Diagnostic]
