"""User-scoped GitHub API client authenticated with OAuth token."""

from __future__ import annotations

import base64
import logging

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class UserGitHubClient:
    """Thin GitHub API wrapper using a user's OAuth access token."""

    def __init__(self, token: str) -> None:
        self.token = token
        self._http = httpx.AsyncClient(
            base_url=GITHUB_API,
            timeout=30.0,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"token {token}",
            },
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, **params: str) -> dict:
        resp = await self._http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, json: dict | None = None) -> dict:
        resp = await self._http.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    async def _put(self, path: str, json: dict | None = None) -> dict:
        resp = await self._http.put(path, json=json)
        resp.raise_for_status()
        return resp.json()

    # ─── Repo content ─────────────────────────────────

    async def get_file(
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

    async def create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        sha: str = "",
        branch: str | None = None,
    ) -> dict:
        """Create or update a file via the Contents API.

        When *sha* is empty the file is created (GitHub requires sha to be
        omitted for new files).  When *sha* is provided the file is updated.
        """
        payload: dict = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        }
        if sha:
            payload["sha"] = sha
        if branch:
            payload["branch"] = branch
        return await self._put(f"/repos/{owner}/{repo}/contents/{path}", json=payload)

    # ─── Branches ─────────────────────────────────────

    async def create_branch(self, owner: str, repo: str, branch: str, from_sha: str) -> dict:
        """Create a new branch from a given SHA."""
        return await self._post(
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": from_sha},
        )

    async def get_branch_sha(self, owner: str, repo: str, branch: str) -> str:
        """Get the latest SHA of a branch."""
        data = await self._get(f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
        return data["object"]["sha"]

    # ─── Pull Requests ────────────────────────────────

    async def create_pull_request(
        self, owner: str, repo: str, title: str, body: str, head: str, base: str
    ) -> dict:
        """Create a pull request."""
        return await self._post(
            f"/repos/{owner}/{repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
        )

    # ─── Repository ───────────────────────────────────

    async def get_repo(self, owner: str, repo: str) -> dict:
        """Get repository metadata."""
        return await self._get(f"/repos/{owner}/{repo}")

    async def list_user_repos(self, per_page: int = 100) -> list[dict]:
        """List repositories accessible to the authenticated user."""
        resp = await self._http.get(
            "/user/repos",
            params={"per_page": str(per_page), "sort": "updated", "direction": "desc"},
        )
        resp.raise_for_status()
        return resp.json()

    async def list_directory(self, owner: str, repo: str, path: str) -> list[dict]:
        """List contents of a directory. Returns empty list on error."""
        try:
            resp = await self._http.get(f"/repos/{owner}/{repo}/contents/{path}")
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else []
            logger.debug("list_directory %s/%s/%s returned %s", owner, repo, path, resp.status_code)
        except Exception:
            logger.debug("list_directory %s/%s/%s failed", owner, repo, path, exc_info=True)
        return []
