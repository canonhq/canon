"""Tests for editor routes."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from canon.main import app
from canon.web.cache import TTLCache
from canon.web.editor_routes import (
    _check_generate_rate,
    _extract_prose,
    _generate_rate,
    _section_to_dict,
    _validate_file_path,
)


def _mock_client() -> AsyncMock:
    client = AsyncMock()
    client.list_installation_repos = AsyncMock(return_value=[])
    client.list_directory = AsyncMock(return_value=[])
    client.get_file_content = AsyncMock(side_effect=Exception("not found"))
    client._get = AsyncMock(side_effect=Exception("not found"))
    return client


@pytest.fixture(autouse=True)
def _setup_app_state():
    """Set up app state for editor route tests."""
    from canon.settings import Settings

    app.state.settings = Settings(web_org="test-org")
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.github_client = _mock_client()
    app.state.github_oauth_client = None
    app.state.search_index = None
    app.state.embed_client = None
    app.state.registry = None
    app.state.agent_store = None
    yield


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


class TestFilePathValidation:
    def test_valid_spec_path(self):
        assert _validate_file_path("docs/specs/my-feature.md") is True

    def test_rejects_path_traversal(self):
        assert _validate_file_path("docs/../.github/workflows/deploy.yml") is False
        assert _validate_file_path("../../etc/passwd") is False

    def test_rejects_non_md_file(self):
        assert _validate_file_path("docs/specs/config.yaml") is False
        assert _validate_file_path("src/main.py") is False

    def test_accepts_nested_md(self):
        assert _validate_file_path("docs/rfcs/deep/nested/spec.md") is True


class TestEditorRouteAccess:
    @pytest.mark.asyncio
    async def test_editor_redirects_without_github_user_no_spa(self, client):
        """Without SPA, editor HTML routes redirect to GitHub login."""
        with patch("canon.web.editor_routes._serve_spa", return_value=None):
            resp = await client.get("/app/TestOrg/editor/")
            assert resp.status_code in (302, 307)
            assert "/auth/github/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_editor_load_redirects_without_github_user_no_spa(self, client):
        with patch("canon.web.editor_routes._serve_spa", return_value=None):
            resp = await client.get("/app/TestOrg/editor/acme/repo/docs/specs/test.md")
            assert resp.status_code in (302, 307)
            assert "/auth/github/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_editor_new_redirects_without_github_user_no_spa(self, client):
        with patch("canon.web.editor_routes._serve_spa", return_value=None):
            resp = await client.get("/app/TestOrg/editor/acme/repo/new")
            assert resp.status_code in (302, 307)
            assert "/auth/github/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_editor_json_api_returns_401_without_github_user(self, client):
        """JSON API endpoints return 401 when no GitHub user in session."""
        resp = await client.get("/app/TestOrg/editor/repos")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_editor_file_json_api_returns_401_without_github_user(self, client):
        resp = await client.get("/app/TestOrg/editor/acme/repo/docs/specs/test.md/json")
        assert resp.status_code == 401


class TestEditorSaveEndpoints:
    @pytest.mark.asyncio
    async def test_save_returns_401_without_github_user(self, client):
        resp = await client.post(
            "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save",
            json={"content": "test", "sha": "abc"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_save_pr_returns_401_without_github_user(self, client):
        resp = await client.post(
            "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save-pr",
            json={"content": "test", "sha": "abc"},
        )
        assert resp.status_code == 401


class TestEditorPreview:
    @pytest.mark.asyncio
    async def test_preview_returns_401_without_github_user(self, client):
        resp = await client.post(
            "/app/TestOrg/editor/acme/repo/preview",
            json={"content": "# Hello"},
        )
        assert resp.status_code == 401


class TestPathTraversalProtection:
    @pytest.mark.asyncio
    async def test_save_rejects_path_traversal(self, client):
        """Save endpoint should reject paths with .. components."""
        resp = await client.post(
            "/app/TestOrg/editor/acme/repo/../../.github/workflows/deploy.yml/save",
            json={"content": "test", "sha": "abc"},
        )
        # Either 400 (path validation) or 401 (auth check runs first)
        assert resp.status_code in (400, 401)

    @pytest.mark.asyncio
    async def test_save_rejects_non_md_file(self, client):
        """Save endpoint should reject non-.md file paths."""
        resp = await client.post(
            "/app/TestOrg/editor/acme/repo/src/main.py/save",
            json={"content": "test", "sha": "abc"},
        )
        # Either 400 (path validation) or 401 (auth check runs first)
        assert resp.status_code in (400, 401)


# ─── Helpers for authenticated tests ────────────────────────────

MOCK_GITHUB_USER = {"login": "testuser", "token": "ghp_test123", "name": "Test User"}

SAMPLE_SPEC = """---
title: Test Feature
status: draft
owner: testuser
team: platform
---

