"""Tests for GitHubClient pagination and factory methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from canon.github.client import GitHubClient


def _make_client(**kwargs) -> GitHubClient:
    """Create a GitHubClient with test credentials."""
    defaults = {
        "app_id": "12345",
        "private_key": "fake-key",
        "installation_id": "67890",
    }
    defaults.update(kwargs)
    return GitHubClient(**defaults)


class TestForInstallation:
    def test_creates_new_client_with_same_credentials(self):
        client = _make_client()
        new_client = client.for_installation("99999")
        assert new_client.app_id == client.app_id
        assert new_client.private_key == client.private_key
        assert new_client.installation_id == "99999"
        assert new_client is not client

    def test_original_client_unchanged(self):
        client = _make_client()
        client.for_installation("99999")
        assert client.installation_id == "67890"


class TestListInstallationReposPagination:
    async def test_single_page(self):
        client = _make_client()
        repos = [{"name": f"repo{i}"} for i in range(3)]

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"repositories": repos, "total_count": 3}
        mock_resp.raise_for_status = MagicMock()

        client._get_installation_token = AsyncMock(return_value="fake-token")
        client._http = AsyncMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client.list_installation_repos()
        assert len(result) == 3
        assert client._http.get.await_count == 1

    async def test_multiple_pages(self):
        client = _make_client()

        page1_repos = [{"name": f"repo{i}"} for i in range(100)]
        page2_repos = [{"name": f"repo{i}"} for i in range(100, 150)]

        call_count = 0

        async def mock_get(path, headers=None, params=None):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if params and params.get("page") == "2":
                resp.json.return_value = {"repositories": page2_repos, "total_count": 150}
            else:
                resp.json.return_value = {"repositories": page1_repos, "total_count": 150}
            return resp

        client._get_installation_token = AsyncMock(return_value="fake-token")
        client._http = AsyncMock()
        client._http.get = mock_get

        result = await client.list_installation_repos()
        assert len(result) == 150
        assert call_count == 2

    async def test_empty_response(self):
        client = _make_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"repositories": [], "total_count": 0}
        mock_resp.raise_for_status = MagicMock()

        client._get_installation_token = AsyncMock(return_value="fake-token")
        client._http = AsyncMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client.list_installation_repos()
        assert len(result) == 0


class TestIssueMethods:
    async def test_create_issue(self):
        client = _make_client()
        client._get_installation_token = AsyncMock(return_value="fake-token")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"number": 42, "title": "Test"}
        mock_resp.raise_for_status = MagicMock()
        client._http = AsyncMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        result = await client.create_issue("acme", "api", "Test", "body", labels=["bug"])
        assert result["number"] == 42
        call_kwargs = client._http.post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["title"] == "Test"
        assert payload["labels"] == ["bug"]

    async def test_list_issues_with_filters(self):
        client = _make_client()
        client._get_installation_token = AsyncMock(return_value="fake-token")

        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"number": 1}, {"number": 2}]
        mock_resp.raise_for_status = MagicMock()
        client._http = AsyncMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client.list_issues("acme", "api", labels="bug", state="open")
        assert len(result) == 2
        call_kwargs = client._http.get.call_args
        assert call_kwargs[1]["params"]["labels"] == "bug"
        assert call_kwargs[1]["params"]["state"] == "open"

    async def test_update_issue(self):
        client = _make_client()
        client._get_installation_token = AsyncMock(return_value="fake-token")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"number": 42, "state": "closed"}
        mock_resp.raise_for_status = MagicMock()
        client._http = AsyncMock()
        client._http.patch = AsyncMock(return_value=mock_resp)

        result = await client.update_issue("acme", "api", 42, state="closed", body="updated")
        assert result["state"] == "closed"
        call_kwargs = client._http.patch.call_args
        payload = call_kwargs[1]["json"]
        assert payload["state"] == "closed"
        assert payload["body"] == "updated"
        assert "title" not in payload  # None fields should be excluded

    async def test_ensure_label_creates_new(self):
        client = _make_client()
        client._get_installation_token = AsyncMock(return_value="fake-token")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"name": "canon-onboarding"}
        mock_resp.raise_for_status = MagicMock()
        client._http = AsyncMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        await client.ensure_label("acme", "api", "canon-onboarding")
        client._http.post.assert_awaited_once()

    async def test_ensure_label_ignores_422_duplicate(self):
        import httpx

        client = _make_client()
        client._get_installation_token = AsyncMock(return_value="fake-token")

        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("422", request=MagicMock(), response=mock_resp)
        )
        mock_resp.json.return_value = {"name": "canon-onboarding"}
        client._http = AsyncMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        # Should not raise
        await client.ensure_label("acme", "api", "canon-onboarding")


class TestGetPreviewDeploymentUrl:
    async def test_returns_url_when_active_deployment_exists(self):
        client = _make_client()
        client._get_installation_token = AsyncMock(return_value="fake-token")

        deployments_resp = MagicMock()
        deployments_resp.json.return_value = [{"id": 100}]
        deployments_resp.raise_for_status = MagicMock()

        statuses_resp = MagicMock()
        statuses_resp.json.return_value = [
            {"state": "success", "environment_url": "https://preview-pr-7.example.com"}
        ]
        statuses_resp.raise_for_status = MagicMock()

        call_count = 0

        async def mock_get(path, headers=None, params=None):
            nonlocal call_count
            call_count += 1
            if "statuses" in path:
                return statuses_resp
            return deployments_resp

        client._http = AsyncMock()
        client._http.get = mock_get

        result = await client.get_preview_deployment_url("acme", "api", 7)
        assert result == "https://preview-pr-7.example.com"
        assert call_count == 2

    async def test_returns_none_when_no_deployment(self):
        client = _make_client()
        client._get_installation_token = AsyncMock(return_value="fake-token")

        empty_resp = MagicMock()
        empty_resp.json.return_value = []
        empty_resp.raise_for_status = MagicMock()

        client._http = AsyncMock()
        client._http.get = AsyncMock(return_value=empty_resp)

        result = await client.get_preview_deployment_url("acme", "api", 7)
        assert result is None

    async def test_returns_none_when_deployment_not_success(self):
        client = _make_client()
        client._get_installation_token = AsyncMock(return_value="fake-token")

        deployments_resp = MagicMock()
        deployments_resp.json.return_value = [{"id": 100}]
        deployments_resp.raise_for_status = MagicMock()

        statuses_resp = MagicMock()
        statuses_resp.json.return_value = [{"state": "in_progress"}]
        statuses_resp.raise_for_status = MagicMock()

        async def mock_get(path, headers=None, params=None):
            if "statuses" in path:
                return statuses_resp
            return deployments_resp

        client._http = AsyncMock()
        client._http.get = mock_get

        result = await client.get_preview_deployment_url("acme", "api", 7)
        assert result is None

    async def test_returns_none_on_api_error(self):
        client = _make_client()
        client._get_installation_token = AsyncMock(return_value="fake-token")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(side_effect=Exception("API error"))

        client._http = AsyncMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client.get_preview_deployment_url("acme", "api", 7)
        assert result is None
