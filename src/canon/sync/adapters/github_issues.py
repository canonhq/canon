"""GitHub Issues adapter."""

from __future__ import annotations

import re

import httpx

from canon.sync.adapters.base import AdapterCapabilities
from canon.sync.models import (
    CreateTicketInput,
    CreateTicketResult,
    GitHubConfig,
    SearchResult,
    TicketStatusResult,
    UpdateTicketInput,
)
from canon.sync.status_map import github_to_spec_status, spec_status_to_github

CANON_LABELS = [
    "canon:draft",
    "canon:todo",
    "canon:in-progress",
    "canon:done",
    "canon:blocked",
    "canon:deprecated",
    # Legacy labels for backwards compatibility
    "specwright:draft",
    "specwright:todo",
    "specwright:in-progress",
    "specwright:done",
    "specwright:blocked",
    "specwright:deprecated",
]


class ParsedTicketId:
    def __init__(self, owner: str, repo: str, issue_number: int) -> None:
        self.owner = owner
        self.repo = repo
        self.issue_number = issue_number


def parse_github_ticket_id(ticket_id: str, config: GitHubConfig) -> ParsedTicketId:
    """Resolve a ticket ID string into owner/repo/number."""
    # owner/repo#number
    full_match = re.match(r"^([^/]+)/([^#]+)#(\d+)$", ticket_id)
    if full_match:
        return ParsedTicketId(full_match.group(1), full_match.group(2), int(full_match.group(3)))

    # repo#number
    repo_match = re.match(r"^([^#]+)#(\d+)$", ticket_id)
    if repo_match:
        return ParsedTicketId(config.default_owner, repo_match.group(1), int(repo_match.group(2)))

    # bare number
    try:
        num = int(ticket_id)
        return ParsedTicketId(config.default_owner, config.default_repo, num)
    except ValueError:
        pass

    raise ValueError(f"Invalid GitHub ticket ID: {ticket_id}")


