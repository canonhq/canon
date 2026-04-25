"""Tests for the LinearAdapter — GraphQL interactions, error handling, and response parsing."""

from __future__ import annotations

import json as _json
from typing import Any

import httpx
import pytest

from canon.parser.models import SectionStatus
from canon.sync.adapters.linear import LINEAR_API, LinearAdapter
from canon.sync.models import (
    CreateTicketInput,
    LinearConfig,
    UpdateTicketInput,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _api_key_config() -> LinearConfig:
    return LinearConfig(api_key="lin_api_key_123")


def _oauth_config() -> LinearConfig:
    return LinearConfig(access_token="lin_oauth_tok")


def _adapter(config: LinearConfig | None = None) -> LinearAdapter:
    return LinearAdapter(config or _api_key_config())


def _gql_response(data: dict[str, Any]) -> httpx.Response:
    """Build a fake httpx.Response wrapping a GraphQL data payload."""
    body = _json.dumps({"data": data}).encode()
    return httpx.Response(
        status_code=200,
        content=body,
        request=httpx.Request("POST", LINEAR_API),
    )


def _gql_error_response(message: str, status_code: int = 200) -> httpx.Response:
    """Build a GraphQL response containing an error."""
    body = _json.dumps({"errors": [{"message": message}]}).encode()
    return httpx.Response(
        status_code=status_code,
        content=body,
        request=httpx.Request("POST", LINEAR_API),
    )


def _http_error_response(status_code: int, text: str = "error") -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=text.encode(),
        request=httpx.Request("POST", LINEAR_API),
    )


# Shared mock data
TEAM_NODES = [
    {"id": "team-uuid-1", "key": "ENG"},
    {"id": "team-uuid-2", "key": "DESIGN"},
]

WORKFLOW_STATES = [
    {"id": "state-backlog", "name": "Backlog", "team": {"id": "team-uuid-1"}},
    {"id": "state-todo", "name": "Todo", "team": {"id": "team-uuid-1"}},
    {"id": "state-inprog", "name": "In Progress", "team": {"id": "team-uuid-1"}},
    {"id": "state-done", "name": "Done", "team": {"id": "team-uuid-1"}},
    {"id": "state-canceled", "name": "Canceled", "team": {"id": "team-uuid-1"}},
]

LABEL_NODES = [
    {"id": "lbl-1", "name": "backend", "team": {"id": "team-uuid-1"}},
    {"id": "lbl-2", "name": "frontend", "team": {"id": "team-uuid-1"}},
    {"id": "lbl-3", "name": "bug", "team": None},  # workspace-level label
    {"id": "lbl-4", "name": "backend", "team": {"id": "team-uuid-2"}},  # different team
]


def _filtered_workflow_states(variables: dict[str, Any]) -> dict[str, Any]:
    """Return workflowStates nodes filtered by the 'name' variable, mimicking the
    Linear API's server-side filter."""
    name = variables.get("name", "")
    filtered = [s for s in WORKFLOW_STATES if s["name"] == name]
    return {"workflowStates": {"nodes": filtered}}


def _make_gql_mock(responses: dict[str, Any]):
    """Return an async function that dispatches based on query keywords.

    ``responses`` maps a keyword (found in the query string) to the GraphQL
    data dict that should be returned.
    """

    async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
        body = kwargs.get("json", {})
        query = body.get("query", "")
        for keyword, data in responses.items():
            if keyword in query:
                return _gql_response(data)
        raise AssertionError(f"Unexpected query: {query}")

    return mock_post


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_api_key_sets_plain_token(self) -> None:
        adapter = _adapter(_api_key_config())
        assert adapter._client.headers["authorization"] == "lin_api_key_123"

    def test_oauth_sets_bearer_token(self) -> None:
        adapter = _adapter(_oauth_config())
        assert adapter._client.headers["authorization"] == "Bearer lin_oauth_tok"

    def test_content_type_header(self) -> None:
        adapter = _adapter()
        assert adapter._client.headers["content-type"] == "application/json"

    def test_system_name(self) -> None:
        assert _adapter().system_name == "linear"

    def test_capabilities(self) -> None:
        caps = _adapter().capabilities
        assert caps.supports_labels is True
        assert caps.supports_hierarchy is True
        assert caps.supports_subtasks is True
        assert caps.supports_custom_fields is False
        assert caps.supports_issue_types is False

    def test_effective_token_prefers_api_key(self) -> None:
        config = LinearConfig(api_key="key", access_token="tok")
        assert config.effective_token == "key"

    def test_effective_token_falls_back_to_access_token(self) -> None:
        config = LinearConfig(access_token="tok")
        assert config.effective_token == "tok"


