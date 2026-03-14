"""Tests for MCP server tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from canon.mcp.deps import McpDeps
from canon.mcp.server import create_mcp_server
from canon.search.index import SearchResult


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


def _sample_search_results() -> list[SearchResult]:
    return [
        SearchResult(
            section_id=1,
            document_id=10,
            repo="org/repo",
            path="docs/specs/auth.md",
            doc_title="Authentication Spec",
            heading="Login Flow",
            body="Users can log in with email and password. " * 20,
            status="in_progress",
            rrf_score=0.0325,
        ),
        SearchResult(
            section_id=2,
            document_id=10,
            repo="org/repo",
            path="docs/specs/auth.md",
            doc_title="Authentication Spec",
            heading="OAuth Integration",
            body="Support for Google and GitHub OAuth.",
            status="draft",
            rrf_score=0.0198,
        ),
    ]


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
"""


class TestSearch:
    async def test_returns_results(self):
        index = AsyncMock()
        index.hybrid_search = AsyncMock(return_value=_sample_search_results())
        embed = MagicMock()
        embed.is_available = True
        embed.embed_query = MagicMock(return_value=[0.1] * 10)

        deps = _make_deps(search_index=index, embed_client=embed)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "search")
        ctx = _mock_context(deps)

        result = await fn("login flow", ctx=ctx)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["heading"] == "Login Flow"
        assert result[0]["repo"] == "org/repo"
        assert result[0]["score"] == 0.0325

        # Verify embedding was called
        embed.embed_query.assert_called_once_with("login flow")
        index.hybrid_search.assert_called_once()

    async def test_truncates_body(self):
        long_body = "x" * 1000
        index = AsyncMock()
        index.hybrid_search = AsyncMock(
            return_value=[
                SearchResult(
                    section_id=1,
                    document_id=1,
                    repo="org/repo",
                    path="docs/specs/a.md",
                    doc_title="A",
                    heading="H",
                    body=long_body,
                    status="draft",
                    rrf_score=0.5,
                )
            ]
        )
        deps = _make_deps(search_index=index)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "search")
        ctx = _mock_context(deps)

        result = await fn("test", ctx=ctx)
        assert len(result[0]["body"]) == 500

    async def test_without_embedding(self):
        index = AsyncMock()
        index.hybrid_search = AsyncMock(return_value=[])

        deps = _make_deps(search_index=index, embed_client=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "search")
        ctx = _mock_context(deps)

        result = await fn("test", ctx=ctx)
        assert result == []

        # Should call with query_embedding=None
        call_kwargs = index.hybrid_search.call_args.kwargs
        assert call_kwargs["query_embedding"] is None

    async def test_with_filters(self):
        index = AsyncMock()
        index.hybrid_search = AsyncMock(return_value=[])
        deps = _make_deps(search_index=index)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "search")
        ctx = _mock_context(deps)

        await fn("test", repo="org/repo", status="draft", limit=5, ctx=ctx)

        call_kwargs = index.hybrid_search.call_args.kwargs
        assert call_kwargs["repo"] == "org/repo"
        assert call_kwargs["status"] == "draft"
        assert call_kwargs["limit"] == 5

    async def test_no_search_index(self):
        deps = _make_deps(search_index=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "search")
        ctx = _mock_context(deps)

        result = await fn("test", ctx=ctx)
        assert result == {"error": "Search index not available"}


