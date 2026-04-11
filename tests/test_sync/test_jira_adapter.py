"""Tests for the JiraAdapter — HTTP interactions, retry logic, and response parsing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from canon.parser.models import SectionStatus
from canon.sync.adapters.jira import (
    INITIAL_BACKOFF,
    MAX_RETRIES,
    JiraAdapter,
    JiraValidationError,
)
from canon.sync.models import CreateTicketInput, JiraConfig, UpdateTicketInput

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _api_token_config() -> JiraConfig:
    return JiraConfig(host="jira.example.com", email="a@b.com", api_token="tok123")


def _oauth_config() -> JiraConfig:
    return JiraConfig(
        auth_method="oauth",
        access_token="bearer_tok",
        cloud_id="cloud-abc",
    )


def _adapter(config: JiraConfig | None = None) -> JiraAdapter:
    return JiraAdapter(config or _api_token_config())


def _response(
    status_code: int = 200, json_data: dict | None = None, headers: dict | None = None
) -> httpx.Response:
    """Build a fake httpx.Response."""
    import json as _json

    body = _json.dumps(json_data or {}).encode()
    return httpx.Response(
        status_code=status_code,
        content=body,
        headers=headers or {},
        request=httpx.Request("GET", "https://jira.example.com/rest/api/3/fake"),
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_api_token_mode_sets_basic_auth(self) -> None:
        adapter = _adapter(_api_token_config())
        auth_header = adapter._client.headers["authorization"]
        assert auth_header.startswith("Basic ")

    def test_api_token_mode_base_url(self) -> None:
        adapter = _adapter(_api_token_config())
        assert str(adapter._client.base_url).rstrip("/") == "https://jira.example.com/rest/api/3"

    def test_oauth_mode_sets_bearer_auth(self) -> None:
        adapter = _adapter(_oauth_config())
        assert adapter._client.headers["authorization"] == "Bearer bearer_tok"

    def test_oauth_mode_base_url(self) -> None:
        adapter = _adapter(_oauth_config())
        assert (
            str(adapter._client.base_url).rstrip("/")
            == "https://api.atlassian.com/ex/jira/cloud-abc/rest/api/3"
        )

    def test_system_name(self) -> None:
        assert _adapter().system_name == "jira"

    def test_capabilities(self) -> None:
        caps = _adapter().capabilities
        assert caps.supports_custom_fields is True
        assert caps.supports_hierarchy is True
        assert caps.supports_subtasks is True
        assert caps.supports_labels is True
        assert caps.supports_issue_types is True


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------


class TestValidateConfig:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        adapter = _adapter()
        adapter._client = AsyncMock()
        adapter._client.request = AsyncMock(
            return_value=_response(200, {"key": "CAN", "name": "Canon"})
        )
        # Should not raise
        await adapter.validate_config("CAN")

    @pytest.mark.asyncio
    async def test_invalid_credentials(self) -> None:
        adapter = _adapter()
        adapter._client = AsyncMock()
        adapter._client.request = AsyncMock(return_value=_response(401))
        with pytest.raises(JiraValidationError, match="Invalid Jira credentials"):
            await adapter.validate_config("CAN")

    @pytest.mark.asyncio
    async def test_project_not_found(self) -> None:
        adapter = _adapter()
        adapter._client = AsyncMock()
        adapter._client.request = AsyncMock(return_value=_response(404))
        with pytest.raises(JiraValidationError, match="not found"):
            await adapter.validate_config("NOPE")

    @pytest.mark.asyncio
    async def test_other_http_error(self) -> None:
        adapter = _adapter()
        adapter._client = AsyncMock()
        adapter._client.request = AsyncMock(return_value=_response(403))
        with pytest.raises(JiraValidationError, match="403"):
            await adapter.validate_config("CAN")


# ---------------------------------------------------------------------------
# create_ticket
# ---------------------------------------------------------------------------


class TestCreateTicket:
    @pytest.mark.asyncio
    async def test_creates_task_and_transitions(self) -> None:
        adapter = _adapter()
        calls: list[tuple[str, str]] = []

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            calls.append((method, path))
            if method == "POST" and path == "/issue":
                return {"key": "CAN-1", "id": "10001"}
            if method == "GET" and "/transitions" in path:
                return {"transitions": [{"id": "31", "name": "To Do"}]}
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        result = await adapter.create_ticket(
            CreateTicketInput(
                project_key="CAN",
                summary="Test ticket",
                description="A description",
                status=SectionStatus(state="todo"),
            )
        )

        assert result.ticket_id == "CAN-1"
        assert "CAN-1" in result.ticket_url
        # Should have: POST /issue, GET transitions, POST transitions
        assert ("POST", "/issue") in calls
        assert any("transitions" in p for _, p in calls)

    @pytest.mark.asyncio
    async def test_skips_transition_for_backlog(self) -> None:
        """Draft status maps to Backlog — no transition needed."""
        adapter = _adapter()
        calls: list[tuple[str, str]] = []

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            calls.append((method, path))
            if method == "POST" and path == "/issue":
                return {"key": "CAN-2", "id": "10002"}
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter.create_ticket(
            CreateTicketInput(
                project_key="CAN",
                summary="Draft item",
                description="",
                status=SectionStatus(state="draft"),
            )
        )

        # No transition calls for Backlog
        assert not any("transitions" in p for _, p in calls)

    @pytest.mark.asyncio
    async def test_subtask_with_parent(self) -> None:
        adapter = _adapter()
        captured_body: dict = {}

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            if method == "POST" and path == "/issue":
                captured_body.update(json or {})
                return {"key": "CAN-3", "id": "10003"}
            if "transitions" in path:
                return {"transitions": [{"id": "31", "name": "To Do"}]}
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter.create_ticket(
            CreateTicketInput(
                project_key="CAN",
                summary="Sub-task",
                description="child",
                status=SectionStatus(state="todo"),
                parent_ticket_id="CAN-1",
            )
        )

        fields = captured_body["fields"]
        assert fields["issuetype"]["name"] == "Sub-task"
        assert fields["parent"]["key"] == "CAN-1"

    @pytest.mark.asyncio
    async def test_labels_included(self) -> None:
        adapter = _adapter()
        captured_body: dict = {}

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            if method == "POST" and path == "/issue":
                captured_body.update(json or {})
                return {"key": "CAN-4", "id": "10004"}
            if "transitions" in path:
                return {"transitions": []}
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter.create_ticket(
            CreateTicketInput(
                project_key="CAN",
                summary="Labeled",
                description="",
                status=SectionStatus(state="todo"),
                labels=["canon:sync", "backend"],
            )
        )

        assert captured_body["fields"]["labels"] == ["canon:sync", "backend"]

    @pytest.mark.asyncio
    async def test_no_description_uses_fallback(self) -> None:
        adapter = _adapter()
        captured_body: dict = {}

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            if method == "POST" and path == "/issue":
                captured_body.update(json or {})
                return {"key": "CAN-5", "id": "10005"}
            if "transitions" in path:
                return {"transitions": []}
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter.create_ticket(
            CreateTicketInput(
                project_key="CAN",
                summary="No desc",
                description="",
                status=SectionStatus(state="draft"),
            )
        )

        adf_text = captured_body["fields"]["description"]["content"][0]["content"][0]["text"]
        assert adf_text == "No description"


# ---------------------------------------------------------------------------
# update_ticket
# ---------------------------------------------------------------------------


class TestUpdateTicket:
    @pytest.mark.asyncio
    async def test_updates_summary_and_description(self) -> None:
        adapter = _adapter()
        captured: list[tuple[str, str, dict | None]] = []

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            captured.append((method, path, json))
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter.update_ticket(
            UpdateTicketInput(
                ticket_id="CAN-1",
                summary="Updated title",
                description="Updated body",
            )
        )

        assert len(captured) == 1
        method, path, body = captured[0]
        assert method == "PUT"
        assert "/issue/CAN-1" in path
        assert body["fields"]["summary"] == "Updated title"

    @pytest.mark.asyncio
    async def test_updates_status_only(self) -> None:
        adapter = _adapter()
        captured: list[tuple[str, str]] = []

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            captured.append((method, path))
            if "transitions" in path and method == "GET":
                return {"transitions": [{"id": "41", "name": "In Progress"}]}
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter.update_ticket(
            UpdateTicketInput(ticket_id="CAN-1", status=SectionStatus(state="in_progress"))
        )

        # No PUT (no fields), but GET+POST transitions
        assert not any(m == "PUT" for m, _ in captured)
        assert any("transitions" in p for _, p in captured)

    @pytest.mark.asyncio
    async def test_no_op_when_empty(self) -> None:
        adapter = _adapter()
        captured: list[tuple[str, str]] = []

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            captured.append((method, path))
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter.update_ticket(UpdateTicketInput(ticket_id="CAN-1"))

        # No fields and no status — nothing should be called
        assert len(captured) == 0


# ---------------------------------------------------------------------------
# get_ticket_status
# ---------------------------------------------------------------------------


class TestGetTicketStatus:
    @pytest.mark.asyncio
    async def test_returns_mapped_status(self) -> None:
        adapter = _adapter()

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            return {
                "fields": {
                    "status": {
                        "name": "In Progress",
                        "statusCategory": {"key": "indeterminate"},
                    }
                }
            }

        adapter._request = fake_request  # type: ignore[assignment]

        result = await adapter.get_ticket_status("CAN-10")
        assert result.ticket_id == "CAN-10"
        assert result.status == SectionStatus(state="in_progress")
        assert result.raw_status == "In Progress"

    @pytest.mark.asyncio
    async def test_done_category(self) -> None:
        adapter = _adapter()

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            return {
                "fields": {
                    "status": {
                        "name": "Done",
                        "statusCategory": {"key": "done"},
                    }
                }
            }

        adapter._request = fake_request  # type: ignore[assignment]

        result = await adapter.get_ticket_status("CAN-11")
        assert result.status == SectionStatus(state="done")

    @pytest.mark.asyncio
    async def test_new_category_maps_to_todo(self) -> None:
        adapter = _adapter()

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            return {
                "fields": {
                    "status": {
                        "name": "To Do",
                        "statusCategory": {"key": "new"},
                    }
                }
            }

        adapter._request = fake_request  # type: ignore[assignment]

        result = await adapter.get_ticket_status("CAN-12")
        assert result.status == SectionStatus(state="todo")


# ---------------------------------------------------------------------------
# link_pr
# ---------------------------------------------------------------------------


class TestLinkPr:
    @pytest.mark.asyncio
    async def test_creates_remote_link(self) -> None:
        adapter = _adapter()
        captured: list[tuple[str, str, dict | None]] = []

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            captured.append((method, path, json))
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter.link_pr("CAN-1", "https://github.com/org/repo/pull/42", "Fix auth bug")

        assert len(captured) == 1
        method, path, body = captured[0]
        assert method == "POST"
        assert "/issue/CAN-1/remotelink" in path
        assert body["object"]["url"] == "https://github.com/org/repo/pull/42"
        assert body["object"]["title"] == "Fix auth bug"


# ---------------------------------------------------------------------------
# search_tickets
# ---------------------------------------------------------------------------


class TestSearchTickets:
    @pytest.mark.asyncio
    async def test_returns_parsed_results(self) -> None:
        adapter = _adapter()
        captured_method: str | None = None
        captured_path: str | None = None
        captured_params: dict | None = None

        async def fake_request(
            method: str, path: str, json: dict | None = None, params: dict | None = None
        ) -> dict:
            nonlocal captured_method, captured_path, captured_params
            captured_method = method
            captured_path = path
            captured_params = params
            return {
                "issues": [
                    {
                        "key": "CAN-10",
                        "fields": {
                            "summary": "Auth login flow",
                            "status": {"statusCategory": {"key": "indeterminate"}},
                        },
                    },
                    {
                        "key": "CAN-11",
                        "fields": {
                            "summary": "Auth logout",
                            "status": {"statusCategory": {"key": "done"}},
                        },
                    },
                ]
            }

        adapter._request = fake_request  # type: ignore[assignment]

        results = await adapter.search_tickets("CAN", "Auth")
        assert len(results) == 2
        assert results[0].ticket_id == "CAN-10"
        assert results[0].state == "open"
        assert results[1].ticket_id == "CAN-11"
        assert results[1].state == "closed"
        assert "CAN-10" in results[0].ticket_url
        # Must use /search/jql — the old /search endpoint returns 410 Gone
        # since Atlassian retired it. JQL passed as params, not embedded in URL.
        assert captured_method == "GET"
        assert captured_path == "/search/jql"
        assert captured_params is not None
        assert "jql" in captured_params

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        adapter = _adapter()

        async def fake_request(
            method: str, path: str, json: dict | None = None, params: dict | None = None
        ) -> dict:
            return {"issues": []}

        adapter._request = fake_request  # type: ignore[assignment]

        results = await adapter.search_tickets("CAN", "Nonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_sanitizes_quotes_in_title_pattern(self) -> None:
        adapter = _adapter()
        captured_params: dict | None = None

        async def fake_request(
            method: str, path: str, json: dict | None = None, params: dict | None = None
        ) -> dict:
            nonlocal captured_params
            captured_params = params
            return {"issues": []}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter.search_tickets("CAN", 'foo" OR project = "OTHER')
        assert captured_params is not None
        jql = captured_params["jql"]
        # Quotes stripped — the injected payload is trapped inside the summary ~ "..." clause
        # rather than breaking out as a separate JQL clause
        assert '" OR project' not in jql


# ---------------------------------------------------------------------------
# _transition_to
# ---------------------------------------------------------------------------


class TestTransitionTo:
    @pytest.mark.asyncio
    async def test_finds_and_executes_transition(self) -> None:
        adapter = _adapter()
        captured: list[tuple[str, str, dict | None]] = []

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            captured.append((method, path, json))
            if method == "GET":
                return {
                    "transitions": [
                        {"id": "11", "name": "To Do"},
                        {"id": "21", "name": "In Progress"},
                        {"id": "31", "name": "Done"},
                    ]
                }
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter._transition_to("CAN-1", "In Progress")

        # GET transitions + POST transition
        assert len(captured) == 2
        post_call = captured[1]
        assert post_call[2]["transition"]["id"] == "21"

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self) -> None:
        adapter = _adapter()
        posted_id: str | None = None

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            nonlocal posted_id
            if method == "GET":
                return {"transitions": [{"id": "31", "name": "Done"}]}
            if method == "POST":
                posted_id = json["transition"]["id"]
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        await adapter._transition_to("CAN-1", "done")
        assert posted_id == "31"

    @pytest.mark.asyncio
    async def test_no_matching_transition_logs_warning(self) -> None:
        adapter = _adapter()
        post_called = False

        async def fake_request(method: str, path: str, json: dict | None = None) -> dict:
            nonlocal post_called
            if method == "GET":
                return {"transitions": [{"id": "11", "name": "To Do"}]}
            if method == "POST":
                post_called = True
            return {}

        adapter._request = fake_request  # type: ignore[assignment]

        # "Won't Do" not available — should warn and skip, not raise
        await adapter._transition_to("CAN-1", "Won't Do")
        assert post_called is False


# ---------------------------------------------------------------------------
# _request — retry logic
# ---------------------------------------------------------------------------


class TestRequestRetry:
    @pytest.mark.asyncio
    async def test_retries_on_429(self) -> None:
        adapter = _adapter()
        attempt_count = 0

        async def mock_request(method: str, url: str, **kwargs) -> httpx.Response:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                return _response(429, headers={"Retry-After": "0"})
            return _response(200, {"ok": True})

        adapter._client.request = mock_request  # type: ignore[assignment]

        with patch("canon.sync.adapters.jira.asyncio.sleep", new_callable=AsyncMock):
            result = await adapter._request("GET", "/test")

        assert result == {"ok": True}
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_502(self) -> None:
        adapter = _adapter()
        attempt_count = 0

        async def mock_request(method: str, url: str, **kwargs) -> httpx.Response:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                return _response(502)
            return _response(200, {"ok": True})

        adapter._client.request = mock_request  # type: ignore[assignment]

        with patch("canon.sync.adapters.jira.asyncio.sleep", new_callable=AsyncMock):
            result = await adapter._request("GET", "/test")

        assert result == {"ok": True}
        assert attempt_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self) -> None:
        adapter = _adapter()

        async def mock_request(method: str, url: str, **kwargs) -> httpx.Response:
            return _response(503)

        adapter._client.request = mock_request  # type: ignore[assignment]

        with (
            patch("canon.sync.adapters.jira.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(httpx.HTTPStatusError) as exc_info,
        ):
            await adapter._request("GET", "/test")

        assert exc_info.value.response.status_code == 503

    @pytest.mark.asyncio
    async def test_non_retryable_status_raises_immediately(self) -> None:
        adapter = _adapter()
        attempt_count = 0

        async def mock_request(method: str, url: str, **kwargs) -> httpx.Response:
            nonlocal attempt_count
            attempt_count += 1
            return _response(400)

        adapter._client.request = mock_request  # type: ignore[assignment]

        with pytest.raises(httpx.HTTPStatusError):
            await adapter._request("GET", "/bad")

        assert attempt_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_respects_retry_after_header(self) -> None:
        adapter = _adapter()
        sleep_values: list[float] = []

        async def mock_request(method: str, url: str, **kwargs) -> httpx.Response:
            if len(sleep_values) == 0:
                return _response(429, headers={"Retry-After": "5"})
            return _response(200, {"ok": True})

        adapter._client.request = mock_request  # type: ignore[assignment]

        async def capture_sleep(seconds: float) -> None:
            sleep_values.append(seconds)

        with patch("canon.sync.adapters.jira.asyncio.sleep", side_effect=capture_sleep):
            await adapter._request("GET", "/rate-limited")

        assert sleep_values[0] == 5.0

    @pytest.mark.asyncio
    async def test_exponential_backoff_without_retry_after(self) -> None:
        adapter = _adapter()
        sleep_values: list[float] = []
        attempt_count = 0

        async def mock_request(method: str, url: str, **kwargs) -> httpx.Response:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count <= MAX_RETRIES:
                return _response(500)
            return _response(200, {"ok": True})

        adapter._client.request = mock_request  # type: ignore[assignment]

        async def capture_sleep(seconds: float) -> None:
            sleep_values.append(seconds)

        with patch("canon.sync.adapters.jira.asyncio.sleep", side_effect=capture_sleep):
            await adapter._request("GET", "/flaky")

        # Backoff doubles: 1.0, 2.0, 4.0, ...
        assert sleep_values[0] == INITIAL_BACKOFF
        assert sleep_values[1] == INITIAL_BACKOFF * 2

    @pytest.mark.asyncio
    async def test_retries_on_connect_error(self) -> None:
        adapter = _adapter()
        attempt_count = 0

        async def mock_request(method: str, url: str, **kwargs) -> httpx.Response:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise httpx.ConnectError("Connection refused")
            return _response(200, {"ok": True})

        adapter._client.request = mock_request  # type: ignore[assignment]

        with patch("canon.sync.adapters.jira.asyncio.sleep", new_callable=AsyncMock):
            result = await adapter._request("GET", "/down")

        assert result == {"ok": True}
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_connect_error_raises_after_max_retries(self) -> None:
        adapter = _adapter()

        async def mock_request(method: str, url: str, **kwargs) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        adapter._client.request = mock_request  # type: ignore[assignment]

        with (
            patch("canon.sync.adapters.jira.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(httpx.ConnectError),
        ):
            await adapter._request("GET", "/down")

    @pytest.mark.asyncio
    async def test_204_returns_empty_dict(self) -> None:
        adapter = _adapter()

        async def mock_request(method: str, url: str, **kwargs) -> httpx.Response:
            return _response(204)

        adapter._client.request = mock_request  # type: ignore[assignment]

        result = await adapter._request("POST", "/transition")
        assert result == {}