# ---------------------------------------------------------------------------
# _gql — low-level GraphQL helper
# ---------------------------------------------------------------------------


class TestGql:
    @pytest.mark.asyncio
    async def test_returns_data_on_success(self) -> None:
        adapter = _adapter()
        adapter._client.post = _make_gql_mock({"teams": {"teams": {"nodes": TEAM_NODES}}})  # type: ignore[assignment]
        result = await adapter._gql("{ teams { nodes { id key } } }")
        assert result["teams"]["nodes"] == TEAM_NODES

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _http_error_response(500, "Internal Server Error")

        adapter._client.post = mock_post  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="Linear API 500"):
            await adapter._gql("{ viewer { id } }")

    @pytest.mark.asyncio
    async def test_raises_on_graphql_error(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_error_response("You do not have permission")

        adapter._client.post = mock_post  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="You do not have permission"):
            await adapter._gql("{ viewer { id } }")

    @pytest.mark.asyncio
    async def test_passes_variables(self) -> None:
        adapter = _adapter()
        captured: dict[str, Any] = {}

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            captured.update(kwargs.get("json", {}))
            return _gql_response({"result": True})

        adapter._client.post = mock_post  # type: ignore[assignment]
        await adapter._gql("query($x: String!) { foo(x: $x) }", {"x": "bar"})
        assert captured["variables"] == {"x": "bar"}

    @pytest.mark.asyncio
    async def test_omits_variables_when_none(self) -> None:
        adapter = _adapter()
        captured: dict[str, Any] = {}

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            captured.update(kwargs.get("json", {}))
            return _gql_response({"result": True})

        adapter._client.post = mock_post  # type: ignore[assignment]
        await adapter._gql("{ viewer { id } }")
        assert "variables" not in captured


# ---------------------------------------------------------------------------
# _resolve_team_id
# ---------------------------------------------------------------------------


class TestResolveTeamId:
    @pytest.mark.asyncio
    async def test_finds_team_by_key(self) -> None:
        adapter = _adapter()
        adapter._client.post = _make_gql_mock({"teams": {"teams": {"nodes": TEAM_NODES}}})  # type: ignore[assignment]
        team_id = await adapter._resolve_team_id("ENG")
        assert team_id == "team-uuid-1"

    @pytest.mark.asyncio
    async def test_raises_for_unknown_team(self) -> None:
        adapter = _adapter()
        adapter._client.post = _make_gql_mock({"teams": {"teams": {"nodes": TEAM_NODES}}})  # type: ignore[assignment]
        with pytest.raises(ValueError, match="Linear team not found: NOPE"):
            await adapter._resolve_team_id("NOPE")


# ---------------------------------------------------------------------------
# _resolve_state_id
# ---------------------------------------------------------------------------


