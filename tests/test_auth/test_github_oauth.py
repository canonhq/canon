"""Tests for GitHub OAuth client and routes."""

from __future__ import annotations

import pytest

from canon.auth.github_oauth import GitHubOAuthClient


class TestGitHubOAuthClient:
    def test_authorize_url_contains_client_id(self):
        client = GitHubOAuthClient(client_id="test-id", client_secret="test-secret")
        url = client.authorize_url("http://localhost/callback", state="abc123")
        assert "client_id=test-id" in url
        assert "state=abc123" in url
        assert "scope=repo" in url
        assert "redirect_uri=http" in url
        assert "github.com/login/oauth/authorize" in url

    def test_authorize_url_requires_state(self):
        client = GitHubOAuthClient(client_id="test-id", client_secret="test-secret")
        with pytest.raises(TypeError):
            client.authorize_url("http://localhost/callback")

    @pytest.mark.asyncio
    async def test_exchange_code(self, respx_mock):
        import respx

        respx_mock.post("https://github.com/login/oauth/access_token").mock(
            return_value=respx.MockResponse(
                200, json={"access_token": "gho_abc", "token_type": "bearer", "scope": "repo"}
            )
        )

        client = GitHubOAuthClient(client_id="test-id", client_secret="test-secret")
        result = await client.exchange_code("test-code", "http://localhost/callback")
        assert result["access_token"] == "gho_abc"

    @pytest.mark.asyncio
    async def test_get_user(self, respx_mock):
        import respx

        respx_mock.get("https://api.github.com/user").mock(
            return_value=respx.MockResponse(
                200,
                json={
                    "login": "testuser",
                    "name": "Test User",
                    "email": "test@example.com",
                    "avatar_url": "https://example.com/avatar.png",
                },
            )
        )

        client = GitHubOAuthClient(client_id="test-id", client_secret="test-secret")
        user = await client.get_user("gho_abc")
        assert user["login"] == "testuser"
        assert user["email"] == "test@example.com"
