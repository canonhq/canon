"""Tests for MCP server write tools (create_spec, update_section_status, add_realization, sync_spec_status)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from canon.mcp.deps import McpDeps
from canon.mcp.server import create_mcp_server


def _make_deps(
    *,
    search_index=None,
    embed_client=None,
    github_client=None,
    cache=None,
    settings=None,
    agent_store=None,
) -> McpDeps:
    return McpDeps(
        search_index=search_index,
        embed_client=embed_client,
        github_client=github_client,
        cache=cache,
        settings=settings,
        agent_store=agent_store,
    )


def _get_tool_fn(mcp_server, tool_name: str):
    """Get the underlying function for a named tool."""
    tool = mcp_server._tool_manager._tools[tool_name]
    return tool.fn


def _mock_context(deps: McpDeps):
    """Create a mock MCP context that provides deps via lifespan_context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"deps": deps}
    return ctx


SAMPLE_SPEC_MD = """\
---
title: Auth Spec
status: in_progress
owner: alice
team: platform
tags: [auth, security]
---

## 1. Login Flow

Users authenticate via email/password.

### 1.1 Password Reset

<!-- specwright:system:1.1 status:todo -->

Users can reset passwords via email.

### Acceptance Criteria

- [x] Email validation
- [ ] Rate limiting

## 2. OAuth

<!-- specwright:ticket:github:ORG-123 -->

Support for external OAuth providers.

### Acceptance Criteria

- [ ] Google OAuth support
- [ ] GitHub OAuth support
"""

SPEC_NO_STATUS = """\
---
title: Simple Spec
status: draft
owner: bob
team: backend
tags: []
---

## 1. Feature

Some description.

### Acceptance Criteria

- [ ] First requirement
"""


class TestCreateSpec:
    async def test_creates_spec_from_template(self):
        client = AsyncMock()
        client.create_or_update_file = AsyncMock(return_value={"content": {"sha": "newsha123"}})

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "create_spec")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "User Authentication", ctx=ctx)

        assert result["path"] == "docs/specs/user-authentication.md"
        assert result["sha"] == "newsha123"
        assert "Created spec" in result["message"]

        # Verify create_or_update_file was called without sha (new file)
        call_kwargs = client.create_or_update_file.call_args
        assert call_kwargs[0][3]  # content is non-empty
        assert "User Authentication" in call_kwargs[0][3]

    async def test_creates_spec_with_custom_filename(self):
        client = AsyncMock()
        client.create_or_update_file = AsyncMock(return_value={"content": {"sha": "abc"}})

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "create_spec")
        ctx = _mock_context(deps)

        result = await fn(
            "org",
            "repo",
            "Auth Feature",
            file_name="auth-v2",
            team="platform",
            owner_name="alice",
            tags=["auth"],
            ctx=ctx,
        )

        assert result["path"] == "docs/specs/auth-v2.md"

    async def test_invalid_doc_type(self):
        client = AsyncMock()
        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "create_spec")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "Test", doc_type="invalid", ctx=ctx)
        assert "error" in result

    async def test_no_github_client(self):
        deps = _make_deps(github_client=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "create_spec")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "Test", ctx=ctx)
        assert result == {"error": "GitHub client not available"}


