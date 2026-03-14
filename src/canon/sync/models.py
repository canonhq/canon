"""Pydantic models for ticket sync."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from canon.parser.models import SectionStatus


class SearchResult(BaseModel):
    """A ticket found by search_tickets."""

    ticket_id: str
    title: str
    ticket_url: str
    state: str  # "open" or "closed"


class CreateTicketInput(BaseModel):
    project_key: str
    summary: str
    description: str
    parent_ticket_id: str | None = None
    status: SectionStatus
    labels: list[str] = []
    issue_type: str = "Task"
    custom_fields: dict[str, Any] = {}
    assignees: list[str] = []
    milestone: str | None = None


class UpdateTicketInput(BaseModel):
    ticket_id: str
    summary: str | None = None
    description: str | None = None
    status: SectionStatus | None = None
    custom_fields: dict[str, Any] = {}


class CreateTicketResult(BaseModel):
    ticket_id: str
    ticket_url: str


class TicketStatusResult(BaseModel):
    ticket_id: str
    status: SectionStatus
    raw_status: str


class SyncCreated(BaseModel):
    section_id: str
    ticket_id: str
    ticket_url: str


class SyncUpdated(BaseModel):
    section_id: str
    ticket_id: str


class SyncStatusChanged(BaseModel):
    section_id: str
    ticket_id: str
    old_state: str
    new_state: str


class SyncSkipped(BaseModel):
    section_id: str
    reason: str


class SyncError(BaseModel):
    section_id: str
    error: str


class SyncResult(BaseModel):
    created: list[SyncCreated] = []
    updated: list[SyncUpdated] = []
    status_changed: list[SyncStatusChanged] = []
    skipped: list[SyncSkipped] = []
    errors: list[SyncError] = []


class JiraConfig(BaseModel):
    host: str
    email: str
    api_token: str


class LinearConfig(BaseModel):
    api_key: str


class GitHubConfig(BaseModel):
    token: str
    default_owner: str
    default_repo: str
