"""GitHub OAuth2 client for user-level authentication."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


class GitHubOAuthClient:
    """Lightweight GitHub OAuth2 flow using httpx."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        """Build the GitHub OAuth authorize redirect URL.

        Args:
            redirect_uri: The callback URL after authorization.
            state: CSRF state token. Caller must generate and store this for validation.
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": "repo",
            "state": state,
        }
        return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """Exchange an authorization code for an access token.

        Returns the parsed token response dict (contains ``access_token``, ``token_type``, ``scope``).
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user(self, token: str) -> dict:
        """Fetch the authenticated user's profile."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            resp.raise_for_status()
            return resp.json()