## 1. User Authentication

<!-- specwright:system:1 status:in_progress -->
<!-- specwright:ticket:github:PROJ-101 -->

Users must be able to log in with email and password.

### Acceptance Criteria

- [x] Login form accepts email and password
<!-- specwright:realized-in:PR#42 file:src/auth.py:10-25 -->
- [ ] Invalid credentials show error message
- [ ] Session persists across page reloads

## 2. Dashboard

<!-- specwright:system:2 status:draft -->

The dashboard shows key metrics.

### Acceptance Criteria

- [ ] Display total users count
- [ ] Show revenue chart
"""


class TestEditorParse:
    """Tests for the parse endpoint."""

    @pytest.mark.asyncio
    async def test_parse_returns_sections_json(self, client):
        """Parse endpoint returns structured sections."""
        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/parse",
                json={"content": SAMPLE_SPEC},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        sections = data["sections"]
        assert len(sections) == 2

        # First section
        sec1 = sections[0]
        assert sec1["title"] == "User Authentication"
        assert sec1["section_number"] == "1"
        assert sec1["depth"] == 2
        assert sec1["status"] == "in_progress"
        assert sec1["id"] == "1-user-authentication"

        # ACs
        acs = sec1["acceptance_criteria"]
        assert len(acs) == 3
        assert acs[0]["checked"] is True
        assert acs[0]["text"] == "Login form accepts email and password"
        assert len(acs[0]["realized_in"]) == 1
        assert acs[0]["realized_in"][0]["pr_number"] == 42
        assert acs[1]["checked"] is False

    @pytest.mark.asyncio
    async def test_parse_includes_prose_content(self, client):
        """Parse extracts prose_content without ACs or system comments."""
        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/parse",
                json={"content": SAMPLE_SPEC},
            )
        data = resp.json()
        sec1 = data["sections"][0]
        prose = sec1["prose_content"]
        # Should contain the description but not AC checkboxes or comments
        assert "Users must be able to log in" in prose
        assert "- [x]" not in prose
        assert "specwright:system" not in prose

    @pytest.mark.asyncio
    async def test_parse_returns_401_without_auth(self, client):
        """Parse endpoint requires GitHub authentication."""
        resp = await client.post(
            "/app/TestOrg/editor/acme/repo/parse",
            json={"content": "# test"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_parse_returns_400_for_malformed_json(self, client):
        """Parse endpoint returns 400 for missing content field."""
        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/parse",
                json={"wrong_field": "test"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_parse_returns_400_for_invalid_content(self, client):
        """Parse endpoint returns 400 for unparseable content."""
        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes.parse_spec",
                side_effect=ValueError("bad content"),
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/parse",
                json={"content": "not valid"},
            )
        assert resp.status_code == 400


class TestEditorConflictDetection:
    """Tests for conflict detection in the save endpoint."""

    @pytest.mark.asyncio
    async def test_save_returns_enriched_409_on_conflict(self, client):
        """Save returns server_content and server_sha on 409 conflict."""
        mock_user_client = AsyncMock()
        # Simulate 409 conflict from GitHub API
        mock_user_client.create_or_update_file = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "409 Conflict",
                request=httpx.Request("PUT", "https://api.github.com/test"),
                response=httpx.Response(409),
            )
        )
        # get_file returns the server version
        mock_user_client.get_file = AsyncMock(return_value=("server content here", "new_sha_abc"))
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save",
                json={"content": "updated content", "sha": "old_sha"},
            )

        assert resp.status_code == 409
        data = resp.json()
        assert data["error"] == "conflict"
        assert data["server_content"] == "server content here"
        assert data["server_sha"] == "new_sha_abc"

    @pytest.mark.asyncio
    async def test_save_409_handles_get_file_failure(self, client):
        """When get_file also fails during conflict, return null fields."""
        mock_user_client = AsyncMock()
        mock_user_client.create_or_update_file = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "409 Conflict",
                request=httpx.Request("PUT", "https://api.github.com/test"),
                response=httpx.Response(409),
            )
        )
        mock_user_client.get_file = AsyncMock(side_effect=Exception("network error"))
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save",
                json={"content": "content", "sha": "sha123"},
            )

        assert resp.status_code == 409
        data = resp.json()
        assert data["error"] == "conflict"
        assert data["server_content"] is None
        assert data["server_sha"] is None

    @pytest.mark.asyncio
    async def test_save_non_409_error_passes_through(self, client):
        """Non-conflict HTTP errors are returned as-is."""
        mock_user_client = AsyncMock()
        mock_user_client.create_or_update_file = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "403 Forbidden",
                request=httpx.Request("PUT", "https://api.github.com/test"),
                response=httpx.Response(403),
            )
        )
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save",
                json={"content": "content", "sha": "sha123"},
            )

        assert resp.status_code == 403


class TestMarkdownRoundTrip:
    """Tests for parse → reconstruct → re-parse roundtrip fidelity."""

    def test_extract_prose_strips_acs_and_comments(self):
        """_extract_prose removes AC checkboxes and system comments."""
        content = (
            "<!-- specwright:system:foo status:draft -->\n"
            "<!-- specwright:ticket:github:PROJ-1 -->\n"
            "\n"
            "Some description text.\n"
            "\n"
            "### Acceptance Criteria\n"
            "\n"
            "- [x] First AC\n"
            "<!-- specwright:realized-in:PR#1 file:foo.py -->\n"
            "- [ ] Second AC\n"
        )
        prose = _extract_prose(content)
        assert "Some description text." in prose
        assert "- [x]" not in prose
        assert "- [ ]" not in prose
        assert "specwright:system" not in prose
        assert "specwright:ticket" not in prose
        assert "specwright:realized-in" not in prose

    def test_extract_prose_excludes_content_after_ac_heading(self):
        """Content after the AC block should not leak into prose."""
        content = (
            "Description paragraph.\n"
            "\n"
            "### Acceptance Criteria\n"
            "\n"
            "- [x] First AC\n"
            "- [ ] Second AC\n"
            "\n"
            "Note: this trailing content is after the AC block.\n"
        )
        prose = _extract_prose(content)
        assert "Description paragraph." in prose
        assert "trailing content" not in prose

    def test_section_to_dict_preserves_acs(self):
        """_section_to_dict correctly serializes acceptance criteria."""
        from canon.parser.models import (
            AcceptanceCriterion,
            RealizationRef,
            SectionStatus,
            SpecSection,
        )

        section = SpecSection(
            id="test-section",
            section_number="1",
            title="Test Section",
            depth=2,
            content="Description text.\n\n### Acceptance Criteria\n\n- [x] First\n- [ ] Second",
            status=SectionStatus(state="in_progress"),
            acceptance_criteria=[
                AcceptanceCriterion(
                    text="First",
                    checked=True,
                    line=5,
                    realized_in=[
                        RealizationRef(pr_number=42, file_path="src/foo.py", lines="1-10")
                    ],
                ),
                AcceptanceCriterion(text="Second", checked=False, line=6),
            ],
            children=[],
            start_line=1,
            end_line=10,
        )

        d = _section_to_dict(section)
        assert d["id"] == "test-section"
        assert d["title"] == "Test Section"
        assert d["status"] == "in_progress"
        assert len(d["acceptance_criteria"]) == 2
        assert d["acceptance_criteria"][0]["checked"] is True
        assert d["acceptance_criteria"][0]["realized_in"][0]["pr_number"] == 42
        assert "prose_content" in d

    @pytest.mark.asyncio
    async def test_parse_roundtrip_preserves_structure(self, client):
        """Parse → serialize → compare verifies structure is preserved."""
        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/parse",
                json={"content": SAMPLE_SPEC},
            )

        data = resp.json()
        assert data["ok"] is True
        sections = data["sections"]

        # Verify structural integrity
        assert len(sections) == 2
        assert sections[0]["title"] == "User Authentication"
        assert sections[1]["title"] == "Dashboard"

        # Verify AC counts match
        assert len(sections[0]["acceptance_criteria"]) == 3
        assert len(sections[1]["acceptance_criteria"]) == 2

        # Verify statuses
        assert sections[0]["status"] == "in_progress"
        assert sections[1]["status"] == "draft"

        # Verify ticket link preserved
        assert sections[0].get("ticket_link") is not None
        assert sections[0]["ticket_link"]["system"] == "github"
        assert sections[0]["ticket_link"]["ticket_id"] == "PROJ-101"


class TestAiEdit:
    """Tests for the AI-assisted section editing endpoint."""

    @pytest.mark.asyncio
    async def test_ai_edit_returns_401_without_github_user(self, client):
        """AI edit endpoint requires GitHub authentication."""
        resp = await client.post(
            "/app/TestOrg/editor/acme/repo/ai-edit",
            json={
                "action": "improve",
                "section_title": "Test",
                "section_content": "Some content",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_ai_edit_returns_400_for_invalid_action(self, client):
        """AI edit endpoint rejects unknown actions."""
        with patch(
            "canon.web.editor_routes._get_github_user",
            return_value=MOCK_GITHUB_USER,
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/ai-edit",
                json={
                    "action": "invalid_action",
                    "section_title": "Test",
                    "section_content": "Some content",
                },
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_ai_edit_returns_400_for_missing_fields(self, client):
        """AI edit endpoint rejects requests with missing required fields."""
        with patch(
            "canon.web.editor_routes._get_github_user",
            return_value=MOCK_GITHUB_USER,
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/ai-edit",
                json={"action": "improve"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_ai_edit_streams_sse_for_improve(self, client):
        """AI edit endpoint returns SSE stream for improve action."""

        async def mock_stream(*args, **kwargs):
            yield "Improved "
            yield "content."

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes.improve_section_stream",
                return_value=mock_stream(),
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/ai-edit",
                json={
                    "action": "improve",
                    "section_title": "Test Section",
                    "section_content": "Original content",
                },
            )

        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        body = resp.text
        assert '"chunk"' in body
        assert '"done": true' in body

    @pytest.mark.asyncio
    async def test_ai_edit_streams_sse_for_generate_acs(self, client):
        """AI edit endpoint returns SSE stream for generate_acs action."""

        async def mock_stream(*args, **kwargs):
            yield "- [ ] First AC\n"
            yield "- [ ] Second AC\n"

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes.generate_acs_stream",
                return_value=mock_stream(),
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/ai-edit",
                json={
                    "action": "generate_acs",
                    "section_title": "Test Section",
                    "section_content": "Some content",
                },
            )

        assert resp.status_code == 200
        body = resp.text
        assert '"chunk"' in body
        assert '"done": true' in body

    @pytest.mark.asyncio
    async def test_ai_edit_rate_limiting(self, client):
        """AI edit endpoint enforces rate limits."""
        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._check_generate_rate",
                return_value=False,
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/ai-edit",
                json={
                    "action": "improve",
                    "section_title": "Test",
                    "section_content": "Content",
                },
            )
        assert resp.status_code == 429
        assert "Rate limit" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_ai_edit_streams_sse_for_expand(self, client):
        """AI edit endpoint returns SSE stream for expand action."""

        async def mock_stream(*args, **kwargs):
            yield "Expanded "
            yield "content with details."

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes.expand_section_stream",
                return_value=mock_stream(),
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/ai-edit",
                json={
                    "action": "expand",
                    "section_title": "API Design",
                    "section_content": "REST endpoints",
                },
            )

        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        body = resp.text
        assert '"chunk"' in body
        assert '"done": true' in body


class TestRateLimiter:
    """Tests for the _check_generate_rate function."""

    @pytest.fixture(autouse=True)
    def _clear_rate_state(self):
        """Clear rate limiter state before each test."""
        _generate_rate.clear()
        yield
        _generate_rate.clear()

    def test_first_request_allowed(self):
        """First request from a user is always allowed."""
        assert _check_generate_rate("user1") is True

    def test_increments_count(self):
        """Each request increments the counter."""
        for _ in range(5):
            assert _check_generate_rate("user1") is True

        # Verify counter incremented
        count, _ = _generate_rate["user1"]
        assert count == 5

    def test_rate_limit_enforced_at_max(self):
        """Requests beyond the limit are rejected."""
        # Fill up to the max (default 10)
        for _ in range(10):
            assert _check_generate_rate("user1") is True

        # 11th request should be rejected
        assert _check_generate_rate("user1") is False

    def test_different_users_independent(self):
        """Rate limits are per-user."""
        for _ in range(10):
            _check_generate_rate("user1")

        # user1 is at limit
        assert _check_generate_rate("user1") is False
        # user2 is fresh
        assert _check_generate_rate("user2") is True

    def test_window_reset(self):
        """After the window expires, the counter resets."""
        for _ in range(10):
            _check_generate_rate("user1")

        assert _check_generate_rate("user1") is False

        # Simulate window expiry by manipulating the stored timestamp
        count, _ = _generate_rate["user1"]
        _generate_rate["user1"] = (count, time.monotonic() - 301)

        # Should be allowed again (window reset)
        assert _check_generate_rate("user1") is True
        count, _ = _generate_rate["user1"]
        assert count == 1

    def test_expired_entries_evicted(self):
        """Expired entries are cleaned up to prevent memory growth."""
        # Add an entry that's expired (> 2x window = 600 seconds)
        _generate_rate["old_user"] = (5, time.monotonic() - 700)
        _generate_rate["recent_user"] = (3, time.monotonic() - 10)

        # Trigger eviction by calling _check_generate_rate for any user
        _check_generate_rate("new_user")

        assert "old_user" not in _generate_rate
        assert "recent_user" in _generate_rate


class TestEditorSaveSuccess:
    """Tests for successful save flows."""

    @pytest.mark.asyncio
    async def test_save_direct_commit_success(self, client):
        """Save endpoint commits and returns new SHA."""
        mock_user_client = AsyncMock()
        mock_user_client.create_or_update_file = AsyncMock(
            return_value={"content": {"sha": "new_sha_123"}}
        )
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
            patch("canon.web.editor_routes.analytics") as mock_analytics,
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save",
                json={"content": "# Updated spec", "sha": "old_sha"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["sha"] == "new_sha_123"

        # Verify analytics was called
        mock_analytics.track.assert_called_once()
        call_kwargs = mock_analytics.track.call_args
        assert call_kwargs[0][0] == "spec_saved"
        assert call_kwargs[1]["properties"]["method"] == "direct"

    @pytest.mark.asyncio
    async def test_save_with_custom_message(self, client):
        """Save endpoint passes custom commit message to GitHub."""
        mock_user_client = AsyncMock()
        mock_user_client.create_or_update_file = AsyncMock(
            return_value={"content": {"sha": "sha456"}}
        )
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
            patch("canon.web.editor_routes.analytics"),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save",
                json={
                    "content": "# Spec",
                    "sha": "abc",
                    "message": "feat: update auth spec with new requirements",
                },
            )

        assert resp.status_code == 200
        # Verify custom message was passed (args: owner, repo, path, content, message, sha)
        call_args = mock_user_client.create_or_update_file.call_args
        assert call_args[0][4] == "feat: update auth spec with new requirements"

    @pytest.mark.asyncio
    async def test_save_default_message_when_empty(self, client):
        """Save uses default 'docs: update {path}' when message is empty."""
        mock_user_client = AsyncMock()
        mock_user_client.create_or_update_file = AsyncMock(
            return_value={"content": {"sha": "sha789"}}
        )
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
            patch("canon.web.editor_routes.analytics"),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save",
                json={"content": "# Spec", "sha": "abc", "message": ""},
            )

        assert resp.status_code == 200
        # args: owner, repo, path, content, message, sha
        call_args = mock_user_client.create_or_update_file.call_args
        assert call_args[0][4] == "docs: update docs/specs/test.md"


class TestEditorSavePR:
    """Tests for the save-as-PR workflow."""

    @pytest.mark.asyncio
    async def test_save_pr_full_workflow(self, client):
        """Save-PR creates branch, commits file, and opens PR."""
        mock_user_client = AsyncMock()
        mock_user_client.get_repo = AsyncMock(return_value={"default_branch": "main"})
        mock_user_client.get_branch_sha = AsyncMock(return_value="base_sha_abc")
        mock_user_client.create_branch = AsyncMock(
            return_value={"ref": "refs/heads/canon/edit-test"}
        )
        mock_user_client.create_or_update_file = AsyncMock(
            return_value={"content": {"sha": "commit_sha"}}
        )
        mock_user_client.create_pull_request = AsyncMock(
            return_value={
                "number": 99,
                "html_url": "https://github.com/acme/repo/pull/99",
            }
        )
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
            patch("canon.web.editor_routes.analytics") as mock_analytics,
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save-pr",
                json={
                    "content": "# Updated spec",
                    "sha": "old_sha",
                    "message": "docs: update auth spec",
                    "branch_name": "canon/edit-test",
                    "pr_title": "Update auth spec",
                    "pr_body": "Added new requirements.",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["pr_number"] == 99
        assert data["pr_url"] == "https://github.com/acme/repo/pull/99"

        # Verify the workflow order
        mock_user_client.get_repo.assert_called_once_with("acme", "repo")
        mock_user_client.get_branch_sha.assert_called_once_with("acme", "repo", "main")
        mock_user_client.create_branch.assert_called_once_with(
            "acme", "repo", "canon/edit-test", "base_sha_abc"
        )
        mock_user_client.create_or_update_file.assert_called_once()
        mock_user_client.create_pull_request.assert_called_once_with(
            "acme",
            "repo",
            "Update auth spec",
            "Added new requirements.",
            "canon/edit-test",
            "main",
        )

        # Verify analytics
        mock_analytics.track.assert_called_once()
        props = mock_analytics.track.call_args[1]["properties"]
        assert props["method"] == "pr"
        assert props["pr_number"] == 99

    @pytest.mark.asyncio
    async def test_save_pr_uses_defaults_when_fields_empty(self, client):
        """Save-PR generates default branch name, title, and body when not provided."""
        mock_user_client = AsyncMock()
        mock_user_client.get_repo = AsyncMock(return_value={"default_branch": "main"})
        mock_user_client.get_branch_sha = AsyncMock(return_value="sha1")
        mock_user_client.create_branch = AsyncMock(return_value={})
        mock_user_client.create_or_update_file = AsyncMock(
            return_value={"content": {"sha": "sha2"}}
        )
        mock_user_client.create_pull_request = AsyncMock(
            return_value={"number": 50, "html_url": "https://github.com/acme/repo/pull/50"}
        )
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
            patch("canon.web.editor_routes.analytics"),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save-pr",
                json={"content": "# Spec", "sha": "abc"},
            )

        assert resp.status_code == 200

        # Verify defaults were used
        create_branch_call = mock_user_client.create_branch.call_args[0]
        assert create_branch_call[2].startswith("canon/edit-")  # branch name

        create_pr_call = mock_user_client.create_pull_request.call_args[0]
        assert create_pr_call[2] == "docs: update docs/specs/test.md"  # pr_title default
        assert create_pr_call[3] == "Spec update via Canon editor."  # pr_body default

    @pytest.mark.asyncio
    async def test_save_pr_returns_500_on_error(self, client):
        """Save-PR returns 500 when GitHub API fails."""
        mock_user_client = AsyncMock()
        mock_user_client.get_repo = AsyncMock(side_effect=Exception("API down"))
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/docs/specs/test.md/save-pr",
                json={"content": "# Spec", "sha": "abc"},
            )

        assert resp.status_code == 500
        assert "API down" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_save_pr_rejects_invalid_path(self, client):
        """Save-PR rejects non-.md file paths."""
        with patch(
            "canon.web.editor_routes._get_github_user",
            return_value=MOCK_GITHUB_USER,
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/src/main.py/save-pr",
                json={"content": "test", "sha": "abc"},
            )
        assert resp.status_code == 400


class TestEditorFileJsonApi:
    """Tests for the file JSON API endpoint."""

    @pytest.mark.asyncio
    async def test_file_json_returns_content(self, client):
        """Returns file content and SHA on success."""
        mock_user_client = AsyncMock()
        mock_user_client.get_file = AsyncMock(return_value=("# My Spec\n", "sha123"))
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
        ):
            resp = await client.get("/app/TestOrg/editor/acme/repo/docs/specs/test.md/json")

        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "# My Spec\n"
        assert data["sha"] == "sha123"

    @pytest.mark.asyncio
    async def test_file_json_returns_404_when_not_found(self, client):
        """Returns 404 when file doesn't exist."""
        mock_user_client = AsyncMock()
        mock_user_client.get_file = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found",
                request=httpx.Request("GET", "https://api.github.com/test"),
                response=httpx.Response(404),
            )
        )
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
        ):
            resp = await client.get("/app/TestOrg/editor/acme/repo/docs/specs/missing.md/json")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_file_json_returns_403_on_permission_denied(self, client):
        """Returns 403 when user lacks access."""
        mock_user_client = AsyncMock()
        mock_user_client.get_file = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "403 Forbidden",
                request=httpx.Request("GET", "https://api.github.com/test"),
                response=httpx.Response(403),
            )
        )
        mock_user_client.close = AsyncMock()

        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes._user_client",
                return_value=mock_user_client,
            ),
        ):
            resp = await client.get("/app/TestOrg/editor/acme/repo/docs/specs/private.md/json")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_file_json_rejects_invalid_path(self, client):
        """Rejects paths that don't end in .md."""
        with patch(
            "canon.web.editor_routes._get_github_user",
            return_value=MOCK_GITHUB_USER,
        ):
            resp = await client.get("/app/TestOrg/editor/acme/repo/src/main.py/json")

        assert resp.status_code == 400


