"""Canon API proxy adapter — routes ticket operations through the server."""

from __future__ import annotations

from canon.cli._platform import PlatformClient
from canon.sync.adapters.base import AdapterCapabilities
from canon.sync.models import (
    CreateTicketInput,
    CreateTicketResult,
    TicketStatusResult,
    UpdateTicketInput,
)


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

    def __init__(self, client: PlatformClient, org: str, owner: str, repo: str) -> None:
        self._client = client
        self._org = org
        self._owner = owner
        self._repo = repo

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(supports_labels=True)

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        resp = self._client.post(
            f"/app/{self._org}/api/tickets/create",
            json={"owner": self._owner, "repo": self._repo, "input": input.model_dump(mode="json")},
        )
        resp.raise_for_status()
        return CreateTicketResult(**resp.json())

    async def get_ticket_status(self, ticket_id: str) -> TicketStatusResult:
        resp = self._client.post(
            f"/app/{self._org}/api/tickets/status",
            json={"owner": self._owner, "repo": self._repo, "ticket_id": ticket_id},
        )
        resp.raise_for_status()
        return TicketStatusResult(**resp.json())

    async def update_ticket(self, input: UpdateTicketInput) -> None:
        resp = self._client.post(
            f"/app/{self._org}/api/tickets/update",
            json={"owner": self._owner, "repo": self._repo, "input": input.model_dump(mode="json")},
        )
        resp.raise_for_status()

    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None:
        resp = self._client.post(
            f"/app/{self._org}/api/tickets/link-pr",
            json={
                "owner": self._owner,
                "repo": self._repo,
                "ticket_id": ticket_id,
                "pr_url": pr_url,
                "pr_title": pr_title,
            },
        )
        resp.raise_for_status()
