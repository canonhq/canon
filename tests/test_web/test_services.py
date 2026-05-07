"""Tests for web services (data access layer)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from canon.parser.models import (
    AcceptanceCriterion,
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
)
from canon.web.cache import TTLCache
from canon.web.models import CoverageApiResponse, FacetCounts
from canon.web.services import (
    _classify_doc_type,
    _highlight_terms,
    _list_indexed_docs,
    _summarize_spec,
    compute_coverage_summary,
    get_coverage,
    get_doc_detail,
    get_facet_counts,
    get_org_overview,
    get_repo_detail,
    get_spec_detail,
    invalidate_search_cache,
    search_specs,
)


def _make_spec_doc(
    *,
    title: str = "Auth Migration",
    status: str = "in_progress",
    owner: str = "alice",
    team: str = "platform",
    tags: list[str] | None = None,
    sections: list[SpecSection] | None = None,
) -> SpecDocument:
    if sections is None:
        sections = [
            SpecSection(
                id="bg",
                section_number="1",
                title="Background",
                depth=2,
                content="Some context.",
                status=SectionStatus(state="done"),
                acceptance_criteria=[
                    AcceptanceCriterion(text="AC 1", checked=True, line=10),
                    AcceptanceCriterion(text="AC 2", checked=False, line=11),
                ],
                children=[],
                start_line=5,
                end_line=15,
            ),
            SpecSection(
                id="reqs",
                section_number="2",
                title="Requirements",
                depth=2,
                content="The requirements.",
                status=SectionStatus(state="in_progress"),
                children=[
                    SpecSection(
                        id="reqs-api",
                        section_number="2.1",
                        title="API",
                        depth=3,
                        content="API reqs.",
                        status=SectionStatus(state="todo"),
                        children=[],
                        start_line=20,
                        end_line=25,
                    ),
                ],
                start_line=16,
                end_line=30,
            ),
        ]
    return SpecDocument(
        file_path="docs/specs/auth-migration.md",
        frontmatter=SpecFrontmatter(
            title=title,
            status=status,
            owner=owner,
            team=team,
            tags=tags or ["auth", "migration"],
        ),
        sections=sections,
        raw="# Auth Migration\n...",
    )


class TestSummarizeSpec:
    def test_counts_sections(self):
        doc = _make_spec_doc()
        summary = _summarize_spec(doc)
        assert summary.total_sections == 3  # 2 top-level + 1 child
        assert summary.done_sections == 1

    def test_counts_acceptance_criteria(self):
        doc = _make_spec_doc()
        summary = _summarize_spec(doc)
        assert summary.total_ac == 2
        assert summary.done_ac == 1

    def test_metadata(self):
        doc = _make_spec_doc()
        summary = _summarize_spec(doc)
        assert summary.title == "Auth Migration"
        assert summary.status == "in_progress"
        assert summary.owner == "alice"
        assert summary.team == "platform"
        assert summary.tags == ["auth", "migration"]


def _mock_client(repos: list[dict] | None = None) -> AsyncMock:
    client = AsyncMock()
    client.list_installation_repos = AsyncMock(return_value=repos or [])
    client.list_directory = AsyncMock(return_value=[])
    client.get_file_content = AsyncMock(side_effect=Exception("not found"))
    client._get = AsyncMock(side_effect=Exception("not found"))
    return client


class TestGetOrgOverview:
    async def test_empty_org(self):
        client = _mock_client(repos=[])
        cache = TTLCache(ttl_seconds=60)
        result = await get_org_overview(client, "test-org", cache)
        assert result.org == "test-org"
        assert result.total_repos == 0
        assert result.total_specs == 0

    async def test_caches_result(self):
        client = _mock_client(repos=[])
        cache = TTLCache(ttl_seconds=60)

        await get_org_overview(client, "test-org", cache)
        # Second call should use cache
        await get_org_overview(client, "test-org", cache)

        assert client.list_installation_repos.call_count == 1

    async def test_repo_without_specs(self):
        repos = [
            {
                "owner": {"login": "org"},
                "name": "repo1",
                "full_name": "org/repo1",
                "description": "A test repo",
                "default_branch": "main",
            }
        ]
        client = _mock_client(repos=repos)
        cache = TTLCache(ttl_seconds=60)
        result = await get_org_overview(client, "org", cache)
        assert len(result.repos_without_specs) == 1
        assert result.repos_without_specs[0].full_name == "org/repo1"

    async def test_populates_broken_refs_count_when_ref_store_provided(self):
        client = _mock_client(
            repos=[
                {
                    "owner": {"login": "o"},
                    "name": "r1",
                    "full_name": "o/r1",
                    "description": "",
                    "default_branch": "main",
                },
                {
                    "owner": {"login": "o"},
                    "name": "r2",
                    "full_name": "o/r2",
                    "description": "",
                    "default_branch": "main",
                },
            ]
        )
        cache = TTLCache(ttl_seconds=300)
        ref_store = AsyncMock()
        ref_store.list_broken = AsyncMock(
            return_value=[
                {
                    "installation_id": 1,
                    "system": "github",
                    "ticket_ref": "o/r1#1",
                    "status": "broken",
                    "consecutive_failures": 3,
                    "last_error_kind": "not_found",
                    "first_failure_at": None,
                    "last_check_at": None,
                },
                {
                    "installation_id": 1,
                    "system": "github",
                    "ticket_ref": "o/r1#2",
                    "status": "broken",
                    "consecutive_failures": 3,
                    "last_error_kind": "not_found",
                    "first_failure_at": None,
                    "last_check_at": None,
                },
            ]
        )
        overview = await get_org_overview(
            client,
            "o",
            cache,
            ref_store=ref_store,
            installation_id=1,
        )
        assert overview.total_broken_refs == 2
        repo_counts = {
            r.full_name: r.broken_refs_count
            for r in overview.repos_with_specs + overview.repos_without_specs
        }
        assert repo_counts.get("o/r1") == 2
        assert repo_counts.get("o/r2", 0) == 0

    async def test_zero_broken_refs_when_ref_store_omitted(self):
        client = _mock_client()
        cache = TTLCache(ttl_seconds=300)
        overview = await get_org_overview(client, "o", cache)
        assert overview.total_broken_refs == 0


class TestGetRepoDetail:
    async def test_repo_not_found(self):
        client = _mock_client()
        cache = TTLCache(ttl_seconds=60)
        result = await get_repo_detail(client, "org", "nonexistent", cache)
        assert result is None

    async def test_repo_found(self):
        client = AsyncMock()
        client._get = AsyncMock(
            return_value={
                "full_name": "org/repo1",
                "description": "Test",
                "default_branch": "main",
            }
        )
        client.list_directory = AsyncMock(return_value=[])
        client.get_file_content = AsyncMock(side_effect=Exception("not found"))
        cache = TTLCache(ttl_seconds=60)

        result = await get_repo_detail(client, "org", "repo1", cache)
        assert result is not None
        assert result.full_name == "org/repo1"


class TestGetSpecDetail:
    async def test_spec_not_found(self):
        client = _mock_client()
        cache = TTLCache(ttl_seconds=60)
        result = await get_spec_detail(client, "org", "repo", "docs/specs/nope.md", cache)
        assert result is None

    async def test_populates_broken_sections_when_ref_store_provided(self):
        from datetime import UTC, datetime

        spec_md = """---
