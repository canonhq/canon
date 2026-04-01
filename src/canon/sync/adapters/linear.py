"""Linear GraphQL adapter."""

from __future__ import annotations

from typing import Any

import httpx

from canon.sync.adapters.base import AdapterCapabilities
from canon.sync.models import (
    CreateTicketInput,
    CreateTicketResult,
    LinearConfig,
    SearchResult,
    TicketStatusResult,
    UpdateTicketInput,
)
from canon.sync.status_map import linear_type_to_spec_status, spec_status_to_linear

LINEAR_API = "https://api.linear.app/graphql"


class LinearAdapter:
    def __init__(self, config: LinearConfig) -> None:
        self.config = config
        token = config.effective_token
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token}"
                if config.access_token and not config.api_key
                else token,
                "Content-Type": "application/json",
            },
        )

    @property
    def system_name(self) -> str:
        return "linear"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_custom_fields=False,
            supports_hierarchy=True,
            supports_subtasks=True,
            supports_labels=True,
            supports_issue_types=False,
        )

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        team_id = await self._resolve_team_id(input.project_key)
        target_state_name = spec_status_to_linear(input.status)
        state_id = await self._resolve_state_id(team_id, target_state_name)

        mutation_input: dict[str, Any] = {
            "teamId": team_id,
            "title": input.summary,
            "description": input.description or None,
            "stateId": state_id,
        }

        if input.parent_ticket_id:
            mutation_input["parentId"] = await self._resolve_issue_id(input.parent_ticket_id)
        if input.labels:
            mutation_input["labelIds"] = await self._resolve_label_ids(team_id, input.labels)

        res = await self._gql(
            """mutation($input: IssueCreateInput!) {
                issueCreate(input: $input) {
                    success
                    issue { identifier url }
                }
            }""",
            {"input": mutation_input},
        )

        return CreateTicketResult(
            ticket_id=res["issueCreate"]["issue"]["identifier"],
            ticket_url=res["issueCreate"]["issue"]["url"],
        )

    async def update_ticket(self, input: UpdateTicketInput) -> None:
        issue_id = await self._resolve_issue_id(input.ticket_id)
        update_input: dict[str, Any] = {}

        if input.summary:
            update_input["title"] = input.summary
        if input.description:
            update_input["description"] = input.description

        if input.status:
            issue = await self._gql(
                "query($id: String!) { issue(id: $id) { team { id } } }",
                {"id": issue_id},
            )
            target_state_name = spec_status_to_linear(input.status)
            state_id = await self._resolve_state_id(issue["issue"]["team"]["id"], target_state_name)
            update_input["stateId"] = state_id

        if not update_input:
            return

        await self._gql(
            """mutation($id: String!, $input: IssueUpdateInput!) {
                issueUpdate(id: $id, input: $input) { success }
            }""",
            {"id": issue_id, "input": update_input},
        )

    async def get_ticket_status(self, ticket_id: str) -> TicketStatusResult:
        issue_id = await self._resolve_issue_id(ticket_id)
        res = await self._gql(
            "query($id: String!) { issue(id: $id) { state { name type } } }",
            {"id": issue_id},
        )

        raw_status = res["issue"]["state"]["name"]
        status = linear_type_to_spec_status(res["issue"]["state"]["type"])

        return TicketStatusResult(ticket_id=ticket_id, status=status, raw_status=raw_status)

    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None:
        issue_id = await self._resolve_issue_id(ticket_id)
        await self._gql(
            """mutation($input: AttachmentCreateInput!) {
                attachmentCreate(input: $input) { success }
            }""",
            {"input": {"issueId": issue_id, "url": pr_url, "title": pr_title}},
        )

    async def search_tickets(self, project_key: str, title_pattern: str) -> list[SearchResult]:
        """Search for existing Linear issues matching a title pattern."""
        res = await self._gql(
            """query($q: String!) {
                issueSearch(query: $q, first: 5) {
                    nodes { identifier title url state { name type } }
                }
            }""",
            {"q": title_pattern},
        )
        return [
            SearchResult(
                ticket_id=node["identifier"],
                title=node["title"],
                ticket_url=node["url"],
                state="closed" if node["state"]["type"] in ("completed", "canceled") else "open",
            )
            for node in res["issueSearch"]["nodes"]
        ]

    # --- Private helpers ---

    async def _resolve_team_id(self, team_key: str) -> str:
        res = await self._gql("{ teams { nodes { id key } } }")
        team = next((t for t in res["teams"]["nodes"] if t["key"] == team_key), None)
        if not team:
            raise ValueError(f"Linear team not found: {team_key}")
        return team["id"]  # type: ignore[no-any-return]

    async def _resolve_state_id(self, team_id: str, state_name: str) -> str:
        res = await self._gql(
            """query($name: String!) {
                workflowStates(filter: { name: { eq: $name } }) {
                    nodes { id name team { id } }
                }
            }""",
            {"name": state_name},
        )
        state = next(
            (s for s in res["workflowStates"]["nodes"] if s["team"]["id"] == team_id),
            None,
        )
        if not state:
            raise ValueError(f'Linear state "{state_name}" not found for team {team_id}')
        return state["id"]  # type: ignore[no-any-return]

    async def _resolve_issue_id(self, identifier: str) -> str:
        res = await self._gql(
            """query($q: String!) {
                issueSearch(query: $q, first: 1) {
                    nodes { id identifier }
                }
            }""",
            {"q": identifier},
        )
        issue = res["issueSearch"]["nodes"][0] if res["issueSearch"]["nodes"] else None
        if not issue:
            raise ValueError(f"Linear issue not found: {identifier}")
        return issue["id"]  # type: ignore[no-any-return]

    async def _resolve_label_ids(self, team_id: str, labels: list[str]) -> list[str]:
        res = await self._gql("{ issueLabels { nodes { id name team { id } } } }")
        return [
            node["id"]
            for node in res["issueLabels"]["nodes"]
            if node["name"] in labels and (node["team"] is None or node["team"]["id"] == team_id)
        ]

    async def _gql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        res = await self._client.post(
            LINEAR_API,
            json={"query": query, **({"variables": variables} if variables else {})},
        )
        if not res.is_success:
            raise RuntimeError(f"Linear API {res.status_code}: {res.text}")

        json_data = res.json()
        if json_data.get("errors"):
            raise RuntimeError(f"Linear GraphQL: {json_data['errors'][0]['message']}")
        return json_data["data"]  # type: ignore[no-any-return]
