"""Jira REST v3 adapter with retry logic and rate limiting."""

from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from canon.sync.adapters.base import AdapterCapabilities
from canon.sync.models import (
    CreateTicketInput,
    CreateTicketResult,
    JiraConfig,
    SearchResult,
    TicketStatusResult,
    UpdateTicketInput,
)
from canon.sync.status_map import jira_category_to_spec_status, spec_status_to_jira

logger = logging.getLogger(__name__)

# Transient HTTP status codes that should be retried
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds


class JiraValidationError(Exception):
    """Raised when Jira configuration is invalid."""


class JiraAdapter:
    def __init__(self, config: JiraConfig) -> None:
        self.config = config
        if config.auth_method == "oauth" and config.access_token:
            # OAuth mode: use Bearer token with Atlassian cloud API
            base_url = f"https://api.atlassian.com/ex/jira/{config.cloud_id}/rest/api/3"
            headers = {
                "Authorization": f"Bearer {config.access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        else:
            # API token mode (default)
            creds = base64.b64encode(f"{config.email}:{config.api_token}".encode()).decode()
            base_url = f"https://{config.host}/rest/api/3"
            headers = {
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=30.0,
        )

    @property
    def system_name(self) -> str:
        return "jira"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_custom_fields=True,
            supports_hierarchy=True,
            supports_subtasks=True,
            supports_labels=True,
            supports_issue_types=True,
        )

    async def validate_config(self, project_key: str) -> None:
        """Validate Jira connection and project configuration.

        Raises JiraValidationError if the project doesn't exist or
        credentials are invalid.
        """
        try:
            res = await self._request("GET", f"/project/{project_key}")
            logger.info("Jira project %s validated: %s", project_key, res.get("name", "?"))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise JiraValidationError("Invalid Jira credentials") from e
            if e.response.status_code == 404:
                raise JiraValidationError(f"Jira project '{project_key}' not found") from e
            raise JiraValidationError(f"Jira API error: {e.response.status_code}") from e

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        issue_type = "Sub-task" if input.parent_ticket_id else "Task"

        body = {
            "fields": {
                "project": {"key": input.project_key},
                "summary": input.summary,
                "issuetype": {"name": issue_type},
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": input.description or "No description",
                                }
                            ],
                        }
                    ],
                },
                **({"parent": {"key": input.parent_ticket_id}} if input.parent_ticket_id else {}),
                **({"labels": input.labels} if input.labels else {}),
            }
        }

        data = await self._request("POST", "/issue", json=body)

        target_status = spec_status_to_jira(input.status)
        if target_status != "Backlog":
            await self._transition_to(data["key"], target_status)

        logger.info("Created Jira ticket %s for project %s", data["key"], input.project_key)

        return CreateTicketResult(
            ticket_id=data["key"],
            ticket_url=f"https://{self.config.host}/browse/{data['key']}",
        )

    async def update_ticket(self, input: UpdateTicketInput) -> None:
        fields: dict[str, object] = {}

        if input.summary:
            fields["summary"] = input.summary
        if input.description:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": input.description}],
                    }
                ],
            }

        if fields:
            await self._request("PUT", f"/issue/{input.ticket_id}", json={"fields": fields})

        if input.status:
            target_status = spec_status_to_jira(input.status)
            await self._transition_to(input.ticket_id, target_status)

    async def get_ticket_status(self, ticket_id: str) -> TicketStatusResult:
        data = await self._request("GET", f"/issue/{ticket_id}?fields=status")

        raw_status = data["fields"]["status"]["name"]
        category_key = data["fields"]["status"]["statusCategory"]["key"]
        status = jira_category_to_spec_status(category_key)

        return TicketStatusResult(ticket_id=ticket_id, status=status, raw_status=raw_status)

    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None:
        await self._request(
            "POST",
            f"/issue/{ticket_id}/remotelink",
            json={
                "object": {
                    "url": pr_url,
                    "title": pr_title,
                    "icon": {
                        "url16x16": "https://github.com/favicon.ico",
                        "title": "GitHub PR",
                    },
                }
            },
        )

    async def search_tickets(self, project_key: str, title_pattern: str) -> list[SearchResult]:
        """Search for existing Jira issues matching a title pattern."""
        jql = f'project = "{project_key}" AND summary ~ "{title_pattern}" ORDER BY created ASC'
        data = await self._request("GET", f"/search?jql={jql}&maxResults=5&fields=summary,status")
        return [
            SearchResult(
                ticket_id=issue["key"],
                title=issue["fields"]["summary"],
                ticket_url=f"https://{self.config.host}/browse/{issue['key']}",
                state="closed"
                if issue["fields"]["status"]["statusCategory"]["key"] == "done"
                else "open",
            )
            for issue in data.get("issues", [])
        ]

    async def _transition_to(self, ticket_id: str, target_status_name: str) -> None:
        data = await self._request("GET", f"/issue/{ticket_id}/transitions")

        transition = next(
            (t for t in data["transitions"] if t["name"].lower() == target_status_name.lower()),
            None,
        )

        if not transition:
            logger.warning(
                "No transition to '%s' available for %s",
                target_status_name,
                ticket_id,
            )
            return

        await self._request(
            "POST",
            f"/issue/{ticket_id}/transitions",
            json={"transition": {"id": transition["id"]}},
        )

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
    ) -> dict:
        """Make a Jira API request with retry and rate limit handling."""
        last_exc: Exception | None = None
        backoff = INITIAL_BACKOFF

        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, path, json=json)
                resp.raise_for_status()
                if resp.status_code == 204 or not resp.content:
                    return {}
                return resp.json()
            except httpx.HTTPStatusError as e:
                last_exc = e
                status = e.response.status_code

                if status not in RETRYABLE_STATUS_CODES or attempt == MAX_RETRIES:
                    raise

                # Respect Retry-After header for 429
                retry_after = e.response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        wait = backoff
                else:
                    wait = backoff

                logger.warning(
                    "Jira API %s %s returned %d, retrying in %.1fs (attempt %d/%d)",
                    method,
                    path,
                    status,
                    wait,
                    attempt + 1,
                    MAX_RETRIES,
                )
                await asyncio.sleep(wait)
                backoff *= 2

            except httpx.ConnectError as e:
                last_exc = e
                if attempt == MAX_RETRIES:
                    raise
                logger.warning(
                    "Jira connection error for %s %s, retrying in %.1fs",
                    method,
                    path,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff *= 2

        raise last_exc  # type: ignore[misc]