class TestGetSpec:
    async def test_returns_parsed_spec(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))
        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_spec")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "docs/specs/auth.md", ctx=ctx)

        assert result["file_path"] == "docs/specs/auth.md"
        assert result["frontmatter"]["title"] == "Auth Spec"
        assert result["frontmatter"]["status"] == "in_progress"
        assert result["frontmatter"]["owner"] == "alice"
        assert result["frontmatter"]["tags"] == ["auth", "security"]
        assert result["frontmatter"]["doc_type"] == "spec"
        assert result["frontmatter"]["depends_on"] == []
        assert "review_status" not in result["frontmatter"]  # omitted when absent
        assert "supersedes" not in result["frontmatter"]  # omitted when absent
        assert len(result["sections"]) == 2
        assert result["sections"][0]["title"] == "Login Flow"

    async def test_sections_have_children(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))
        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_spec")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "docs/specs/auth.md", ctx=ctx)

        login_section = result["sections"][0]
        assert len(login_section["children"]) == 1
        assert login_section["children"][0]["title"] == "Password Reset"
        assert login_section["children"][0]["status"] == "todo"

    async def test_file_not_found(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(side_effect=Exception("404"))
        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_spec")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "missing.md", ctx=ctx)
        assert "error" in result

    async def test_no_github_client(self):
        deps = _make_deps(github_client=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_spec")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "docs/specs/auth.md", ctx=ctx)
        assert result == {"error": "GitHub client not available"}


class TestGetSection:
    async def test_finds_section_by_id(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))
        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_section")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "docs/specs/auth.md", "2-oauth", ctx=ctx)

        assert result["title"] == "OAuth"
        assert result["content"]  # has content
        assert result["ticket_link"]["system"] == "github"
        assert result["ticket_link"]["ticket_id"] == "ORG-123"

    async def test_finds_nested_child(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))
        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_section")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "docs/specs/auth.md", "1.1-password-reset", ctx=ctx)

        assert result["title"] == "Password Reset"
        assert result["status"] == "todo"

    async def test_section_not_found(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))
        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_section")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "docs/specs/auth.md", "nonexistent", ctx=ctx)
        assert "error" in result

    async def test_no_github_client(self):
        deps = _make_deps(github_client=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_section")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "f.md", "id", ctx=ctx)
        assert result == {"error": "GitHub client not available"}


class TestGetDoc:
    async def test_returns_raw_markdown(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(
            return_value=("# Hello World\n\nSome content.", "sha456")
        )
        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_doc")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "README.md", ctx=ctx)

        assert result["owner"] == "org"
        assert result["repo"] == "repo"
        assert result["path"] == "README.md"
        assert result["content"] == "# Hello World\n\nSome content."

    async def test_file_not_found(self):
        client = AsyncMock()
        client.get_file_content = AsyncMock(side_effect=Exception("404"))
        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_doc")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "missing.md", ctx=ctx)
        assert "error" in result

    async def test_no_github_client(self):
        deps = _make_deps(github_client=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_doc")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", "f.md", ctx=ctx)
        assert result == {"error": "GitHub client not available"}


class TestListSpecs:
    async def test_lists_specs(self):
        client = AsyncMock()
        # Mock list_directory to return spec file entries
        client.list_directory = AsyncMock(
            return_value=[
                {"type": "file", "name": "auth.md", "path": "docs/specs/auth.md"},
            ]
        )
        client.get_file_content = AsyncMock(return_value=(SAMPLE_SPEC_MD, "sha123"))

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "list_specs")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", ctx=ctx)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["file_path"] == "docs/specs/auth.md"
        assert result[0]["title"] == "Auth Spec"
        assert result[0]["status"] == "in_progress"
        assert result[0]["section_count"] == 2

    async def test_empty_repo(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(return_value=[])

        deps = _make_deps(github_client=client)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "list_specs")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", ctx=ctx)
        assert result == []

    async def test_no_github_client(self):
        deps = _make_deps(github_client=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "list_specs")
        ctx = _mock_context(deps)

        result = await fn("org", "repo", ctx=ctx)
        assert result == {"error": "GitHub client not available"}


class TestListDocs:
    async def test_returns_indexed_paths(self):
        index = AsyncMock()
        index.get_indexed_paths = AsyncMock(
            return_value={
                "org/repo/docs/specs/auth.md": {
                    "indexed_at": "2026-02-18T10:00:00",
                    "has_embedding": True,
                },
                "org/repo/docs/rfcs/001.md": {
                    "indexed_at": "2026-02-17T09:00:00",
                    "has_embedding": False,
                },
            }
        )
        deps = _make_deps(search_index=index)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "list_docs")
        ctx = _mock_context(deps)

        result = await fn(ctx=ctx)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["key"] == "org/repo/docs/specs/auth.md"
        assert result[0]["has_embedding"] is True

    async def test_repo_filter(self):
        index = AsyncMock()
        index.get_indexed_paths = AsyncMock(return_value={})
        deps = _make_deps(search_index=index)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "list_docs")
        ctx = _mock_context(deps)

        await fn(repo="org/repo", ctx=ctx)
        index.get_indexed_paths.assert_called_once_with(repo="org/repo")

    async def test_no_search_index(self):
        deps = _make_deps(search_index=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "list_docs")
        ctx = _mock_context(deps)

        result = await fn(ctx=ctx)
        assert result == {"error": "Search index not available"}


