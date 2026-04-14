"""Tests for the public v1 API consumed by the GitHub Actions suite."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.agent.client import CompletionResult
from canon.main import app
from canon.web.cache import TTLCache

SAMPLE_SPEC_MD = """\
---
title: Auth Spec
status: in_progress
owner: dev
team: platform
---

## 1. Login Flow
<!-- canon:system:1 status:in_progress -->

### Acceptance Criteria

- [ ] Username validation with regex
- [x] Password hashing with bcrypt

## 2. Session Management
<!-- canon:system:2 status:todo -->

### Acceptance Criteria

- [ ] JWT token generation
- [ ] Token refresh endpoint
"""


MOCK_CLAUDE_RESPONSE = json.dumps(
    {
        "sections": [
            {
                "sectionId": "1-login-flow",
                "sectionNumber": "1",
                "currentStatus": "in_progress",
                "recommendedStatus": "done",
                "confidence": "high",
                "reasoning": "All ACs implemented",
                "acEvaluations": [
                    {
                        "acText": "Username validation with regex",
                        "status": "realized",
                        "evidence": "src/auth.py:10",
                    }
                ],
            },
            {
                "sectionId": "2-session-management",
                "sectionNumber": "2",
                "currentStatus": "todo",
                "recommendedStatus": "in_progress",
                "confidence": "medium",
                "reasoning": "JWT generation found",
                "acEvaluations": [
                    {
                        "acText": "JWT token generation",
                        "status": "realized",
                        "evidence": "src/tokens.py:5",
                    }
                ],
            },
        ]
    }
)


def _mock_claude_client(*, available: bool = True) -> MagicMock:
    mock = MagicMock()
    mock.is_available = available
    if available:
        mock.complete.return_value = CompletionResult(
            text=MOCK_CLAUDE_RESPONSE,
            input_tokens=1234,
            output_tokens=567,
        )
    return mock


@pytest.fixture(autouse=True)
def _setup_app_state():
    """Configure the FastAPI app for the test client.

    Default ``Settings()`` has no Auth0/OIDC config, so ``auth_enabled``
    is False and anonymous requests get the all-permissions
    ``ANONYMOUS_USER``. That lets us drive the endpoint without spinning
    up a real user store; auth wiring is covered in test_auth.
    """
    from canon.settings import Settings

    app.state.settings = Settings()
    app.state.cache = TTLCache(ttl_seconds=60)
    yield


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True,
    )


class TestPostAudit:
    async def test_returns_recommendations_with_claude(self, client: AsyncClient):
        with patch("canon.web.api_v1_actions.ClaudeClient", return_value=_mock_claude_client()):
            resp = await client.post(
                "/v1/actions/audit",
                json={
                    "specs": [{"path": "docs/specs/auth.md", "raw_md": SAMPLE_SPEC_MD}],
                    "evidence": [
                        {
                            "spec_path": "docs/specs/auth.md",
                            "section_evidence": {
                                "1-login-flow": ["src/auth.py:10: def username_validation():"]
                            },
                        }
                    ],
                    "repo": "owner/repo",
                    "workflow_run_id": "1234",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "recommendations" in body
        assert "summary" in body
        assert body["summary"]["mode"] == "claude"
        assert body["summary"]["specs_scanned"] >= 1
        assert body["summary"]["recommendations"] >= 1
        assert body["summary"]["input_tokens"] == 1234
        assert body["summary"]["output_tokens"] == 567

        recs = body["recommendations"]
        section_ids = {r["section_id"] for r in recs}
        assert "1-login-flow" in section_ids
        for r in recs:
            assert r["spec"] == "docs/specs/auth.md"
            assert r["spec_title"] == "Auth Spec"
            assert "ac_evaluations" in r

    async def test_returns_recommendations_without_claude(self, client: AsyncClient):
        # No Claude available — endpoint should still return a heuristic mode
        # response without erroring.
        with patch(
            "canon.web.api_v1_actions.ClaudeClient",
            return_value=_mock_claude_client(available=False),
        ):
            resp = await client.post(
                "/v1/actions/audit",
                json={
                    "specs": [{"path": "docs/specs/auth.md", "raw_md": SAMPLE_SPEC_MD}],
                    "evidence": [],
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"]["mode"] == "heuristic"
        assert isinstance(body["recommendations"], list)

    async def test_specs_scanned_and_tokens_count_empty_recommendations(self, client: AsyncClient):
        """Regression: a spec that consumes Claude tokens but produces no
        recommendations must still count toward specs_scanned and the
        token totals. The earlier implementation `continue`d before the
        counters, silently dropping billing-relevant metrics."""
        from canon.agent.client import CompletionResult

        empty_response = json.dumps({"sections": []})
        mock = _mock_claude_client()
        mock.complete.return_value = CompletionResult(
            text=empty_response,
            input_tokens=4242,
            output_tokens=99,
        )

        with patch("canon.web.api_v1_actions.ClaudeClient", return_value=mock):
            resp = await client.post(
                "/v1/actions/audit",
                json={
                    "specs": [{"path": "docs/specs/auth.md", "raw_md": SAMPLE_SPEC_MD}],
                    "evidence": [],
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        # No recommendations came back
        assert body["recommendations"] == []
        assert body["summary"]["recommendations"] == 0
        # …but the spec was still evaluated and the tokens were still spent
        assert body["summary"]["specs_scanned"] == 1
        assert body["summary"]["input_tokens"] == 4242
        assert body["summary"]["output_tokens"] == 99

    async def test_rejects_oversized_spec(self, client: AsyncClient):
        oversized = "x" * (600_000)  # > MAX_SPEC_BYTES
        resp = await client.post(
            "/v1/actions/audit",
            json={"specs": [{"path": "docs/specs/big.md", "raw_md": oversized}]},
        )
        assert resp.status_code == 413
        assert "limit" in resp.json()["detail"].lower()

    async def test_rejects_too_many_specs(self, client: AsyncClient):
        # Build 51 minimal specs — exceeds MAX_SPECS_PER_REQUEST = 50
        specs = [{"path": f"docs/specs/spec_{i}.md", "raw_md": SAMPLE_SPEC_MD} for i in range(51)]
        resp = await client.post("/v1/actions/audit", json={"specs": specs})
        assert resp.status_code == 422  # pydantic validation error

    async def test_empty_specs_rejected(self, client: AsyncClient):
        resp = await client.post("/v1/actions/audit", json={"specs": []})
        assert resp.status_code == 422

    async def test_evidence_optional(self, client: AsyncClient):
        # Evidence is optional — without it, the endpoint should still
        # parse the spec and run the heuristic/Claude path.
        with patch(
            "canon.web.api_v1_actions.ClaudeClient",
            return_value=_mock_claude_client(available=False),
        ):
            resp = await client.post(
                "/v1/actions/audit",
                json={"specs": [{"path": "docs/specs/auth.md", "raw_md": SAMPLE_SPEC_MD}]},
            )
        assert resp.status_code == 200
        # No evidence → heuristic finds nothing → empty recs is fine
        body = resp.json()
        assert body["summary"]["mode"] == "heuristic"