class TestEditorPreviewAuthenticated:
    """Tests for the preview endpoint with authentication."""

    @pytest.mark.asyncio
    async def test_preview_returns_json_for_json_accept(self, client):
        """Preview returns JSON when Accept: application/json."""
        with patch(
            "canon.web.editor_routes._get_github_user",
            return_value=MOCK_GITHUB_USER,
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/preview",
                json={"content": SAMPLE_SPEC},
                headers={"Accept": "application/json"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "html" in data
        # The rendered HTML contains section content (not frontmatter title directly)
        assert "User Authentication" in data["html"]

    @pytest.mark.asyncio
    async def test_preview_handles_parse_failure(self, client):
        """Preview returns error HTML when parsing fails."""
        with (
            patch(
                "canon.web.editor_routes._get_github_user",
                return_value=MOCK_GITHUB_USER,
            ),
            patch(
                "canon.web.editor_routes.parse_spec",
                side_effect=Exception("parse error"),
            ),
        ):
            resp = await client.post(
                "/app/TestOrg/editor/acme/repo/preview",
                json={"content": "bad content"},
                headers={"Accept": "application/json"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "Failed to parse" in data["html"]


class TestFilePathValidationExtended:
    """Additional file path validation tests."""

    def test_accepts_canon_yaml(self):
        """CANON.yaml is allowed as a special case."""
        assert _validate_file_path("CANON.yaml") is True

    def test_accepts_specwright_yaml_legacy(self):
        """SPECWRIGHT.yaml is allowed for backwards compatibility."""
        assert _validate_file_path("SPECWRIGHT.yaml") is True

    def test_rejects_other_yaml(self):
        """Other YAML files are not allowed."""
        assert _validate_file_path("config.yaml") is False
        assert _validate_file_path("docs/config.yml") is False

    def test_rejects_hidden_files(self):
        """Files in hidden directories are rejected (non-.md)."""
        assert _validate_file_path(".github/workflows/test.yml") is False

    def test_accepts_root_md(self):
        """Markdown files at the root are allowed."""
        assert _validate_file_path("README.md") is True
