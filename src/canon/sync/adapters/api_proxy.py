"""Canon API proxy adapter — routes ticket operations through the server."""

from __future__ import annotations

import contextlib

from canon.cli._platform import PlatformClient
from canon.sync.adapters.base import AdapterCapabilities
from canon.sync.models import (
    CreateTicketInput,
    CreateTicketResult,
    SearchResult,
    TicketStatusResult,
    UpdateTicketInput,
)

# Capabilities per ticket system (static — avoids an extra round-trip).
_CAPABILITIES = {
    "github": AdapterCapabilities(supports_labels=True),
    "jira": AdapterCapabilities(
        supports_custom_fields=True,
        supports_hierarchy=True,
        supports_subtasks=True,
        supports_labels=True,
        supports_issue_types=True,
    ),
    "linear": AdapterCapabilities(),
}


class CanonApiAdapter:
    """TicketAdapter that proxies operations through the Canon API.

    Uses ``PlatformClient`` (synchronous httpx) for authenticated HTTP.
    The sync engine calls adapter methods with ``await``, but since the CLI
    runs single-threaded via ``asyncio.run()``, the synchronous HTTP calls
    execute inline without issue.

    Warning: This adapter is not safe for concurrent async use (e.g.
    ``asyncio.gather``).  The synchronous HTTP calls will serialize and
    block the event loop for the duration of each request.
    """

    def __init__(
        self,
        client: PlatformClient,
        org: str,
        owner: str,
        repo: str,
        *,
        ticket_system: str = "github",
        project_key: str = "",
    ) -> None:
        self._client = client
        self._org = org
        self._owner = owner
        self._repo = repo
        self._ticket_system = ticket_system
        self._project_key = project_key

    @property
    def system_name(self) -> str:
        return self._ticket_system

    @property
    def capabilities(self) -> AdapterCapabilities:
        return _CAPABILITIES.get(self._ticket_system, AdapterCapabilities())

    @staticmethod
    def _check_response(resp) -> None:
        """Raise with server's error detail when available, else raise_for_status."""
        if resp.is_success:
            return
        detail = ""
        with contextlib.suppress(Exception):
            detail = resp.json().get("detail", "")
        if detail:
            raise RuntimeError(f"Canon server error ({resp.status_code}): {detail}")
        resp.raise_for_status()

    def _base_body(self) -> dict:
        """Fields included in every request for system routing."""
        body: dict = {"ticket_system": self._ticket_system}
        if self._owner:
            body["owner"] = self._owner
        if self._repo:
            body["repo"] = self._repo
        if self._project_key:
            body["project_key"] = self._project_key
        return body

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        body = self._base_body()
        body["input"] = input.model_dump(mode="json")
        resp = self._client.post(f"/app/{self._org}/api/tickets/create", json=body)
        self._check_response(resp)
        return CreateTicketResult(**resp.json())

    async def get_ticket_status(self, ticket_id: str) -> TicketStatusResult:
        body = self._base_body()
        body["ticket_id"] = ticket_id
        resp = self._client.post(f"/app/{self._org}/api/tickets/status", json=body)
        self._check_response(resp)
        return TicketStatusResult(**resp.json())

    async def update_ticket(self, input: UpdateTicketInput) -> None:
        body = self._base_body()
        body["input"] = input.model_dump(mode="json")
        resp = self._client.post(f"/app/{self._org}/api/tickets/update", json=body)
        self._check_response(resp)

    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None:
        body = self._base_body()
        body["ticket_id"] = ticket_id
        body["pr_url"] = pr_url
        body["pr_title"] = pr_title
        resp = self._client.post(f"/app/{self._org}/api/tickets/link-pr", json=body)
        self._check_response(resp)

    async def search_tickets(self, project_key: str, title_pattern: str) -> list[SearchResult]:
        body = self._base_body()
        body["project_key"] = project_key
        body["title_pattern"] = title_pattern
        resp = self._client.post(f"/app/{self._org}/api/tickets/search", json=body)
        self._check_response(resp)
        return [SearchResult(**r) for r in resp.json()]