class GitHubAdapter:
    def __init__(self, config: GitHubConfig) -> None:
        self.config = config
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {config.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    @property
    def system_name(self) -> str:
        return "github"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_custom_fields=False,
            supports_hierarchy=False,
            supports_subtasks=False,
            supports_labels=True,
            supports_issue_types=False,
        )

    async def create_ticket(self, input: CreateTicketInput) -> CreateTicketResult:
        owner, repo = self.config.default_owner, self.config.default_repo
        target = spec_status_to_github(input.status)

        labels = [*input.labels, target.label]

        body: dict[str, object] = {
            "title": input.summary,
            "body": input.description or "",
            "labels": labels,
        }
        if input.assignees:
            body["assignees"] = input.assignees
        if input.milestone:
            milestone_id = await self._resolve_milestone_id(owner, repo, input.milestone)
            if milestone_id is not None:
                body["milestone"] = milestone_id

        res = await self._client.post(f"/repos/{owner}/{repo}/issues", json=body)
        res.raise_for_status()
        data = res.json()

        if target.state == "closed":
            await self._client.patch(
                f"/repos/{owner}/{repo}/issues/{data['number']}",
                json={"state": "closed"},
            )

        return CreateTicketResult(
            ticket_id=str(data["number"]),
            ticket_url=data["html_url"],
        )

    async def update_ticket(self, input: UpdateTicketInput) -> None:
        parsed = parse_github_ticket_id(input.ticket_id, self.config)

        patch: dict[str, object] = {}
        if input.summary:
            patch["title"] = input.summary
        if input.description:
            patch["body"] = input.description

        if input.status:
            target = spec_status_to_github(input.status)
            patch["state"] = target.state

            issue = await self._fetch_issue(parsed.owner, parsed.repo, parsed.issue_number)
            current_labels = [lb["name"] for lb in issue["labels"]]
            new_labels = [lb for lb in current_labels if lb not in CANON_LABELS]
            new_labels.append(target.label)
            patch["labels"] = new_labels

        if patch:
            res = await self._client.patch(
                f"/repos/{parsed.owner}/{parsed.repo}/issues/{parsed.issue_number}",
                json=patch,
            )
            res.raise_for_status()

    async def get_ticket_status(self, ticket_id: str) -> TicketStatusResult:
        parsed = parse_github_ticket_id(ticket_id, self.config)
        issue = await self._fetch_issue(parsed.owner, parsed.repo, parsed.issue_number)
        labels = [lb["name"] for lb in issue["labels"]]
        status = github_to_spec_status(issue["state"], labels)

        # Use the canon/specwright label as raw_status when present — this is the
        # meaningful status string for GitHub (analogous to "In QA" for Jira).
        # Without this, custom status_map.reverse keyed on "canon:*"
        # labels would never match the coarse "open"/"closed" state.
        canon_labels = [
            lb for lb in labels if lb.startswith("canon:") or lb.startswith("specwright:")
        ]
        raw_status = canon_labels[0] if canon_labels else issue["state"]

        return TicketStatusResult(ticket_id=ticket_id, status=status, raw_status=raw_status)

    async def link_pr(self, ticket_id: str, pr_url: str, pr_title: str) -> None:
        parsed = parse_github_ticket_id(ticket_id, self.config)
        res = await self._client.post(
            f"/repos/{parsed.owner}/{parsed.repo}/issues/{parsed.issue_number}/comments",
            json={"body": f"\U0001f517 PR linked: [{pr_title}]({pr_url})"},
        )
        res.raise_for_status()

    async def search_tickets(self, project_key: str, title_pattern: str) -> list[SearchResult]:
        """Search for existing issues matching a title pattern."""
        owner, repo = self.config.default_owner, self.config.default_repo
        query = f'repo:{owner}/{repo} "{title_pattern}" in:title is:issue'
        res = await self._client.get(
            "https://api.github.com/search/issues",
            params={"q": query, "per_page": 5},
        )
        res.raise_for_status()
        data = res.json()
        return [
            SearchResult(
                ticket_id=str(item["number"]),
                title=item["title"],
                ticket_url=item["html_url"],
                state=item["state"],
            )
            for item in data.get("items", [])
        ]

    async def update_task_list(
        self,
        parent_ticket_id: str,
        children: list[tuple[str, str]],
    ) -> None:
        """Append a sub-tasks section to a parent issue body.

        Args:
            parent_ticket_id: Issue number of the parent.
            children: List of (ticket_id, title) tuples.
        """
        parsed = parse_github_ticket_id(parent_ticket_id, self.config)
        issue = await self._fetch_issue(parsed.owner, parsed.repo, parsed.issue_number)
        current_body = str(issue.get("body", "") or "")

        task_lines = [f"- [ ] #{tid} — {title}" for tid, title in children]
        task_section = "\n\n## Sub-tasks\n" + "\n".join(task_lines)

        # Replace existing sub-tasks section or append
        if "## Sub-tasks" in current_body:
            # Replace from "## Sub-tasks" to end or next heading
            new_body = re.sub(
                r"## Sub-tasks\n(?:- \[[ x]\] #\d+.*\n?)*",
                "## Sub-tasks\n" + "\n".join(task_lines) + "\n",
                current_body,
            )
        else:
            new_body = current_body + task_section

        res = await self._client.patch(
            f"/repos/{parsed.owner}/{parsed.repo}/issues/{parsed.issue_number}",
            json={"body": new_body},
        )
        res.raise_for_status()

    async def _resolve_milestone_id(self, owner: str, repo: str, milestone_name: str) -> int | None:
        """Resolve a milestone name to its GitHub ID."""
        res = await self._client.get(
            f"/repos/{owner}/{repo}/milestones",
            params={"state": "open", "per_page": 100},
        )
        res.raise_for_status()
        for ms in res.json():
            if ms["title"] == milestone_name:
                return ms["number"]
        return None

    async def _fetch_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, object]:
        res = await self._client.get(f"/repos/{owner}/{repo}/issues/{issue_number}")
        res.raise_for_status()
        return res.json()  # type: ignore[no-any-return]