class TestResolveStateId:
    @pytest.mark.asyncio
    async def test_finds_state_for_team(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            return _gql_response(_filtered_workflow_states(body.get("variables", {})))

        adapter._client.post = mock_post  # type: ignore[assignment]
        state_id = await adapter._resolve_state_id("team-uuid-1", "In Progress")
        assert state_id == "state-inprog"

    @pytest.mark.asyncio
    async def test_raises_for_unknown_state(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            return _gql_response(_filtered_workflow_states(body.get("variables", {})))

        adapter._client.post = mock_post  # type: ignore[assignment]
        with pytest.raises(ValueError, match='Linear state "Review" not found'):
            await adapter._resolve_state_id("team-uuid-1", "Review")

    @pytest.mark.asyncio
    async def test_filters_by_team_id(self) -> None:
        """A state that exists for team-uuid-1 should not match team-uuid-2."""
        extra_states = [
            *WORKFLOW_STATES,
            {"id": "state-other", "name": "In Progress", "team": {"id": "team-uuid-2"}},
        ]
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            name = body.get("variables", {}).get("name", "")
            filtered = [s for s in extra_states if s["name"] == name]
            return _gql_response({"workflowStates": {"nodes": filtered}})

        adapter._client.post = mock_post  # type: ignore[assignment]
        state_id = await adapter._resolve_state_id("team-uuid-2", "In Progress")
        assert state_id == "state-other"


# ---------------------------------------------------------------------------
# _resolve_issue_id
# ---------------------------------------------------------------------------


class TestResolveIssueId:
    @pytest.mark.asyncio
    async def test_finds_issue(self) -> None:
        adapter = _adapter()
        adapter._client.post = _make_gql_mock(  # type: ignore[assignment]
            {
                "issueSearch": {
                    "issueSearch": {"nodes": [{"id": "issue-uuid-42", "identifier": "ENG-42"}]}
                }
            }
        )
        issue_id = await adapter._resolve_issue_id("ENG-42")
        assert issue_id == "issue-uuid-42"

    @pytest.mark.asyncio
    async def test_raises_for_missing_issue(self) -> None:
        adapter = _adapter()
        adapter._client.post = _make_gql_mock(  # type: ignore[assignment]
            {"issueSearch": {"issueSearch": {"nodes": []}}}
        )
        with pytest.raises(ValueError, match="Linear issue not found: ENG-999"):
            await adapter._resolve_issue_id("ENG-999")


# ---------------------------------------------------------------------------
# _resolve_label_ids
# ---------------------------------------------------------------------------


class TestResolveLabelIds:
    @pytest.mark.asyncio
    async def test_returns_matching_labels(self) -> None:
        adapter = _adapter()
        adapter._client.post = _make_gql_mock(  # type: ignore[assignment]
            {"issueLabels": {"issueLabels": {"nodes": LABEL_NODES}}}
        )
        ids = await adapter._resolve_label_ids("team-uuid-1", ["backend", "bug"])
        assert "lbl-1" in ids  # team match
        assert "lbl-3" in ids  # workspace-level (team is None)
        assert "lbl-4" not in ids  # different team

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_matches(self) -> None:
        adapter = _adapter()
        adapter._client.post = _make_gql_mock(  # type: ignore[assignment]
            {"issueLabels": {"issueLabels": {"nodes": LABEL_NODES}}}
        )
        ids = await adapter._resolve_label_ids("team-uuid-1", ["nonexistent"])
        assert ids == []

    @pytest.mark.asyncio
    async def test_workspace_level_label_matches_any_team(self) -> None:
        adapter = _adapter()
        adapter._client.post = _make_gql_mock(  # type: ignore[assignment]
            {"issueLabels": {"issueLabels": {"nodes": LABEL_NODES}}}
        )
        ids = await adapter._resolve_label_ids("team-uuid-2", ["bug"])
        assert "lbl-3" in ids


# ---------------------------------------------------------------------------
# create_ticket
# ---------------------------------------------------------------------------


class TestCreateTicket:
    @pytest.mark.asyncio
    async def test_creates_basic_issue(self) -> None:
        adapter = _adapter()
        captured_inputs: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "teams" in query:
                return _gql_response({"teams": {"nodes": TEAM_NODES}})
            if "workflowStates" in query:
                return _gql_response(_filtered_workflow_states(variables))
            if "issueCreate" in query:
                captured_inputs.append(variables.get("input", {}))
                return _gql_response(
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {
                                "identifier": "ENG-1",
                                "url": "https://linear.app/team/ENG-1",
                            },
                        }
                    }
                )
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        result = await adapter.create_ticket(
            CreateTicketInput(
                project_key="ENG",
                summary="New feature",
                description="Build a thing",
                status=SectionStatus(state="todo"),
            )
        )

        assert result.ticket_id == "ENG-1"
        assert result.ticket_url == "https://linear.app/team/ENG-1"

        inp = captured_inputs[0]
        assert inp["teamId"] == "team-uuid-1"
        assert inp["title"] == "New feature"
        assert inp["description"] == "Build a thing"
        assert inp["stateId"] == "state-todo"

    @pytest.mark.asyncio
    async def test_creates_issue_with_labels(self) -> None:
        adapter = _adapter()
        captured_inputs: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "teams" in query:
                return _gql_response({"teams": {"nodes": TEAM_NODES}})
            if "workflowStates" in query:
                return _gql_response(_filtered_workflow_states(variables))
            if "issueLabels" in query:
                return _gql_response({"issueLabels": {"nodes": LABEL_NODES}})
            if "issueCreate" in query:
                captured_inputs.append(variables.get("input", {}))
                return _gql_response(
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {
                                "identifier": "ENG-2",
                                "url": "https://linear.app/team/ENG-2",
                            },
                        }
                    }
                )
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.create_ticket(
            CreateTicketInput(
                project_key="ENG",
                summary="Labeled ticket",
                description="",
                status=SectionStatus(state="draft"),
                labels=["backend", "bug"],
            )
        )

        inp = captured_inputs[0]
        assert "labelIds" in inp
        assert "lbl-1" in inp["labelIds"]
        assert "lbl-3" in inp["labelIds"]

    @pytest.mark.asyncio
    async def test_creates_subtask_with_parent(self) -> None:
        adapter = _adapter()
        captured_inputs: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "teams" in query:
                return _gql_response({"teams": {"nodes": TEAM_NODES}})
            if "workflowStates" in query:
                return _gql_response(_filtered_workflow_states(variables))
            if "issueSearch" in query:
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "parent-uuid", "identifier": "ENG-10"}]}}
                )
            if "issueCreate" in query:
                captured_inputs.append(variables.get("input", {}))
                return _gql_response(
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {
                                "identifier": "ENG-11",
                                "url": "https://linear.app/team/ENG-11",
                            },
                        }
                    }
                )
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.create_ticket(
            CreateTicketInput(
                project_key="ENG",
                summary="Sub-task",
                description="child item",
                status=SectionStatus(state="in_progress"),
                parent_ticket_id="ENG-10",
            )
        )

        inp = captured_inputs[0]
        assert inp["parentId"] == "parent-uuid"

    @pytest.mark.asyncio
    async def test_none_description_passed_as_none(self) -> None:
        adapter = _adapter()
        captured_inputs: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "teams" in query:
                return _gql_response({"teams": {"nodes": TEAM_NODES}})
            if "workflowStates" in query:
                return _gql_response(_filtered_workflow_states(variables))
            if "issueCreate" in query:
                captured_inputs.append(variables.get("input", {}))
                return _gql_response(
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {
                                "identifier": "ENG-3",
                                "url": "https://linear.app/team/ENG-3",
                            },
                        }
                    }
                )
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.create_ticket(
            CreateTicketInput(
                project_key="ENG",
                summary="No desc",
                description="",
                status=SectionStatus(state="draft"),
            )
        )

        # Empty string becomes None due to `or None`
        assert captured_inputs[0]["description"] is None

    @pytest.mark.asyncio
    async def test_status_mapping_draft_to_backlog(self) -> None:
        adapter = _adapter()
        captured_inputs: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "teams" in query:
                return _gql_response({"teams": {"nodes": TEAM_NODES}})
            if "workflowStates" in query:
                return _gql_response(_filtered_workflow_states(variables))
            if "issueCreate" in query:
                captured_inputs.append(variables.get("input", {}))
                return _gql_response(
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {
                                "identifier": "ENG-4",
                                "url": "https://linear.app/team/ENG-4",
                            },
                        }
                    }
                )
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.create_ticket(
            CreateTicketInput(
                project_key="ENG",
                summary="Draft item",
                description="",
                status=SectionStatus(state="draft"),
            )
        )

        assert captured_inputs[0]["stateId"] == "state-backlog"

    @pytest.mark.asyncio
    async def test_status_mapping_done(self) -> None:
        adapter = _adapter()
        captured_inputs: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "teams" in query:
                return _gql_response({"teams": {"nodes": TEAM_NODES}})
            if "workflowStates" in query:
                return _gql_response(_filtered_workflow_states(variables))
            if "issueCreate" in query:
                captured_inputs.append(variables.get("input", {}))
                return _gql_response(
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {
                                "identifier": "ENG-5",
                                "url": "https://linear.app/team/ENG-5",
                            },
                        }
                    }
                )
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.create_ticket(
            CreateTicketInput(
                project_key="ENG",
                summary="Done item",
                description="complete",
                status=SectionStatus(state="done"),
            )
        )

        assert captured_inputs[0]["stateId"] == "state-done"

    @pytest.mark.asyncio
    async def test_status_mapping_deprecated_to_canceled(self) -> None:
        adapter = _adapter()
        captured_inputs: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "teams" in query:
                return _gql_response({"teams": {"nodes": TEAM_NODES}})
            if "workflowStates" in query:
                return _gql_response(_filtered_workflow_states(variables))
            if "issueCreate" in query:
                captured_inputs.append(variables.get("input", {}))
                return _gql_response(
                    {
                        "issueCreate": {
                            "success": True,
                            "issue": {
                                "identifier": "ENG-6",
                                "url": "https://linear.app/team/ENG-6",
                            },
                        }
                    }
                )
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.create_ticket(
            CreateTicketInput(
                project_key="ENG",
                summary="Deprecated item",
                description="",
                status=SectionStatus(state="deprecated"),
            )
        )

        assert captured_inputs[0]["stateId"] == "state-canceled"