class TestUpdateSectionStatus:
    async def test_updates_existing_status(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))
        client.create_or_update_file = AsyncMock(return_value={})

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "update_section_status")
        ctx = _mock_context(deps)

        result = await fn(
            "org",
            "repo",
            "docs/specs/auth.md",
            "1.1-password-reset",
            "in_progress",
            ctx=ctx,
        )

        assert result["new_state"] == "in_progress"
        assert "Updated" in result["message"]

        # Verify the committed content has the updated status
        committed = client.create_or_update_file.call_args[0][3]
        assert "status:in_progress" in committed

    async def test_inserts_status_when_missing(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SPEC_NO_STATUS, "sha456"))
        client.create_or_update_file = AsyncMock(return_value={})

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "update_section_status")
        ctx = _mock_context(deps)

        result = await fn(
            "org",
            "repo",
            "docs/specs/simple.md",
            "1-feature",
            "in_progress",
            ctx=ctx,
        )

        assert result["new_state"] == "in_progress"
        committed = client.create_or_update_file.call_args[0][3]
        assert "canon:system:1 status:in_progress" in committed

    async def test_section_not_found(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "update_section_status")
        ctx = _mock_context(deps)

        result = await fn(
            "org",
            "repo",
            "docs/specs/auth.md",
            "nonexistent",
            "done",
            ctx=ctx,
        )
        assert "error" in result

    async def test_file_not_found(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(side_effect=Exception("404"))

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "update_section_status")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "missing.md", "id", "done", ctx=ctx)
        assert "error" in result

    async def test_no_github_client(self):
        deps = _make_deps(github_client=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "update_section_status")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "f.md", "id", "done", ctx=ctx)
        assert result == {"error": "GitHub client not available"}


class TestAddRealization:
    async def test_adds_realization(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))
        client.create_or_update_file = AsyncMock(return_value={})

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "add_realization")
        ctx = _mock_context(deps)

        result = await fn(
            "org",
            "repo",
            "docs/specs/auth.md",
            "1.1-password-reset",
            "Rate limiting",
            42,
            "src/auth/rate_limit.py",
            "10-25",
            ctx=ctx,
        )

        assert result["pr_number"] == 42
        assert "realization" in result["message"].lower()

        committed = client.create_or_update_file.call_args[0][3]
        assert "canon:realized-in:PR#42" in committed
        assert "rate_limit.py:10-25" in committed

    async def test_ac_not_found(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "add_realization")
        ctx = _mock_context(deps)

        result = await fn(
            "org",
            "repo",
            "docs/specs/auth.md",
            "1.1-password-reset",
            "Nonexistent AC text",
            42,
            "src/foo.py",
            ctx=ctx,
        )
        assert "error" in result

    async def test_section_not_found(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "add_realization")
        ctx = _mock_context(deps)

        result = await fn(
            "org",
            "repo",
            "docs/specs/auth.md",
            "nonexistent",
            "Some AC",
            42,
            "f.py",
            ctx=ctx,
        )
        assert "error" in result

    async def test_no_github_client(self):
        deps = _make_deps(github_client=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "add_realization")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "f.md", "id", "ac", 1, "f.py", ctx=ctx)
        assert result == {"error": "GitHub client not available"}


class TestSyncSpecStatus:
    async def test_bulk_status_update(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))
        client.create_or_update_file = AsyncMock(return_value={})

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "sync_spec_status")
        ctx = _mock_context(deps)

        result = await fn(
            "org",
            "repo",
            "docs/specs/auth.md",
            status_updates=[
                {"section_number": "1.1", "new_state": "done"},
            ],
            commit_message="chore: mark password reset done",
            ctx=ctx,
        )

        assert "Synced" in result["message"]
        committed = client.create_or_update_file.call_args[0][3]
        assert "status:done" in committed

    async def test_bulk_with_realizations(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))
        client.create_or_update_file = AsyncMock(return_value={})

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "sync_spec_status")
        ctx = _mock_context(deps)

        result = await fn(
            "org",
            "repo",
            "docs/specs/auth.md",
            realizations=[
                {
                    "ac_text": "Rate limiting",
                    "pr_number": 55,
                    "code_file": "src/auth.py",
                    "lines": "1-10",
                },
            ],
            ctx=ctx,
        )

        assert "Synced" in result["message"]

    async def test_no_updates_provided(self):
        client = AsyncMock()
        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "sync_spec_status")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "f.md", ctx=ctx)
        assert "error" in result

    async def test_no_github_client(self):
        deps = _make_deps(github_client=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "sync_spec_status")
        ctx = _mock_context(deps)

        result = await fn(
            "org",
            "repo",
            "f.md",
            status_updates=[{"section_number": "1", "new_state": "done"}],
            ctx=ctx,
        )
        assert result == {"error": "GitHub client not available"}
