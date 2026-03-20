"""GitHub API client with App JWT auth and installation token exchange."""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass

import httpx
import jwt

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class InstallationNotFound(Exception):
    """Raised when a GitHub App installation ID no longer exists (404)."""

    def __init__(self, installation_id: int | str) -> None:
        self.installation_id = int(installation_id)
        super().__init__(
            f"GitHub App installation {installation_id} not found — "
            "it may have been removed or reinstalled with a new ID"
        )


@dataclass
class FileChange:
    """A file to create or update in a commit."""

    path: str
    content: str


@dataclass
class DocPRResult:
    """Result of creating or updating a doc-update PR."""

    pr_number: int
    pr_url: str


class GitHubClient:
    """Authenticated GitHub API client using App installation tokens."""

    def __init__(
        self,
        *,
        app_id: str,
        private_key: str,
        installation_id: str = "",
    ) -> None:
        self.app_id = app_id
        self.private_key = private_key.replace("\\n", "\n")
        self.installation_id = installation_id
        self._token: str = ""
        self._token_expires: float = 0
        self._http = httpx.AsyncClient(
            base_url=GITHUB_API,
            timeout=30.0,
            headers={"Accept": "application/vnd.github+json"},
        )

    async def close(self) -> None:
        await self._http.aclose()

    # ─── Auth ─────────────────────────────────────────

    def _generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication."""
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": self.app_id,
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    async def _get_installation_token(self) -> str:
        """Exchange JWT for an installation access token.

        Raises ``InstallationNotFound`` when GitHub returns 404, indicating
        the installation was removed or the ID is stale.
        """
        if self._token and time.time() < self._token_expires:
            return self._token

        app_jwt = self._generate_jwt()
        resp = await self._http.post(
            f"/app/installations/{self.installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}"},
        )
        if resp.status_code == 404:
            raise InstallationNotFound(self.installation_id)
        resp.raise_for_status()
        data = resp.json()
        self._token = data["token"]
        self._token_expires = time.time() + 3300  # 55 min (tokens last 1h)
        return self._token

    async def get_installation_token(self) -> str:
        """Return a valid installation access token (cached, auto-refreshed)."""
        return await self._get_installation_token()

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._get_installation_token()
        return {"Authorization": f"token {token}"}

    # ─── API helpers ──────────────────────────────────

    async def _get(self, path: str, **params: str) -> dict:
        headers = await self._auth_headers()
        resp = await self._http.get(path, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _get_list(self, path: str, **params: str) -> list[dict]:
        """GET that returns a JSON array (issues, files, directory listings)."""
        headers = await self._auth_headers()
        resp = await self._http.get(path, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise TypeError(f"Expected JSON array from {path}, got {type(data).__name__}")
        return data

    async def _post(self, path: str, json: dict | None = None) -> dict:
        headers = await self._auth_headers()
        resp = await self._http.post(path, headers=headers, json=json)
        resp.raise_for_status()
        return resp.json()

    async def _patch(self, path: str, json: dict | None = None) -> dict:
        headers = await self._auth_headers()
        resp = await self._http.patch(path, headers=headers, json=json)
        resp.raise_for_status()
        return resp.json()

    async def _put(self, path: str, json: dict | None = None) -> dict:
        headers = await self._auth_headers()
        resp = await self._http.put(path, headers=headers, json=json)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str) -> None:
        headers = await self._auth_headers()
        resp = await self._http.delete(path, headers=headers)
        resp.raise_for_status()

    # ─── Factory ───────────────────────────────────────

    def for_installation(self, installation_id: str) -> GitHubClient:
        """Return a new client scoped to a different installation.

        Reuses app_id and private_key but issues tokens for the given
        installation_id.
        """
        return GitHubClient(
            app_id=self.app_id,
            private_key=self.private_key,
            installation_id=installation_id,
        )

    # ─── Installation ──────────────────────────────────

    async def list_installation_repos(self) -> list[dict]:
        """List all repositories accessible to this installation (paginated)."""
        all_repos: list[dict] = []
        page = 1

        while True:
            headers = await self._auth_headers()
            resp = await self._http.get(
                "/installation/repositories",
                headers=headers,
                params={"per_page": "100", "page": str(page)},
            )
            resp.raise_for_status()
            data = resp.json()
            repos = data.get("repositories", [])
            all_repos.extend(repos)

            total_count = data.get("total_count", 0)
            if len(all_repos) >= total_count or not repos:
                break
            page += 1

        return all_repos

    async def get_default_branch(self, owner: str, repo: str) -> str:
        """Return the default branch name for a repository."""
        data = await self._get(f"/repos/{owner}/{repo}")
        return data.get("default_branch", "main")

    # ─── Repo content ─────────────────────────────────

    async def get_file_content(
        self, owner: str, repo: str, path: str, ref: str | None = None
    ) -> tuple[str, str]:
        """Fetch a file's content and SHA.

        Returns:
            (content_string, file_sha)
        """
        params = {}
        if ref:
            params["ref"] = ref
        data = await self._get(f"/repos/{owner}/{repo}/contents/{path}", **params)
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]

    async def list_directory(
        self, owner: str, repo: str, path: str, ref: str | None = None
    ) -> list[dict]:
        """List files in a directory. Returns empty list on 404."""
        params = {}
        if ref:
            params["ref"] = ref
        try:
            return await self._get_list(f"/repos/{owner}/{repo}/contents/{path}", **params)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise

    async def create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        sha: str | None = None,
        branch: str | None = None,
    ) -> dict:
        """Create or update a file via the Contents API."""
        payload: dict = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        }
        if sha:
            payload["sha"] = sha
        if branch:
            payload["branch"] = branch
        return await self._put(f"/repos/{owner}/{repo}/contents/{path}", json=payload)

    # ─── Comments ─────────────────────────────────────

    async def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict]:
        """List comments on an issue or PR."""
        return await self._get_list(f"/repos/{owner}/{repo}/issues/{issue_number}/comments")

    async def create_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict:
        """Create a comment on an issue or PR."""
        return await self._post(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )

    async def update_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict:
        """Update an existing comment."""
        return await self._patch(
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
            json={"body": body},
        )

    async def delete_comment(self, owner: str, repo: str, comment_id: int) -> None:
        """Delete a comment."""
        await self._delete(f"/repos/{owner}/{repo}/issues/comments/{comment_id}")

    # ─── Issues ────────────────────────────────────────

    async def ensure_label(
        self,
        owner: str,
        repo: str,
        name: str,
        *,
        color: str = "0075ca",
        description: str = "",
    ) -> None:
        """Create a label if it doesn't already exist. Ignores 422 (duplicate)."""
        try:
            await self._post(
                f"/repos/{owner}/{repo}/labels",
                json={"name": name, "color": color, "description": description},
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:
                pass  # 422 Unprocessable Entity — GitHub uses this for duplicate label names
            else:
                raise

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> dict:
        """Create a new issue."""
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return await self._post(f"/repos/{owner}/{repo}/issues", json=payload)

    async def list_issues(
        self,
        owner: str,
        repo: str,
        labels: str | None = None,
        state: str | None = None,
        per_page: int = 100,
    ) -> list[dict]:
        """List issues, optionally filtered by labels and state.

        Note: returns a single page (up to ``per_page``). Callers that need
        exhaustive results must paginate themselves.
        """
        params: dict[str, str] = {"per_page": str(per_page)}
        if labels:
            params["labels"] = labels
        if state:
            params["state"] = state
        return await self._get_list(f"/repos/{owner}/{repo}/issues", **params)

    async def update_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> dict:
        """Update an existing issue. Only includes non-None fields in the payload."""
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if labels is not None:
            payload["labels"] = labels
        return await self._patch(f"/repos/{owner}/{repo}/issues/{issue_number}", json=payload)

    # ─── PR files ─────────────────────────────────────

    async def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict:
        """Get PR details."""
        return await self._get(f"/repos/{owner}/{repo}/pulls/{pull_number}")

    async def list_pull_files(self, owner: str, repo: str, pull_number: int) -> list[dict]:
        """List files changed in a PR (first page, up to 100).

        PRs with >100 changed files will be silently truncated.
        TODO: auto-paginate or return a truncation flag if needed.
        """
        return await self._get_list(
            f"/repos/{owner}/{repo}/pulls/{pull_number}/files", per_page="100"
        )

    async def list_pull_reviews(self, owner: str, repo: str, pull_number: int) -> list[dict]:
        """List reviews on a pull request."""
        return await self._get_list(f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews")

    # ─── Doc PRs (Git Data API) ───────────────────────

    async def _get_default_branch(self, owner: str, repo: str) -> str:
        data = await self._get(f"/repos/{owner}/{repo}")
        return data["default_branch"]

    async def create_doc_pr(
        self,
        owner: str,
        repo: str,
        *,
        branch: str,
        base: str | None = None,
        title: str,
        body: str,
        files: list[FileChange],
        commit_message: str,
    ) -> DocPRResult:
        """Create a branch with file changes and open a PR."""
        base_branch = base or await self._get_default_branch(owner, repo)

        # Get base branch SHA
        base_ref = await self._get(f"/repos/{owner}/{repo}/git/ref/heads/{base_branch}")
        base_sha = base_ref["object"]["sha"]

        # Create blobs
        blobs = []
        for f in files:
            blob = await self._post(
                f"/repos/{owner}/{repo}/git/blobs",
                json={
                    "content": base64.b64encode(f.content.encode("utf-8")).decode("ascii"),
                    "encoding": "base64",
                },
            )
            blobs.append({"path": f.path, "sha": blob["sha"]})

        # Get base tree
        base_commit = await self._get(f"/repos/{owner}/{repo}/git/commits/{base_sha}")

        # Create tree
        tree = await self._post(
            f"/repos/{owner}/{repo}/git/trees",
            json={
                "base_tree": base_commit["tree"]["sha"],
                "tree": [
                    {"path": b["path"], "mode": "100644", "type": "blob", "sha": b["sha"]}
                    for b in blobs
                ],
            },
        )

        # Create commit
        commit = await self._post(
            f"/repos/{owner}/{repo}/git/commits",
            json={
                "message": commit_message,
                "tree": tree["sha"],
                "parents": [base_sha],
            },
        )

        # Create branch ref
        await self._post(
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]},
        )

        # Open PR
        pr = await self._post(
            f"/repos/{owner}/{repo}/pulls",
            json={"title": title, "body": body, "head": branch, "base": base_branch},
        )

        return DocPRResult(pr_number=pr["number"], pr_url=pr["html_url"])

    async def update_doc_pr(
        self,
        owner: str,
        repo: str,
        *,
        branch: str,
        base: str | None = None,
        title: str,
        body: str,
        files: list[FileChange],
        commit_message: str,
        pr_number: int,
    ) -> DocPRResult:
        """Update an existing doc-update branch and PR."""
        base_branch = base or await self._get_default_branch(owner, repo)

        # Get base branch SHA
        base_ref = await self._get(f"/repos/{owner}/{repo}/git/ref/heads/{base_branch}")
        base_sha = base_ref["object"]["sha"]

        # Create blobs
        blobs = []
        for f in files:
            blob = await self._post(
                f"/repos/{owner}/{repo}/git/blobs",
                json={
                    "content": base64.b64encode(f.content.encode("utf-8")).decode("ascii"),
                    "encoding": "base64",
                },
            )
            blobs.append({"path": f.path, "sha": blob["sha"]})

        # Get base tree
        base_commit = await self._get(f"/repos/{owner}/{repo}/git/commits/{base_sha}")

        # Create tree
        tree = await self._post(
            f"/repos/{owner}/{repo}/git/trees",
            json={
                "base_tree": base_commit["tree"]["sha"],
                "tree": [
                    {"path": b["path"], "mode": "100644", "type": "blob", "sha": b["sha"]}
                    for b in blobs
                ],
            },
        )

        # Create commit
        commit = await self._post(
            f"/repos/{owner}/{repo}/git/commits",
            json={
                "message": commit_message,
                "tree": tree["sha"],
                "parents": [base_sha],
            },
        )

        # Force-update branch ref
        headers = await self._auth_headers()
        resp = await self._http.patch(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/refs/heads/{branch}",
            headers=headers,
            json={"sha": commit["sha"], "force": True},
        )
        resp.raise_for_status()

        # Update PR
        await self._patch(
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            json={"title": title, "body": body},
        )

        pr = await self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        return DocPRResult(pr_number=pr["number"], pr_url=pr["html_url"])

    async def find_open_doc_pr(self, owner: str, repo: str, branch: str) -> DocPRResult | None:
        """Find an open PR for a given branch."""
        headers = await self._auth_headers()
        resp = await self._http.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            headers=headers,
            params={"head": f"{owner}:{branch}", "state": "open"},
        )
        resp.raise_for_status()
        prs = resp.json()
        if prs:
            return DocPRResult(pr_number=prs[0]["number"], pr_url=prs[0]["html_url"])
        return None

    # ─── Deployments ─────────────────────────────────

    async def get_preview_deployment_url(self, owner: str, repo: str, pr_number: int) -> str | None:
        """Return the preview deployment URL for a PR, or None if not deployed."""
        env_name = f"preview-pr-{pr_number}"
        try:
            deployments = await self._get_list(
                f"/repos/{owner}/{repo}/deployments",
                environment=env_name,
                per_page="1",
            )
            if not deployments:
                return None
            statuses = await self._get_list(
                f"/repos/{owner}/{repo}/deployments/{deployments[0]['id']}/statuses",
                per_page="1",
            )
            if statuses and statuses[0].get("state") == "success":
                url = statuses[0].get("environment_url")
                if not url:
                    logger.warning(
                        "Deployment %s has success status but no environment_url",
                        deployments[0]["id"],
                    )
                return url
            return None
        except Exception:
            logger.debug("Failed to fetch preview deployment for PR #%d", pr_number, exc_info=True)
            return None

    # ─── Bot comment helpers ──────────────────────────

    BOT_MARKER = "<!-- canon-bot -->"

    async def upsert_bot_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
        """Post or update the canon bot comment on a PR/issue."""
        marked_body = f"{self.BOT_MARKER}\n{body}"

        comments = await self.list_issue_comments(owner, repo, issue_number)
        existing = next(
            (c for c in comments if c.get("body", "").find(self.BOT_MARKER) >= 0),
            None,
        )

        if existing:
            await self.update_comment(owner, repo, existing["id"], marked_body)
        else:
            await self.create_comment(owner, repo, issue_number, marked_body)