# ---------------------------------------------------------------------------
# update_ticket
# ---------------------------------------------------------------------------


class TestUpdateTicket:
    @pytest.mark.asyncio
    async def test_updates_title_and_description(self) -> None:
        adapter = _adapter()
        captured_update: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "issueSearch" in query:
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "issue-uuid", "identifier": "ENG-1"}]}}
                )
            if "issueUpdate" in query:
                captured_update.append(variables)
                return _gql_response({"issueUpdate": {"success": True}})
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.update_ticket(
            UpdateTicketInput(
                ticket_id="ENG-1",
                summary="Updated title",
                description="Updated body",
            )
        )

        assert len(captured_update) == 1
        assert captured_update[0]["input"]["title"] == "Updated title"
        assert captured_update[0]["input"]["description"] == "Updated body"

    @pytest.mark.asyncio
    async def test_updates_status_only(self) -> None:
        adapter = _adapter()
        captured_update: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "issueSearch" in query:
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "issue-uuid", "identifier": "ENG-1"}]}}
                )
            if "issue(id:" in query or (
                "issue" in query
                and "team" in query
                and "issueUpdate" not in query
                and "issueCreate" not in query
                and "issueSearch" not in query
            ):
                return _gql_response({"issue": {"team": {"id": "team-uuid-1"}}})
            if "workflowStates" in query:
                return _gql_response(_filtered_workflow_states(variables))
            if "issueUpdate" in query:
                captured_update.append(variables)
                return _gql_response({"issueUpdate": {"success": True}})
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.update_ticket(
            UpdateTicketInput(ticket_id="ENG-1", status=SectionStatus(state="in_progress"))
        )

        assert len(captured_update) == 1
        assert captured_update[0]["input"]["stateId"] == "state-inprog"
        assert "title" not in captured_update[0]["input"]

    @pytest.mark.asyncio
    async def test_no_op_when_empty(self) -> None:
        adapter = _adapter()
        call_count = 0

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            body = kwargs.get("json", {})
            query = body.get("query", "")
            if "issueSearch" in query:
                call_count += 1
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "issue-uuid", "identifier": "ENG-1"}]}}
                )
            if "issueUpdate" in query:
                call_count += 1
                return _gql_response({"issueUpdate": {"success": True}})
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.update_ticket(UpdateTicketInput(ticket_id="ENG-1"))

        # Should resolve issue id but NOT call issueUpdate
        assert call_count == 1  # only the issueSearch

    @pytest.mark.asyncio
    async def test_partial_update_summary_only(self) -> None:
        adapter = _adapter()
        captured_update: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "issueSearch" in query:
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "issue-uuid", "identifier": "ENG-1"}]}}
                )
            if "issueUpdate" in query:
                captured_update.append(variables)
                return _gql_response({"issueUpdate": {"success": True}})
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.update_ticket(UpdateTicketInput(ticket_id="ENG-1", summary="Only title"))

        assert captured_update[0]["input"] == {"title": "Only title"}


