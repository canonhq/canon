"""TicketAdapter protocol — base interface for all adapters."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from canon.sync.models import (
    CreateTicketInput,
    CreateTicketResult,
    SearchResult,
    TicketStatusResult,
    UpdateTicketInput,
)


class AdapterCapabilities(BaseModel):
    """Declares what features an adapter supports."""

    supports_custom_fields: bool = False
    supports_hierarchy: bool = False
    supports_subtasks: bool = False
    supports_labels: bool = False
    supports_issue_types: bool = False


class TicketAdapter(Protocol):
    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult: ...
    async def update_ticket(self, input: UpdateTicketInput) -> None: ...
    async def get_ticket_status(self, ticket_id: str) -> TicketStatusResult: ...
    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None: ...
    async def search_tickets(self, project_key: str, title_pattern: str) -> list[SearchResult]: ...

    @property
    def system_name(self) -> str:
        """Return the canonical ticket system name (e.g. 'github', 'jira', 'linear')."""
        ...

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return adapter capabilities.

        Implementors must override this property — Protocol method bodies
        are not inherited by implementing classes in Python.
        """
        ...