title: Test
status: in_progress
---

# Test

## 1. Has broken ticket

<!-- canon:system:1 status:in_progress -->
<!-- canon:ticket:github:456 url:https://github.com/o/r/issues/456 -->

Body

## 2. Has working ticket

<!-- canon:system:2 status:in_progress -->
<!-- canon:ticket:github:789 url:https://github.com/o/r/issues/789 -->

Body
"""
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(spec_md, "sha"))
        cache = TTLCache(ttl_seconds=300)

        ref_store = AsyncMock()
        ref_store.list_broken = AsyncMock(
            return_value=[
                {
                    "installation_id": 1,
                    "system": "github",
                    "ticket_ref": "o/r#456",
                    "status": "broken",
                    "consecutive_failures": 3,
                    "last_error_kind": "not_found",
                    "last_error_message": "not found",
                    "first_failure_at": datetime.now(UTC),
                    "last_check_at": datetime.now(UTC),
                    "last_recheck_at": None,
                    "dismissed_at": None,
                    "dismissed_by": None,
                },
            ]
        )

        detail = await get_spec_detail(
            client,
            "o",
            "r",
            "docs/specs/test.md",
            cache,
            ref_store=ref_store,
            installation_id=1,
        )
        assert detail is not None
        assert len(detail.broken_sections) == 1
        assert detail.broken_sections[0].ticket_ref == "o/r#456"
        assert detail.broken_sections[0].error_kind == "not_found"


class TestIndexedStatus:
    async def test_is_indexed_populated_when_search_index_provided(self):
        """Specs matching indexed paths should have is_indexed=True."""
        from unittest.mock import AsyncMock as AM

        repos = [
            {
                "owner": {"login": "org"},
                "name": "repo1",
                "full_name": "org/repo1",
                "description": "",
                "default_branch": "main",
            }
        ]
        client = _mock_client(repos=repos)

        # Make load_repo_specs return a spec
        import canon.web.services as svc

        doc = _make_spec_doc()
        original_load = svc.load_repo_specs

        async def mock_load(*args, **kwargs):
            return [{"document": doc}]

        svc.load_repo_specs = mock_load

        # Mock search index
        mock_index = AM()
        mock_index.get_indexed_paths = AM(
            return_value={
                "org/repo1/docs/specs/auth-migration.md": {
                    "indexed_at": "2026-02-13",
                    "has_embedding": True,
                }
            }
        )

        cache = TTLCache(ttl_seconds=60)
        try:
            result = await get_org_overview(client, "org", cache, search_index=mock_index)
            assert len(result.repos_with_specs) == 1
            spec = result.repos_with_specs[0].specs[0]
            assert spec.is_indexed is True
        finally:
            svc.load_repo_specs = original_load

    async def test_is_indexed_false_without_search_index(self):
        """Without search_index, is_indexed should default to False."""
        repos = [
            {
                "owner": {"login": "org"},
                "name": "repo1",
                "full_name": "org/repo1",
                "description": "",
                "default_branch": "main",
            }
        ]
        client = _mock_client(repos=repos)

        import canon.web.services as svc

        doc = _make_spec_doc()
        original_load = svc.load_repo_specs

        async def mock_load(*args, **kwargs):
            return [{"document": doc}]

        svc.load_repo_specs = mock_load

        cache = TTLCache(ttl_seconds=60)
        try:
            result = await get_org_overview(client, "org", cache)
            spec = result.repos_with_specs[0].specs[0]
            assert spec.is_indexed is False
        finally:
            svc.load_repo_specs = original_load


class TestSearchSpecs:
    async def test_search_empty(self):
        client = _mock_client(repos=[])
        cache = TTLCache(ttl_seconds=60)
        results = await search_specs(client, "org", cache, query="anything")
        assert results == []

    async def test_search_by_title(self):
        repos = [
            {
                "owner": {"login": "org"},
                "name": "repo1",
                "full_name": "org/repo1",
                "description": "",
                "default_branch": "main",
            }
        ]
        client = _mock_client(repos=repos)

        import canon.web.services as svc

        doc = _make_spec_doc(title="Auth Migration")
        original_load = svc.load_repo_specs

        async def mock_load(*args, **kwargs):
            return [{"document": doc}]

        svc.load_repo_specs = mock_load

        cache = TTLCache(ttl_seconds=60)
        try:
            results = await search_specs(client, "org", cache, query="auth")
            assert len(results) == 1
            assert results[0].title == "Auth Migration"
        finally:
            svc.load_repo_specs = original_load

    async def test_search_by_status_filter(self):
        repos = [
            {
                "owner": {"login": "org"},
                "name": "repo1",
                "full_name": "org/repo1",
                "description": "",
                "default_branch": "main",
            }
        ]
        client = _mock_client(repos=repos)

        import canon.web.services as svc

        doc = _make_spec_doc(status="draft")
        original_load = svc.load_repo_specs

        async def mock_load(*args, **kwargs):
            return [{"document": doc}]

        svc.load_repo_specs = mock_load

        cache = TTLCache(ttl_seconds=60)
        try:
            # Matching filter
            results = await search_specs(client, "org", cache, status="draft")
            assert len(results) == 1
            # Non-matching filter
            results = await search_specs(client, "org", cache, status="done")
            assert len(results) == 0
        finally:
            svc.load_repo_specs = original_load

    async def test_search_by_team_filter(self):
        repos = [
            {
                "owner": {"login": "org"},
                "name": "repo1",
                "full_name": "org/repo1",
                "description": "",
                "default_branch": "main",
            }
        ]
        client = _mock_client(repos=repos)

        import canon.web.services as svc

        doc = _make_spec_doc(team="platform")
        original_load = svc.load_repo_specs

        async def mock_load(*args, **kwargs):
            return [{"document": doc}]

        svc.load_repo_specs = mock_load

        cache = TTLCache(ttl_seconds=60)
        try:
            results = await search_specs(client, "org", cache, team="platform")
            assert len(results) == 1
            results = await search_specs(client, "org", cache, team="frontend")
            assert len(results) == 0
        finally:
            svc.load_repo_specs = original_load


class TestHighlightTerms:
    def test_highlights_matching_terms(self):
        result = _highlight_terms("The auth system is working", "auth")
        assert "<mark>auth</mark>" in result

    def test_escapes_html(self):
        result = _highlight_terms("<script>alert('xss')</script>", "")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_empty_query(self):
        result = _highlight_terms("Hello world", "")
        assert result == "Hello world"

    def test_short_terms_ignored(self):
        result = _highlight_terms("Is a test", "a")
        assert "<mark>" not in result

    def test_case_insensitive(self):
        result = _highlight_terms("The AUTH system", "auth")
        assert "<mark>AUTH</mark>" in result


class TestGetFacetCounts:
    async def test_in_memory_fallback(self):
        """Facet counts computed from org overview when no search_index."""
        repos = [
            {
                "owner": {"login": "org"},
                "name": "repo1",
                "full_name": "org/repo1",
                "description": "",
                "default_branch": "main",
            }
        ]
        client = _mock_client(repos=repos)

        import canon.web.services as svc

        doc = _make_spec_doc(status="in_progress")
        original_load = svc.load_repo_specs

        async def mock_load(*args, **kwargs):
            return [{"document": doc}]

        svc.load_repo_specs = mock_load

        cache = TTLCache(ttl_seconds=60)
        try:
            facets = await get_facet_counts(client, "org", cache)
            assert isinstance(facets, FacetCounts)
            assert facets.status.get("in_progress") == 1
            assert facets.repo.get("org/repo1") == 1
        finally:
            svc.load_repo_specs = original_load

    async def test_db_facets(self):
        """Facet counts from search_index when available."""
        from unittest.mock import AsyncMock as AM

        client = _mock_client(repos=[])
        cache = TTLCache(ttl_seconds=60)

        mock_index = AM()
        mock_index.get_facet_counts = AM(
            return_value={
                "status": {"draft": 3, "done": 7},
                "repo": {"org/repo1": 5, "org/repo2": 5},
            }
        )

        facets = await get_facet_counts(client, "org", cache, search_index=mock_index)
        assert facets.status == {"draft": 3, "done": 7}
        assert facets.repo == {"org/repo1": 5, "org/repo2": 5}

    async def test_db_failure_falls_back(self):
        """Falls back to in-memory when DB facet query fails."""
        from unittest.mock import AsyncMock as AM

        repos = [
            {
                "owner": {"login": "org"},
                "name": "repo1",
                "full_name": "org/repo1",
                "description": "",
                "default_branch": "main",
            }
        ]
        client = _mock_client(repos=repos)

        import canon.web.services as svc

        doc = _make_spec_doc(status="done")
        original_load = svc.load_repo_specs

        async def mock_load(*args, **kwargs):
            return [{"document": doc}]

        svc.load_repo_specs = mock_load

        mock_index = AM()
        mock_index.get_facet_counts = AM(side_effect=Exception("DB error"))

        cache = TTLCache(ttl_seconds=60)
        try:
            facets = await get_facet_counts(client, "org", cache, search_index=mock_index)
            assert facets.status.get("done") == 1
        finally:
            svc.load_repo_specs = original_load

    async def test_facet_cache_hit(self):
        """Second call returns cached facet counts."""
        from unittest.mock import AsyncMock as AM

        client = _mock_client(repos=[])
        cache = TTLCache(ttl_seconds=60)

        mock_index = AM()
        mock_index.get_facet_counts = AM(
            return_value={
                "status": {"draft": 2},
                "repo": {"org/repo1": 2},
            }
        )

        # First call hits DB
        await get_facet_counts(client, "org", cache, search_index=mock_index)
        # Second call should use cache
        await get_facet_counts(client, "org", cache, search_index=mock_index)
        assert mock_index.get_facet_counts.call_count == 1


class TestSearchCaching:
    async def test_search_cache_hit(self):
        """Second call with same params returns cached results."""
        from unittest.mock import AsyncMock as AM

        client = _mock_client(repos=[])
        cache = TTLCache(ttl_seconds=60)

        mock_index = AM()
        mock_result = AM()
        mock_result.path = "docs/specs/test.md"
        mock_result.doc_title = "Test"
        mock_result.status = "draft"
        mock_result.repo = "org/repo1"
        mock_result.heading = "Section"
        mock_result.body = "Content here"
        mock_result.rrf_score = 0.5
        mock_index.hybrid_search = AM(return_value=[mock_result])

        # First call
        r1 = await search_specs(
            client,
            "org",
            cache,
            query="test",
            status="draft",
            search_index=mock_index,
        )
        assert len(r1) == 1

        # Second call — should use cache
        r2 = await search_specs(
            client,
            "org",
            cache,
            query="test",
            status="draft",
            search_index=mock_index,
        )
        assert len(r2) == 1
        assert mock_index.hybrid_search.call_count == 1

    async def test_search_cache_invalidation(self):
        """invalidate_search_cache clears search and facet caches."""
        cache = TTLCache(ttl_seconds=60)
        cache.set("search:org:test::::", [])
        cache.set("facets:org:", FacetCounts())
        cache.set("repo:org/repo1", "keep")

        invalidate_search_cache(cache, "org")

        assert cache.get("search:org:test::::") is None
        assert cache.get("facets:org:") is None
        assert cache.get("repo:org/repo1") == "keep"


class TestClassifyDocType:
    def test_spec(self):
        assert _classify_doc_type("docs/specs/auth.md") == "spec"

    def test_adr(self):
        assert _classify_doc_type("docs/adrs/001-use-fastapi.md") == "adr"

    def test_readme(self):
        assert _classify_doc_type("README.md") == "readme"

    def test_changelog(self):
        assert _classify_doc_type("CHANGELOG.md") == "changelog"

    def test_contributing(self):
        assert _classify_doc_type("CONTRIBUTING.md") == "contributing"

    def test_runbook(self):
        assert _classify_doc_type("docs/runbook-deploy.md") == "runbook"

    def test_playbook(self):
        assert _classify_doc_type("docs/playbook-incident.md") == "runbook"

    def test_generic_doc(self):
        assert _classify_doc_type("docs/api-guide.md") == "doc"


class TestListIndexedDocs:
    async def test_uses_indexed_paths(self):
        """When indexed_paths provided, returns docs from index."""
        client = _mock_client()
        indexed_paths = {
            "org/repo1/docs/specs/auth.md": {"indexed_at": "2026-02-13"},
            "org/repo1/README.md": {"indexed_at": "2026-02-13"},
            "org/repo1/docs/adrs/001.md": {"indexed_at": "2026-02-13"},
            "other/repo2/README.md": {"indexed_at": "2026-02-13"},
        }
        docs = await _list_indexed_docs(
            client,
            "org",
            "repo1",
            indexed_paths=indexed_paths,
        )
        # Should have README and ADR, not the spec or other repo
        assert len(docs) == 2
        paths = {d.path for d in docs}
        assert "README.md" in paths
        assert "docs/adrs/001.md" in paths
        assert all(d.is_indexed for d in docs)

    async def test_fallback_to_github_api(self):
        """Without indexed_paths, falls back to GitHub API."""
        client = AsyncMock()

        async def _list_dir(_owner, _repo, path):
            if path == "":
                return [
                    {
                        "name": "README.md",
                        "path": "README.md",
                        "type": "file",
                        "html_url": "https://github.com/org/repo1/blob/main/README.md",
                    },
                ]
            return []

        client.list_directory = AsyncMock(side_effect=_list_dir)
        docs = await _list_indexed_docs(client, "org", "repo1")
        assert len(docs) == 1
        assert docs[0].doc_type == "readme"
        assert not docs[0].is_indexed

    async def test_custom_spec_patterns_filters_indexed(self):
        """With spec_patterns, uses matches_doc_patterns instead of classify_doc_type."""
        client = _mock_client()
        indexed_paths = {
            "org/repo1/design/auth.md": {"indexed_at": "2026-02-13"},
            "org/repo1/README.md": {"indexed_at": "2026-02-13"},
            "org/repo1/docs/specs/old.md": {"indexed_at": "2026-02-13"},
        }
        # Custom patterns: design/*.md are specs, not docs/specs/
        docs = await _list_indexed_docs(
            client,
            "org",
            "repo1",
            indexed_paths=indexed_paths,
            spec_patterns=["design/*.md"],
        )
        # design/auth.md is now a spec (filtered out), docs/specs/old.md is NOT a spec
        paths = {d.path for d in docs}
        assert "design/auth.md" not in paths  # filtered as spec
        assert "README.md" in paths
        assert "docs/specs/old.md" in paths  # not a spec under custom patterns

    async def test_custom_spec_patterns_filters_api_fallback(self):
        """With spec_patterns, API fallback also uses matches_doc_patterns."""
        client = AsyncMock()

        async def _list_dir(_owner, _repo, path):
            if path == "docs":
                return [
                    {
                        "name": "auth.md",
                        "path": "docs/auth.md",
                        "type": "file",
                    },
                    {
                        "name": "overview.md",
                        "path": "docs/specs/overview.md",
                        "type": "file",
                    },
                ]
            return []

        client.list_directory = AsyncMock(side_effect=_list_dir)
        # With custom patterns, docs/specs/ files are NOT specs
        docs = await _list_indexed_docs(client, "org", "repo1", spec_patterns=["design/*.md"])
        paths = {d.path for d in docs}
        assert "docs/auth.md" in paths
        assert "docs/specs/overview.md" in paths  # not a spec under custom patterns

    async def test_empty_index_result_skips_github(self):
        """An empty (but non-None) indexed_paths means the index answered

        authoritatively — return [] without ever hitting GitHub. This is the
        rate-limit-critical branch: every dashboard load passes through here
        once per repo.
        """
        client = AsyncMock()
        client.list_directory = AsyncMock()
        docs = await _list_indexed_docs(
            client,
            "org",
            "repo1",
            search_index=object(),
            indexed_paths={},
        )
        assert docs == []
        client.list_directory.assert_not_called()

    async def test_none_indexed_paths_falls_back_when_index_errored(self):
        """indexed_paths=None signals the index couldn't be queried.

        The caller swallows search-index exceptions and leaves indexed_paths
        as None; we should fall back to GitHub so users still see docs in
        a search-index outage.
        """
        client = AsyncMock()

        async def _list_dir(_owner, _repo, path):
            if path == "":
                return [
                    {
                        "name": "README.md",
                        "path": "README.md",
                        "type": "file",
                    },
                ]
            return []

        client.list_directory = AsyncMock(side_effect=_list_dir)
        docs = await _list_indexed_docs(
            client,
            "org",
            "repo1",
            search_index=object(),
            indexed_paths=None,
        )
        paths = {d.path for d in docs}
        assert "README.md" in paths
        assert client.list_directory.await_count >= 1


class TestGetDocDetail:
    async def test_returns_doc_detail(self):
        """get_doc_detail fetches and renders markdown."""
        client = AsyncMock()
        client.get_file_content = AsyncMock(
            return_value=("# My Guide\n\nSome content here.", "abc123")
        )
        cache = TTLCache(ttl_seconds=60)

        detail = await get_doc_detail(client, "org", "repo1", "docs/guide.md", cache)
        assert detail is not None
        assert detail.title == "My Guide"
        assert detail.doc_type == "doc"
        assert "Some content here" in detail.rendered_html
        assert detail.github_url == "https://github.com/org/repo1/blob/main/docs/guide.md"

    async def test_caches_result(self):
        """Second call uses cache."""
        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=("# Test\n\nBody.", "sha"))
        cache = TTLCache(ttl_seconds=60)

        await get_doc_detail(client, "org", "repo1", "docs/test.md", cache)
        await get_doc_detail(client, "org", "repo1", "docs/test.md", cache)
        assert client.get_file_content.call_count == 1

    async def test_returns_none_on_not_found(self):
        """Returns None when file not found."""
        client = AsyncMock()
        client.get_file_content = AsyncMock(side_effect=Exception("not found"))
        cache = TTLCache(ttl_seconds=60)

        detail = await get_doc_detail(client, "org", "repo1", "nope.md", cache)
        assert detail is None

    async def test_title_from_filename_when_no_heading(self):
        """Uses filename when no heading in content."""
        client = AsyncMock()
        client.get_file_content = AsyncMock(
            return_value=("Just some text without a heading.", "sha")
        )
        cache = TTLCache(ttl_seconds=60)

        detail = await get_doc_detail(client, "org", "repo1", "docs/notes.md", cache)
        assert detail is not None
        assert detail.title == "notes.md"


class TestComputeCoverageSummary:
    def test_basic_percentages(self):
        result = compute_coverage_summary(
            total_specs=3,
            total_sections=10,
            done_sections=5,
            total_ac=20,
            done_ac=10,
            realized_ac=6,
        )
        assert result.section_coverage_pct == 50.0
        assert result.ac_coverage_pct == 50.0
        assert result.realization_rate_pct == 30.0
        # health = 50*0.3 + 50*0.3 + 30*0.4 = 15 + 15 + 12 = 42
        assert result.health_score == 42.0

    def test_zero_totals(self):
        result = compute_coverage_summary()
        assert result.section_coverage_pct == 0.0
        assert result.ac_coverage_pct == 0.0
        assert result.realization_rate_pct == 0.0
        assert result.health_score == 0.0

    def test_full_coverage(self):
        result = compute_coverage_summary(
            total_specs=1,
            total_sections=5,
            done_sections=5,
            total_ac=10,
            done_ac=10,
            realized_ac=10,
        )
        assert result.section_coverage_pct == 100.0
        assert result.ac_coverage_pct == 100.0
        assert result.realization_rate_pct == 100.0
        assert result.health_score == 100.0


class TestGetCoverage:
    async def test_in_memory_fallback(self):
        """When no agent_store, compute from org overview."""
        client = _mock_client(
            repos=[
                {
                    "name": "repo1",
                    "full_name": "org/repo1",
                    "owner": {"login": "org"},
                    "default_branch": "main",
                }
            ]
        )
        client.list_directory = AsyncMock(return_value=[])
        client.get_file_content = AsyncMock(side_effect=Exception("not found"))
        cache = TTLCache(ttl_seconds=60)

        result = await get_coverage(client, "org", cache)

        assert isinstance(result, CoverageApiResponse)
        assert result.summary.realized_ac == 0
        assert result.trend == []

    async def test_db_path(self):
        """When agent_store is available, use DB snapshots."""
        client = _mock_client(repos=[])
        cache = TTLCache(ttl_seconds=60)
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
        agent_store.get_coverage_trend = AsyncMock(
            return_value=[
                {
                    "date": "2026-02-19",
                    "total_sections": 10,
                    "done_sections": 6,
                    "total_ac": 20,
                    "done_ac": 14,
                    "realized_ac": 8,
                }
            ]
        )

        result = await get_coverage(client, "org", cache, agent_store=agent_store)

        assert result.summary.total_specs == 2
        assert result.summary.realized_ac == 8
        assert len(result.trend) == 1

    async def test_caches_result(self):
        """Second call uses cache."""
        client = _mock_client(repos=[])
        cache = TTLCache(ttl_seconds=60)
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

        await get_coverage(client, "org", cache, agent_store=agent_store)
        await get_coverage(client, "org", cache, agent_store=agent_store)

        assert agent_store.get_coverage_summary.call_count == 1

    async def test_db_failure_falls_back(self):
        """When DB query fails, fall back to in-memory."""
        client = _mock_client(repos=[])
        client.list_directory = AsyncMock(return_value=[])
        cache = TTLCache(ttl_seconds=60)
        agent_store = AsyncMock()
        agent_store.get_coverage_summary = AsyncMock(side_effect=Exception("DB error"))

        result = await get_coverage(client, "org", cache, agent_store=agent_store)

        assert isinstance(result, CoverageApiResponse)
        assert result.summary.realized_ac == 0


class TestRemoveTicketRef:
    SPEC_WITH_TICKET = """---