# ---------------------------------------------------------------------------
# get_ticket_status
# ---------------------------------------------------------------------------


class TestGetTicketStatus:
    @pytest.mark.asyncio
    async def test_returns_mapped_status_started(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            if "issueSearch" in query:
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "issue-uuid", "identifier": "ENG-10"}]}}
                )
            if "issue" in query and "state" in query:
                return _gql_response(
                    {"issue": {"state": {"name": "In Progress", "type": "started"}}}
                )
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        result = await adapter.get_ticket_status("ENG-10")
        assert result.ticket_id == "ENG-10"
        assert result.status == SectionStatus(state="in_progress")
        assert result.raw_status == "In Progress"

    @pytest.mark.asyncio
    async def test_completed_maps_to_done(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            if "issueSearch" in query:
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "issue-uuid", "identifier": "ENG-11"}]}}
                )
            if "issue" in query:
                return _gql_response({"issue": {"state": {"name": "Done", "type": "completed"}}})
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        result = await adapter.get_ticket_status("ENG-11")
        assert result.status == SectionStatus(state="done")

    @pytest.mark.asyncio
    async def test_canceled_maps_to_deprecated(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            if "issueSearch" in query:
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "issue-uuid", "identifier": "ENG-12"}]}}
                )
            if "issue" in query:
                return _gql_response({"issue": {"state": {"name": "Canceled", "type": "canceled"}}})
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        result = await adapter.get_ticket_status("ENG-12")
        assert result.status == SectionStatus(state="deprecated")

    @pytest.mark.asyncio
    async def test_backlog_maps_to_draft(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            if "issueSearch" in query:
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "issue-uuid", "identifier": "ENG-13"}]}}
                )
            if "issue" in query:
                return _gql_response({"issue": {"state": {"name": "Backlog", "type": "backlog"}}})
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        result = await adapter.get_ticket_status("ENG-13")
        assert result.status == SectionStatus(state="draft")

    @pytest.mark.asyncio
    async def test_unstarted_maps_to_todo(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            if "issueSearch" in query:
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "issue-uuid", "identifier": "ENG-14"}]}}
                )
            if "issue" in query:
                return _gql_response({"issue": {"state": {"name": "Todo", "type": "unstarted"}}})
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        result = await adapter.get_ticket_status("ENG-14")
        assert result.status == SectionStatus(state="todo")


