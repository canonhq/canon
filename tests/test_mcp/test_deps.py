"""Unit tests for canon.mcp.deps — McpDeps dataclass."""

from __future__ import annotations

from unittest.mock import MagicMock, sentinel

from canon.mcp.deps import McpDeps


class TestMcpDepsDefaults:
    """All fields default to None."""

    def test_all_fields_default_to_none(self):
        deps = McpDeps()
        assert deps.search_index is None
        assert deps.search_backend is None
        assert deps.embed_client is None
        assert deps.github_client is None
        assert deps.cache is None
        assert deps.settings is None
        assert deps.agent_store is None
        assert deps.session_evidence_store is None
        assert deps.content_cache_store is None


class TestMcpDepsConstruction:
    """Fields can be populated via constructor kwargs."""

    def test_partial_construction(self):
        mock_index = MagicMock()
        deps = McpDeps(search_index=mock_index)
        assert deps.search_index is mock_index
        assert deps.github_client is None

    def test_full_construction(self):
        values = {
            "search_index": sentinel.search_index,
            "search_backend": sentinel.search_backend,
            "embed_client": sentinel.embed_client,
            "github_client": sentinel.github_client,
            "cache": sentinel.cache,
            "settings": sentinel.settings,
            "agent_store": sentinel.agent_store,
            "session_evidence_store": sentinel.session_evidence_store,
            "content_cache_store": sentinel.content_cache_store,
        }
        deps = McpDeps(**values)
        for field_name, expected in values.items():
            assert getattr(deps, field_name) is expected


class TestMcpDepsMutation:
    """Dataclass fields are mutable (not frozen)."""

    def test_field_can_be_reassigned(self):
        deps = McpDeps()
        mock_client = MagicMock()
        deps.github_client = mock_client
        assert deps.github_client is mock_client

    def test_multiple_fields_reassigned(self):
        deps = McpDeps()
        deps.search_index = sentinel.idx
        deps.settings = sentinel.cfg
        assert deps.search_index is sentinel.idx
        assert deps.settings is sentinel.cfg


class TestMcpDepsEquality:
    """Dataclass equality (auto-generated __eq__)."""

    def test_equal_instances(self):
        a = McpDeps()
        b = McpDeps()
        assert a == b

    def test_unequal_instances(self):
        a = McpDeps(cache=sentinel.a)
        b = McpDeps(cache=sentinel.b)
        assert a != b

    def test_equal_with_same_values(self):
        obj = MagicMock()
        a = McpDeps(github_client=obj)
        b = McpDeps(github_client=obj)
        assert a == b
