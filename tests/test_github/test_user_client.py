"""Tests for UserGitHubClient."""

from __future__ import annotations

import base64

import pytest
from httpx import Response

from canon.github.user_client import UserGitHubClient


@pytest.fixture
def client():
    return UserGitHubClient(token="gho_test123")


class TestUserGitHubClient:
    @pytest.mark.asyncio
    async def test_get_file(self, client, respx_mock):
        content_b64 = base64.b64encode(b"# Hello").decode()
        respx_mock.get("https://api.github.com/repos/acme/repo/contents/docs/specs/test.md").mock(
            return_value=Response(200, json={"content": content_b64, "sha": "abc123"})
        )

        content, sha = await client.get_file("acme", "repo", "docs/specs/test.md")
        assert content == "# Hello"
        assert sha == "abc123"

    @pytest.mark.asyncio
    async def test_get_file_with_ref(self, client, respx_mock):
        content_b64 = base64.b64encode(b"content").decode()
        respx_mock.get("https://api.github.com/repos/acme/repo/contents/test.md").mock(
            return_value=Response(200, json={"content": content_b64, "sha": "def456"})
        )

        content, _sha = await client.get_file("acme", "repo", "test.md", ref="feature")
        assert content == "content"

    @pytest.mark.asyncio
    async def test_create_or_update_file(self, client, respx_mock):
        respx_mock.put("https://api.github.com/repos/acme/repo/contents/docs/specs/test.md").mock(
            return_value=Response(200, json={"content": {"sha": "new_sha"}})
        )

        result = await client.create_or_update_file(
            "acme", "repo", "docs/specs/test.md", "new content", "update spec", "old_sha"
        )
        assert result["content"]["sha"] == "new_sha"

    @pytest.mark.asyncio
    async def test_create_branch(self, client, respx_mock):
        respx_mock.post("https://api.github.com/repos/acme/repo/git/refs").mock(
            return_value=Response(201, json={"ref": "refs/heads/test-branch"})
        )

        result = await client.create_branch("acme", "repo", "test-branch", "sha123")
        assert result["ref"] == "refs/heads/test-branch"

    @pytest.mark.asyncio
    async def test_get_branch_sha(self, client, respx_mock):
        respx_mock.get("https://api.github.com/repos/acme/repo/git/ref/heads/main").mock(
            return_value=Response(200, json={"object": {"sha": "head_sha"}})
        )

        sha = await client.get_branch_sha("acme", "repo", "main")
        assert sha == "head_sha"

    @pytest.mark.asyncio
    async def test_create_pull_request(self, client, respx_mock):
        respx_mock.post("https://api.github.com/repos/acme/repo/pulls").mock(
            return_value=Response(
                201,
                json={
                    "number": 42,
                    "html_url": "https://github.com/acme/repo/pull/42",
                },
            )
        )

        result = await client.create_pull_request(
            "acme", "repo", "Update spec", "Body", "feature-branch", "main"
        )
        assert result["number"] == 42

    @pytest.mark.asyncio
    async def test_get_repo(self, client, respx_mock):
        respx_mock.get("https://api.github.com/repos/acme/repo").mock(
            return_value=Response(
                200,
                json={"full_name": "acme/repo", "default_branch": "main"},
            )
        )

        result = await client.get_repo("acme", "repo")
        assert result["default_branch"] == "main"

    @pytest.mark.asyncio
    async def test_list_user_repos(self, client, respx_mock):
        respx_mock.get("https://api.github.com/user/repos").mock(
            return_value=Response(
                200,
                json=[
                    {"full_name": "acme/repo1"},
                    {"full_name": "acme/repo2"},
                ],
            )
        )

        repos = await client.list_user_repos()
        assert len(repos) == 2
        assert repos[0]["full_name"] == "acme/repo1"


