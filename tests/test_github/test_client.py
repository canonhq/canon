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


def _mock_response(json_data=None, status_code=200, headers=None):
    """Create a mock httpx.Response with rate-limit-safe defaults."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = ""
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _setup_client_mock(client, *, request_return=None, request_side_effect=None):
    """Wire up a mock _http with request method and token auth."""
    client._get_installation_token = AsyncMock(return_value="fake-token")
    client._http = AsyncMock()
    if request_side_effect:
        client._http.request = AsyncMock(side_effect=request_side_effect)
    else:
        client._http.request = AsyncMock(return_value=request_return)


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

        mock_resp = _mock_response({"repositories": repos, "total_count": 3})
        _setup_client_mock(client, request_return=mock_resp)

        result = await client.list_installation_repos()
        assert len(result) == 3
        assert client._http.request.await_count == 1

    async def test_multiple_pages(self):
        client = _make_client()

        page1_repos = [{"name": f"repo{i}"} for i in range(100)]
        page2_repos = [{"name": f"repo{i}"} for i in range(100, 150)]

        call_count = 0

        async def mock_request(method, path, headers=None, params=None, json=None):
            nonlocal call_count
            call_count += 1
            if params and params.get("page") == "2":
                return _mock_response({"repositories": page2_repos, "total_count": 150})
            return _mock_response({"repositories": page1_repos, "total_count": 150})

        _setup_client_mock(client, request_side_effect=mock_request)

        result = await client.list_installation_repos()
        assert len(result) == 150
        assert call_count == 2

    async def test_empty_response(self):
        client = _make_client()

        mock_resp = _mock_response({"repositories": [], "total_count": 0})
        _setup_client_mock(client, request_return=mock_resp)

        result = await client.list_installation_repos()
        assert len(result) == 0


class TestIssueMethods:
    async def test_create_issue(self):
        client = _make_client()
        mock_resp = _mock_response({"number": 42, "title": "Test"})
        _setup_client_mock(client, request_return=mock_resp)

        result = await client.create_issue("acme", "api", "Test", "body", labels=["bug"])
        assert result["number"] == 42
        call_kwargs = client._http.request.call_args
        payload = call_kwargs[1]["json"]
        assert payload["title"] == "Test"
        assert payload["labels"] == ["bug"]

    async def test_list_issues_with_filters(self):
        client = _make_client()
        mock_resp = _mock_response([{"number": 1}, {"number": 2}])
        _setup_client_mock(client, request_return=mock_resp)

        result = await client.list_issues("acme", "api", labels="bug", state="open")
        assert len(result) == 2
        call_kwargs = client._http.request.call_args
        assert call_kwargs[1]["params"]["labels"] == "bug"
        assert call_kwargs[1]["params"]["state"] == "open"

    async def test_update_issue(self):
        client = _make_client()
        mock_resp = _mock_response({"number": 42, "state": "closed"})
        _setup_client_mock(client, request_return=mock_resp)

        result = await client.update_issue("acme", "api", 42, state="closed", body="updated")
        assert result["state"] == "closed"
        call_kwargs = client._http.request.call_args
        payload = call_kwargs[1]["json"]
        assert payload["state"] == "closed"
        assert payload["body"] == "updated"
        assert "title" not in payload  # None fields should be excluded

    async def test_ensure_label_creates_new(self):
        client = _make_client()
        mock_resp = _mock_response({"name": "canon-onboarding"})
        _setup_client_mock(client, request_return=mock_resp)

        await client.ensure_label("acme", "api", "canon-onboarding")
        client._http.request.assert_awaited_once()

    async def test_ensure_label_ignores_422_duplicate(self):
        import httpx

        client = _make_client()

        mock_resp = _mock_response({"name": "canon-onboarding"}, status_code=422)
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("422", request=MagicMock(), response=mock_resp)
        )
        _setup_client_mock(client, request_return=mock_resp)

        # Should not raise
        await client.ensure_label("acme", "api", "canon-onboarding")


class TestGetPreviewDeploymentUrl:
    async def test_returns_url_when_active_deployment_exists(self):
        client = _make_client()

        deployments_resp = _mock_response([{"id": 100}])
        statuses_resp = _mock_response(
            [{"state": "success", "environment_url": "https://preview-pr-7.example.com"}]
        )

        call_count = 0

        async def mock_request(method, path, headers=None, params=None, json=None):
            nonlocal call_count
            call_count += 1
            if "statuses" in path:
                return statuses_resp
            return deployments_resp

        _setup_client_mock(client, request_side_effect=mock_request)

        result = await client.get_preview_deployment_url("acme", "api", 7)
        assert result == "https://preview-pr-7.example.com"
        assert call_count == 2

    async def test_returns_none_when_no_deployment(self):
        client = _make_client()
        empty_resp = _mock_response([])
        _setup_client_mock(client, request_return=empty_resp)

        result = await client.get_preview_deployment_url("acme", "api", 7)
        assert result is None

    async def test_returns_none_when_deployment_not_success(self):
        client = _make_client()

        deployments_resp = _mock_response([{"id": 100}])
        statuses_resp = _mock_response([{"state": "in_progress"}])

        async def mock_request(method, path, headers=None, params=None, json=None):
            if "statuses" in path:
                return statuses_resp
            return deployments_resp

        _setup_client_mock(client, request_side_effect=mock_request)

        result = await client.get_preview_deployment_url("acme", "api", 7)
        assert result is None

    async def test_returns_none_on_api_error(self):
        client = _make_client()
        mock_resp = _mock_response(status_code=200)
        mock_resp.raise_for_status = MagicMock(side_effect=Exception("API error"))
        _setup_client_mock(client, request_return=mock_resp)

        result = await client.get_preview_deployment_url("acme", "api", 7)
        assert result is None
