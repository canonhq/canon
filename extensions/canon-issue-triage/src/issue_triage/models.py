"""Data models for issue triage results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class IssueCategory(StrEnum):
    FEATURE_REQUEST = "feature-request"
    BUG_REPORT = "bug-report"
    QUESTION = "question"
    DUPLICATE = "duplicate"
    SUPPORT = "support"


@dataclass
class SpecMatch:
    """A spec file matched to an issue by relevance."""

    path: str
    relevance: float  # 0.0 - 1.0
    section: str | None = None  # e.g. "3.2"
    title: str = ""


@dataclass
class TriageResult:
    """The complete result of triaging an issue."""

    classification: IssueCategory
    confidence: float  # 0.0 - 1.0
    reasoning: str
    related_specs: list[SpecMatch] = field(default_factory=list)
    suggested_labels: list[str] = field(default_factory=list)
    duplicate_of: int | None = None  # issue number if duplicate


@dataclass
class IssueContext:
    """Context about the issue being triaged."""

    number: int
    title: str
    body: str
    author: str
    labels: list[str] = field(default_factory=list)
    repo_owner: str = ""
    repo_name: str = ""