class TestListDirectory:
    @pytest.mark.asyncio
    async def test_list_directory_success(self, client, respx_mock):
        """Returns list of items from a directory."""
        respx_mock.get("https://api.github.com/repos/acme/repo/contents/docs/specs").mock(
            return_value=Response(
                200,
                json=[
                    {"name": "auth.md", "type": "file"},
                    {"name": "payments.md", "type": "file"},
                ],
            )
        )

        items = await client.list_directory("acme", "repo", "docs/specs")
        assert len(items) == 2
        assert items[0]["name"] == "auth.md"

    @pytest.mark.asyncio
    async def test_list_directory_empty(self, client, respx_mock):
        """Returns empty list when directory is empty."""
        respx_mock.get("https://api.github.com/repos/acme/repo/contents/docs/specs").mock(
            return_value=Response(200, json=[])
        )

        items = await client.list_directory("acme", "repo", "docs/specs")
        assert items == []

    @pytest.mark.asyncio
    async def test_list_directory_404_returns_empty(self, client, respx_mock):
        """Returns empty list when directory doesn't exist (404)."""
        respx_mock.get("https://api.github.com/repos/acme/repo/contents/nonexistent").mock(
            return_value=Response(404, json={"message": "Not Found"})
        )

        items = await client.list_directory("acme", "repo", "nonexistent")
        assert items == []

    @pytest.mark.asyncio
    async def test_list_directory_non_list_response(self, client, respx_mock):
        """Returns empty list when API returns a file instead of directory listing."""
        content_b64 = base64.b64encode(b"# file content").decode()
        respx_mock.get("https://api.github.com/repos/acme/repo/contents/README.md").mock(
            return_value=Response(200, json={"content": content_b64, "sha": "abc"})
        )

        items = await client.list_directory("acme", "repo", "README.md")
        assert items == []

    @pytest.mark.asyncio
    async def test_list_directory_network_error_returns_empty(self, client, respx_mock):
        """Returns empty list on network/connection error."""
        respx_mock.get("https://api.github.com/repos/acme/repo/contents/docs").mock(
            side_effect=Exception("connection refused")
        )

        items = await client.list_directory("acme", "repo", "docs")
        assert items == []


class TestCreateOrUpdateFileSHA:
    """Tests for SHA handling in create_or_update_file."""

    @pytest.mark.asyncio
    async def test_new_file_omits_sha(self, client, respx_mock):
        """When sha is empty, it should be omitted from the payload (new file creation)."""
        route = respx_mock.put("https://api.github.com/repos/acme/repo/contents/docs/new.md").mock(
            return_value=Response(201, json={"content": {"sha": "created_sha"}})
        )

        await client.create_or_update_file("acme", "repo", "docs/new.md", "# New", "create file")

        request_body = route.calls[0].request
        import json

        payload = json.loads(request_body.content)
        assert "sha" not in payload
        assert payload["message"] == "create file"
        assert "content" in payload

    @pytest.mark.asyncio
    async def test_existing_file_includes_sha(self, client, respx_mock):
        """When sha is provided, it should be included in the payload (update)."""
        route = respx_mock.put(
            "https://api.github.com/repos/acme/repo/contents/docs/existing.md"
        ).mock(return_value=Response(200, json={"content": {"sha": "updated_sha"}}))

        await client.create_or_update_file(
            "acme", "repo", "docs/existing.md", "# Updated", "update file", "old_sha_123"
        )

        import json

        payload = json.loads(route.calls[0].request.content)
        assert payload["sha"] == "old_sha_123"

    @pytest.mark.asyncio
    async def test_branch_parameter_included(self, client, respx_mock):
        """When branch is specified, it should be in the payload."""
        route = respx_mock.put("https://api.github.com/repos/acme/repo/contents/docs/spec.md").mock(
            return_value=Response(200, json={"content": {"sha": "branch_sha"}})
        )

        await client.create_or_update_file(
            "acme", "repo", "docs/spec.md", "content", "msg", "sha1", branch="feature-branch"
        )

        import json

        payload = json.loads(route.calls[0].request.content)
        assert payload["branch"] == "feature-branch"

    @pytest.mark.asyncio
    async def test_branch_omitted_when_none(self, client, respx_mock):
        """When branch is None, it should not appear in the payload."""
        route = respx_mock.put("https://api.github.com/repos/acme/repo/contents/docs/spec.md").mock(
            return_value=Response(200, json={"content": {"sha": "sha2"}})
        )

        await client.create_or_update_file("acme", "repo", "docs/spec.md", "content", "msg", "sha1")

        import json

        payload = json.loads(route.calls[0].request.content)
        assert "branch" not in payload
