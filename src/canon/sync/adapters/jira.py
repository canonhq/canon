"""Jira REST v3 adapter with retry logic, rate limiting, and OAuth token refresh."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from canon.db.integration_store import IntegrationStore

logger = logging.getLogger(__name__)

# Transient HTTP status codes that should be retried
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds

ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"


class JiraValidationError(Exception):
    """Raised when Jira configuration is invalid."""


class JiraAuthError(Exception):
    """Raised when token refresh fails and re-authorization is required."""


class JiraAdapter:
    def __init__(
        self,
        config: JiraConfig,
        *,
        store: IntegrationStore | None = None,
        org_login: str = "",
        jira_client_id: str = "",
        jira_client_secret: str = "",
    ) -> None:
        self.config = config
        self._store = store
        self._org_login = org_login
        self._jira_client_id = jira_client_id
        self._jira_client_secret = jira_client_secret
        self._refreshed = False  # guard against infinite refresh loops
        self._build_client()

    def _build_client(self) -> None:
        """(Re)build the HTTP client from current config."""
        if self.config.auth_method == "oauth" and self.config.access_token:
            base_url = f"https://api.atlassian.com/ex/jira/{self.config.cloud_id}/rest/api/3"
            headers = {
                "Authorization": f"Bearer {self.config.access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        else:
            creds = base64.b64encode(
                f"{self.config.email}:{self.config.api_token}".encode()
            ).decode()
            base_url = f"https://{self.config.host}/rest/api/3"
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
    def _browse_base_url(self) -> str:
        """Base URL for human-readable ticket links."""
        if self.config.site_url:
            return self.config.site_url.rstrip("/")
        if self.config.host:
            return f"https://{self.config.host}"
        return f"https://{self.config.cloud_id}.atlassian.net"

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
            ticket_url=f"{self._browse_base_url}/browse/{data['key']}",
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
        """Search for existing Jira issues matching a title pattern.

        Uses /rest/api/3/search/jql. The older /rest/api/3/search endpoint
        was retired by Atlassian and now returns 410 Gone. The JQL-variant
        endpoint uses ``nextPageToken``/``isLast`` instead of
        ``startAt``/``total`` for pagination, but we only read ``issues[]``
        which is stable across both.
        """
        # Sanitize inputs to prevent JQL injection — strip quotes and backslashes
        safe_project = project_key.replace("\\", "").replace('"', "")
        safe_pattern = title_pattern.replace("\\", "").replace('"', "")
        jql = f'project = "{safe_project}" AND summary ~ "{safe_pattern}" ORDER BY created ASC'
        data = await self._request(
            "GET",
            "/search/jql",
            params={"jql": jql, "maxResults": "5", "fields": "summary,status"},
        )
        return [
            SearchResult(
                ticket_id=issue["key"],
                title=issue["fields"]["summary"],
                ticket_url=f"{self._browse_base_url}/browse/{issue['key']}",
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

    async def _refresh_tokens(self) -> bool:
        """Refresh the OAuth access token using the stored refresh token.

        Returns True if the refresh succeeded, False otherwise.
        On success, persists updated tokens to the integration store.
        """
        if not self.config.refresh_token:
            logger.warning("Jira token refresh failed: no refresh_token stored")
            return False
        if not self._jira_client_id or not self._jira_client_secret:
            logger.warning("Jira token refresh failed: missing OAuth client credentials")
            return False

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                ATLASSIAN_TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "client_id": self._jira_client_id,
                    "client_secret": self._jira_client_secret,
                    "refresh_token": self.config.refresh_token,
                },
            )

        if resp.status_code != 200:
            err_msg = f"Token refresh failed: HTTP {resp.status_code}"
            logger.warning(
                "Jira token refresh failed: HTTP %d — %s",
                resp.status_code,
                resp.text[:200],
            )
            if self._store and self._org_login:
                await self._store.update_status(
                    self._org_login, "jira", "needs_reauth", error=err_msg
                )
            return False

        data = resp.json()
        new_access = data["access_token"]
        new_refresh = data.get("refresh_token", self.config.refresh_token)

        # Update in-memory config and rebuild the HTTP client
        self.config = self.config.model_copy(
            update={"access_token": new_access, "refresh_token": new_refresh}
        )
        self._build_client()

        # Persist to DB
        if self._store and self._org_login:
            new_config = {
                "access_token": new_access,
                "refresh_token": new_refresh,
                "cloud_id": self.config.cloud_id,
                "site_url": self.config.site_url,
            }
            await self._store.update_config(
                self._org_login,
                "jira",
                config=new_config,
                provider_metadata=None,  # preserve existing metadata
            )
            logger.info("Jira tokens refreshed and persisted for org %s", self._org_login)

        return True

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Make a Jira API request with retry, rate limit, and token refresh."""
        last_exc: Exception | None = None
        backoff = INITIAL_BACKOFF

        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, path, json=json, params=params)
                resp.raise_for_status()
                if resp.status_code == 204 or not resp.content:
                    return {}
                return resp.json()
            except httpx.HTTPStatusError as e:
                last_exc = e
                status = e.response.status_code

                # On 401 in OAuth mode, attempt a single token refresh
                if status == 401 and self.config.auth_method == "oauth" and not self._refreshed:
                    self._refreshed = True
                    if await self._refresh_tokens():
                        logger.info("Retrying %s %s after token refresh", method, path)
                        continue  # retry with new token
                    raise JiraAuthError(
                        "Jira access token expired and refresh failed — re-authorize via Settings"
                    ) from e

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