class TestGetCoverage:
    async def test_returns_coverage_data(self):
        agent_store = AsyncMock()
        agent_store.get_coverage_summary = AsyncMock(
            return_value={
                "total_specs": 2,
                "total_sections": 10,
                "done_sections": 6,
                "total_ac": 20,
                "done_ac": 14,
                "realized_ac": 8,
            }
        )
        agent_store.get_coverage_trend = AsyncMock(return_value=[])

        settings = MagicMock()
        settings.web_org = "test-org"

        deps = _make_deps(agent_store=agent_store, settings=settings)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_coverage")
        ctx = _mock_context(deps)

        result = await fn(ctx=ctx)

        assert "summary" in result
        assert result["summary"]["total_specs"] == 2
        assert result["summary"]["realized_ac"] == 8

    async def test_no_deps_available(self):
        deps = _make_deps(github_client=None, agent_store=None)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_coverage")
        ctx = _mock_context(deps)

        result = await fn(ctx=ctx)
        assert "error" in result

    async def test_with_filters(self):
        agent_store = AsyncMock()
        agent_store.get_coverage_summary = AsyncMock(
            return_value={
                "total_specs": 1,
                "total_sections": 5,
                "done_sections": 3,
                "total_ac": 10,
                "done_ac": 7,
                "realized_ac": 4,
            }
        )
        agent_store.get_coverage_trend = AsyncMock(return_value=[])

        settings = MagicMock()
        settings.web_org = "test-org"

        deps = _make_deps(agent_store=agent_store, settings=settings)
        mcp = create_mcp_server(deps)
        fn = _get_tool_fn(mcp, "get_coverage")
        ctx = _mock_context(deps)

        result = await fn(repo="org/repo", team="payments", days=90, ctx=ctx)

        assert "summary" in result
        agent_store.get_coverage_summary.assert_called_once()


class TestSectionToDict:
    def test_includes_scenarios_and_delta(self):
        """_section_to_dict should include scenarios and delta when present."""
        from canon.mcp.server import _section_to_dict
        from canon.parser.models import (
            Scenario,
            ScenarioStep,
            SectionStatus,
            SpecSection,
        )

        section = SpecSection(
            id="1-feature",
            section_number="1",
            title="Feature",
            depth=2,
            content="Content.",
            status=SectionStatus(state="in_progress"),
            delta="added",
            scenarios=[
                Scenario(
                    name="Happy path",
                    steps=[
                        ScenarioStep(keyword="GIVEN", text="valid input", line=5),
                        ScenarioStep(
                            keyword="THEN", text="output MUST be correct", strength="MUST", line=7
                        ),
                    ],
                    start_line=4,
                    end_line=7,
                )
            ],
            children=[],
            start_line=1,
            end_line=10,
        )

        d = _section_to_dict(section)

        assert d["delta"] == "added"
        assert len(d["scenarios"]) == 1
        assert d["scenarios"][0]["name"] == "Happy path"
        assert len(d["scenarios"][0]["steps"]) == 2
        assert d["scenarios"][0]["steps"][0]["keyword"] == "GIVEN"
        assert "strength" not in d["scenarios"][0]["steps"][0]  # omitted when absent
        assert d["scenarios"][0]["steps"][1]["strength"] == "MUST"

    def test_omits_scenarios_and_delta_when_absent(self):
        """_section_to_dict should not include scenarios/delta keys when empty."""
        from canon.mcp.server import _section_to_dict
        from canon.parser.models import SectionStatus, SpecSection

        section = SpecSection(
            id="1-feature",
            section_number="1",
            title="Feature",
            depth=2,
            content="Content.",
            status=SectionStatus(state="draft"),
            children=[],
            start_line=1,
            end_line=5,
        )

        d = _section_to_dict(section)

        assert "delta" not in d
        assert "scenarios" not in d


class TestServerCreation:
    def test_creates_server_with_11_tools(self):
        deps = _make_deps()
        mcp = create_mcp_server(deps)
        tools = mcp._tool_manager._tools
        assert len(tools) == 11
        assert set(tools.keys()) == {
            "search",
            "get_spec",
            "get_section",
            "get_doc",
            "list_specs",
            "list_docs",
            "get_coverage",
            "create_spec",
            "update_section_status",
            "add_realization",
            "sync_spec_status",
        }

    def test_server_has_name_and_instructions(self):
        deps = _make_deps()
        mcp = create_mcp_server(deps)
        assert mcp.name == "Canon"
        assert "spec documents" in mcp.instructions