title: Test
status: in_progress
---

# Test

## 1. Has broken ticket

<!-- canon:system:1 status:in_progress -->
<!-- canon:ticket:github:456 url:https://github.com/o/r/issues/456 -->

Body
"""

    SPEC_WITHOUT_TICKET = """---
title: Test
status: in_progress
---

# Test

## 1. No ticket here

<!-- canon:system:1 status:in_progress -->

Body
"""

    async def test_strips_ticket_line_and_opens_pr_with_slug(self):
        from unittest.mock import AsyncMock, MagicMock

        from canon.web.services import RemoveTicketRefResult, remove_ticket_ref

        client = AsyncMock()
        store = AsyncMock()
        store.get_spec_raw = AsyncMock(return_value=self.SPEC_WITH_TICKET)
        client.find_open_doc_pr = AsyncMock(return_value=None)
        client.create_doc_pr = AsyncMock(
            return_value=MagicMock(pr_number=42, pr_url="https://github.com/o/r/pull/42")
        )

        result = await remove_ticket_ref(
            client,
            store,
            owner="o",
            repo="r",
            file_path="docs/specs/test.md",
            section_id="1-has-broken-ticket",
        )
        assert isinstance(result, RemoveTicketRefResult)
        assert result.pr_number == 42
        assert result.already_existed is False
        # The result also reports the qualified ticket_ref so the route layer
        # can auto-dismiss the matching ticket_ref_status row without
        # re-deriving it from the spec.
        assert result.system == "github"
        assert result.ticket_ref == "o/r#456"

        # Verify the markdown passed to create_doc_pr does NOT contain the ticket comment
        call_kwargs = client.create_doc_pr.await_args.kwargs
        files = call_kwargs["files"]
        assert len(files) == 1
        assert "canon:ticket:github:456" not in files[0].content
        # Section header + body remain
        assert "## 1. Has broken ticket" in files[0].content
        assert "Body" in files[0].content
        # canon:system: comment is preserved (only ticket comment is removed)
        assert "canon:system:1" in files[0].content

    async def test_already_existed_result_carries_ticket_ref(self):
        """Existing-PR path also returns system + ticket_ref so the route
        can auto-dismiss the row regardless of whether a new PR was opened."""
        from unittest.mock import AsyncMock, MagicMock

        from canon.web.services import remove_ticket_ref

        client = AsyncMock()
        store = AsyncMock()
        store.get_spec_raw = AsyncMock(return_value=self.SPEC_WITH_TICKET)
        client.find_open_doc_pr = AsyncMock(
            return_value=MagicMock(pr_number=7, pr_url="https://github.com/o/r/pull/7")
        )

        result = await remove_ticket_ref(
            client,
            store,
            owner="o",
            repo="r",
            file_path="docs/specs/test.md",
            section_id="1-has-broken-ticket",
        )
        assert result.already_existed is True
        assert result.system == "github"
        assert result.ticket_ref == "o/r#456"

    async def test_section_number_fallback_works(self):
        """Test that section_id='1' (bare number) matches via the fallback."""
        from unittest.mock import AsyncMock, MagicMock

        from canon.web.services import RemoveTicketRefResult, remove_ticket_ref

        client = AsyncMock()
        store = AsyncMock()
        store.get_spec_raw = AsyncMock(return_value=self.SPEC_WITH_TICKET)
        client.find_open_doc_pr = AsyncMock(return_value=None)
        client.create_doc_pr = AsyncMock(
            return_value=MagicMock(pr_number=42, pr_url="https://github.com/o/r/pull/42")
        )

        result = await remove_ticket_ref(
            client,
            store,
            owner="o",
            repo="r",
            file_path="docs/specs/test.md",
            section_id="1",  # bare number, hits fallback
        )
        assert isinstance(result, RemoveTicketRefResult)
        assert result.pr_number == 42

    async def test_409_when_existing_pr_for_same_section(self):
        from unittest.mock import AsyncMock, MagicMock

        from canon.web.services import remove_ticket_ref

        client = AsyncMock()
        store = AsyncMock()
        store.get_spec_raw = AsyncMock(return_value=self.SPEC_WITH_TICKET)
        client.find_open_doc_pr = AsyncMock(
            return_value=MagicMock(pr_number=7, pr_url="https://github.com/o/r/pull/7")
        )

        result = await remove_ticket_ref(
            client,
            store,
            owner="o",
            repo="r",
            file_path="docs/specs/test.md",
            section_id="1",
        )
        assert result.pr_number == 7
        assert result.already_existed is True
        client.create_doc_pr.assert_not_called()

    async def test_section_not_found_raises(self):
        from unittest.mock import AsyncMock

        import pytest

        from canon.web.services import SectionNotFoundError, remove_ticket_ref

        client = AsyncMock()
        store = AsyncMock()
        store.get_spec_raw = AsyncMock(return_value=self.SPEC_WITH_TICKET)

        with pytest.raises(SectionNotFoundError):
            await remove_ticket_ref(
                client,
                store,
                owner="o",
                repo="r",
                file_path="docs/specs/test.md",
                section_id="9999-does-not-exist",
            )

    async def test_section_without_ticket_link_raises_already_updated(self):
        from unittest.mock import AsyncMock

        import pytest

        from canon.web.services import SectionAlreadyUpdatedError, remove_ticket_ref

        client = AsyncMock()
        store = AsyncMock()
        store.get_spec_raw = AsyncMock(return_value=self.SPEC_WITHOUT_TICKET)

        with pytest.raises(SectionAlreadyUpdatedError):
            await remove_ticket_ref(
                client,
                store,
                owner="o",
                repo="r",
                file_path="docs/specs/test.md",
                section_id="1-no-ticket-here",
            )

    async def test_falls_back_to_github_when_cache_empty(self):
        from unittest.mock import AsyncMock, MagicMock

        from canon.web.services import remove_ticket_ref

        client = AsyncMock()
        client.get_file_content = AsyncMock(return_value=(self.SPEC_WITH_TICKET, "abc"))
        client.find_open_doc_pr = AsyncMock(return_value=None)
        client.create_doc_pr = AsyncMock(
            return_value=MagicMock(pr_number=42, pr_url="https://github.com/o/r/pull/42")
        )

        # Pass content_cache_store=None to simulate the cache-disabled path
        result = await remove_ticket_ref(
            client,
            None,
            owner="o",
            repo="r",
            file_path="docs/specs/test.md",
            section_id="1",
        )
        assert result.pr_number == 42
        client.get_file_content.assert_awaited_once_with("o", "r", "docs/specs/test.md")