# ---------------------------------------------------------------------------
# link_pr
# ---------------------------------------------------------------------------


class TestLinkPr:
    @pytest.mark.asyncio
    async def test_creates_attachment(self) -> None:
        adapter = _adapter()
        captured: list[dict[str, Any]] = []

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            variables = body.get("variables", {})

            if "issueSearch" in query:
                return _gql_response(
                    {"issueSearch": {"nodes": [{"id": "issue-uuid", "identifier": "ENG-1"}]}}
                )
            if "attachmentCreate" in query:
                captured.append(variables)
                return _gql_response({"attachmentCreate": {"success": True}})
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.link_pr("ENG-1", "https://github.com/org/repo/pull/42", "Fix auth bug")

        assert len(captured) == 1
        inp = captured[0]["input"]
        assert inp["issueId"] == "issue-uuid"
        assert inp["url"] == "https://github.com/org/repo/pull/42"
        assert inp["title"] == "Fix auth bug"


# ---------------------------------------------------------------------------
# search_tickets
# ---------------------------------------------------------------------------


class TestSearchTickets:
    @pytest.mark.asyncio
    async def test_returns_parsed_results(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_response(
                {
                    "issueSearch": {
                        "nodes": [
                            {
                                "identifier": "ENG-10",
                                "title": "Auth login flow",
                                "url": "https://linear.app/team/ENG-10",
                                "state": {"name": "In Progress", "type": "started"},
                            },
                            {
                                "identifier": "ENG-11",
                                "title": "Auth logout",
                                "url": "https://linear.app/team/ENG-11",
                                "state": {"name": "Done", "type": "completed"},
                            },
                        ]
                    }
                }
            )

        adapter._client.post = mock_post  # type: ignore[assignment]

        results = await adapter.search_tickets("ENG", "Auth")
        assert len(results) == 2
        assert results[0].ticket_id == "ENG-10"
        assert results[0].title == "Auth login flow"
        assert results[0].state == "open"
        assert results[1].ticket_id == "ENG-11"
        assert results[1].state == "closed"

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_response({"issueSearch": {"nodes": []}})

        adapter._client.post = mock_post  # type: ignore[assignment]

        results = await adapter.search_tickets("ENG", "Nonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_canceled_state_is_closed(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_response(
                {
                    "issueSearch": {
                        "nodes": [
                            {
                                "identifier": "ENG-20",
                                "title": "Canceled thing",
                                "url": "https://linear.app/team/ENG-20",
                                "state": {"name": "Canceled", "type": "canceled"},
                            },
                        ]
                    }
                }
            )

        adapter._client.post = mock_post  # type: ignore[assignment]

        results = await adapter.search_tickets("ENG", "Canceled")
        assert results[0].state == "closed"

    @pytest.mark.asyncio
    async def test_non_terminal_state_is_open(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_response(
                {
                    "issueSearch": {
                        "nodes": [
                            {
                                "identifier": "ENG-21",
                                "title": "Backlog item",
                                "url": "https://linear.app/team/ENG-21",
                                "state": {"name": "Backlog", "type": "backlog"},
                            },
                        ]
                    }
                }
            )

        adapter._client.post = mock_post  # type: ignore[assignment]

        results = await adapter.search_tickets("ENG", "Backlog")
        assert results[0].state == "open"

    @pytest.mark.asyncio
    async def test_passes_title_pattern_as_query(self) -> None:
        adapter = _adapter()
        captured_variables: dict[str, Any] = {}

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            captured_variables.update(body.get("variables", {}))
            return _gql_response({"issueSearch": {"nodes": []}})

        adapter._client.post = mock_post  # type: ignore[assignment]

        await adapter.search_tickets("ENG", "Auth login")
        assert captured_variables["q"] == "Auth login"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_401_raises_runtime_error(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _http_error_response(401, "Unauthorized")

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="Linear API 401"):
            await adapter._gql("{ viewer { id } }")

    @pytest.mark.asyncio
    async def test_429_raises_runtime_error(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _http_error_response(429, "Rate limited")

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="Linear API 429"):
            await adapter._gql("{ viewer { id } }")

    @pytest.mark.asyncio
    async def test_404_raises_runtime_error(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _http_error_response(404, "Not Found")

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="Linear API 404"):
            await adapter._gql("{ viewer { id } }")

    @pytest.mark.asyncio
    async def test_500_raises_runtime_error(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _http_error_response(500, "Internal Server Error")

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="Linear API 500"):
            await adapter._gql("{ viewer { id } }")

    @pytest.mark.asyncio
    async def test_graphql_error_with_message(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_error_response("Variable '$id' is not defined")

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="Variable '\\$id' is not defined"):
            await adapter._gql("query { bad }")

    @pytest.mark.asyncio
    async def test_network_error_propagates(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(httpx.ConnectError):
            await adapter._gql("{ viewer { id } }")

    @pytest.mark.asyncio
    async def test_timeout_error_propagates(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            raise httpx.ReadTimeout("Read timed out")

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(httpx.ReadTimeout):
            await adapter._gql("{ viewer { id } }")

    @pytest.mark.asyncio
    async def test_graphql_auth_error_message(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_error_response("Authentication required")

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="Authentication required"):
            await adapter._gql("{ viewer { id } }")

    @pytest.mark.asyncio
    async def test_create_ticket_team_not_found_error(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_response({"teams": {"nodes": TEAM_NODES}})

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(ValueError, match="Linear team not found: MISSING"):
            await adapter.create_ticket(
                CreateTicketInput(
                    project_key="MISSING",
                    summary="Fail",
                    description="",
                    status=SectionStatus(state="todo"),
                )
            )

    @pytest.mark.asyncio
    async def test_update_ticket_issue_not_found(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_response({"issueSearch": {"nodes": []}})

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(ValueError, match="Linear issue not found: ENG-999"):
            await adapter.update_ticket(UpdateTicketInput(ticket_id="ENG-999", summary="Update"))

    @pytest.mark.asyncio
    async def test_get_ticket_status_issue_not_found(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_response({"issueSearch": {"nodes": []}})

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(ValueError, match="Linear issue not found: ENG-999"):
            await adapter.get_ticket_status("ENG-999")

    @pytest.mark.asyncio
    async def test_link_pr_issue_not_found(self) -> None:
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            return _gql_response({"issueSearch": {"nodes": []}})

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(ValueError, match="Linear issue not found: ENG-999"):
            await adapter.link_pr("ENG-999", "https://github.com/org/repo/pull/1", "PR")

    @pytest.mark.asyncio
    async def test_create_ticket_state_not_found(self) -> None:
        """When the target workflow state doesn't exist for the team."""
        adapter = _adapter()

        async def mock_post(url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json", {})
            query = body.get("query", "")
            if "teams" in query:
                return _gql_response({"teams": {"nodes": TEAM_NODES}})
            if "workflowStates" in query:
                return _gql_response({"workflowStates": {"nodes": []}})
            return _gql_response({})

        adapter._client.post = mock_post  # type: ignore[assignment]

        with pytest.raises(ValueError, match='Linear state "Todo" not found'):
            await adapter.create_ticket(
                CreateTicketInput(
                    project_key="ENG",
                    summary="Fail",
                    description="",
                    status=SectionStatus(state="todo"),
                )
            )
