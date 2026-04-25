"""Tests for the full re-index CLI."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from canon.parser.models import (
    SectionStatus,
    SpecDocument,
    SpecFrontmatter,
    SpecSection,
)


def _make_doc(
    *,
    title: str = "Test Spec",
    file_path: str = "docs/specs/test.md",
) -> SpecDocument:
    return SpecDocument(
        file_path=file_path,
        frontmatter=SpecFrontmatter(
            title=title,
            status="draft",
            owner="eng",
            team="platform",
        ),
        sections=[
            SpecSection(
                id="s1",
                section_number=None,
                title="Section 1",
                depth=2,
                content="Body",
                status=SectionStatus(state="draft"),
                children=[],
                start_line=1,
                end_line=5,
            ),
        ],
        raw="# Test Spec\nContent",
    )


class TestRunReindex:
    @patch("canon.search.reindex.close_pool", new_callable=AsyncMock)
    @patch("canon.search.reindex.ensure_schema", new_callable=AsyncMock)
    @patch("canon.search.reindex.create_pool", new_callable=AsyncMock)
    @patch("canon.search.reindex.EmbeddingClient")
    @patch("canon.search.reindex.SearchIndex")
    @patch("canon.search.reindex.load_repo_specs", new_callable=AsyncMock)
    @patch("canon.search.reindex.index_spec", new_callable=AsyncMock)
    @patch("canon.search.reindex.GitHubClient")
    @patch("canon.search.reindex.Settings")
    async def test_indexes_all_specs(
        self,
        mock_settings_cls,
        mock_client_cls,
        mock_index_spec,
        mock_load_specs,
        mock_search_index_cls,
        mock_embed_cls,
        mock_create_pool,
        mock_ensure_schema,
        mock_close_pool,
    ):
        """Verifies index_spec is called for each spec in each repo."""
        settings = MagicMock()
        settings.gh_app_id = "123"
        settings.gh_private_key = "key"
        settings.gh_installation_id = "456"
        settings.database_url = "postgres://localhost/test"
        settings.google_cloud_project = ""
        settings.google_cloud_location = "us-central1"
        settings.gcp_service_account_key = ""
        mock_settings_cls.return_value = settings

        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        # Simulate listing repos
        mock_client.list_installation_repos = AsyncMock(
            return_value=[
                {"owner": {"login": "org"}, "name": "repo1"},
                {"owner": {"login": "org"}, "name": "repo2"},
            ]
        )

        doc1 = _make_doc(title="Auth", file_path="docs/specs/auth.md")
        doc2 = _make_doc(title="API", file_path="docs/specs/api.md")

        mock_load_specs.side_effect = [
            [{"file_path": "docs/specs/auth.md", "document": doc1, "raw": "raw1"}],
            [{"file_path": "docs/specs/api.md", "document": doc2, "raw": "raw2"}],
        ]

        mock_index_spec.return_value = 1
        mock_embed = MagicMock()
        mock_embed.is_available = False
        mock_embed_cls.return_value = mock_embed

        from canon.search.reindex import run_reindex

        results = await run_reindex()

        assert len(results) == 2
        assert results[0]["repo"] == "org/repo1"
        assert results[0]["specs_indexed"] == 1
        assert results[1]["repo"] == "org/repo2"
        assert results[1]["specs_indexed"] == 1
        assert mock_index_spec.await_count == 2

    @patch("canon.search.reindex.close_pool", new_callable=AsyncMock)
    @patch("canon.search.reindex.ensure_schema", new_callable=AsyncMock)
    @patch("canon.search.reindex.create_pool", new_callable=AsyncMock)
    @patch("canon.search.reindex.EmbeddingClient")
    @patch("canon.search.reindex.SearchIndex")
    @patch("canon.search.reindex.load_repo_specs", new_callable=AsyncMock)
    @patch("canon.search.reindex.index_spec", new_callable=AsyncMock)
    @patch("canon.search.reindex.GitHubClient")
    @patch("canon.search.reindex.Settings")
    async def test_handles_errors(
        self,
        mock_settings_cls,
        mock_client_cls,
        mock_index_spec,
        mock_load_specs,
        mock_search_index_cls,
        mock_embed_cls,
        mock_create_pool,
        mock_ensure_schema,
        mock_close_pool,
    ):
        """Errors on individual specs don't stop the overall process."""
        settings = MagicMock()
        settings.gh_app_id = "123"
        settings.gh_private_key = "key"
        settings.gh_installation_id = "456"
        settings.database_url = "postgres://localhost/test"
        settings.google_cloud_project = ""
        settings.google_cloud_location = "us-central1"
        settings.gcp_service_account_key = ""
        mock_settings_cls.return_value = settings

        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_client.list_installation_repos = AsyncMock(
            return_value=[
                {"owner": {"login": "org"}, "name": "repo1"},
            ]
        )

        doc1 = _make_doc(title="Good", file_path="docs/specs/good.md")
        doc2 = _make_doc(title="Bad", file_path="docs/specs/bad.md")

        mock_load_specs.return_value = [
            {"file_path": "docs/specs/good.md", "document": doc1, "raw": "raw1"},
            {"file_path": "docs/specs/bad.md", "document": doc2, "raw": "raw2"},
        ]

        mock_index_spec.side_effect = [1, RuntimeError("DB error")]
        mock_embed = MagicMock()
        mock_embed.is_available = False
        mock_embed_cls.return_value = mock_embed

        from canon.search.reindex import run_reindex

        results = await run_reindex()

        assert results[0]["specs_indexed"] == 1
        assert results[0]["errors"] == 1

    @patch("canon.search.reindex.close_pool", new_callable=AsyncMock)
    @patch("canon.search.reindex.ensure_schema", new_callable=AsyncMock)
    @patch("canon.search.reindex.create_pool", new_callable=AsyncMock)
    @patch("canon.search.reindex.EmbeddingClient")
    @patch("canon.search.reindex.SearchIndex")
    @patch("canon.search.reindex.load_repo_specs", new_callable=AsyncMock)
    @patch("canon.search.reindex.index_spec", new_callable=AsyncMock)
    @patch("canon.search.reindex.GitHubClient")
    @patch("canon.search.reindex.Settings")
    async def test_empty_repos(
        self,
        mock_settings_cls,
        mock_client_cls,
        mock_index_spec,
        mock_load_specs,
        mock_search_index_cls,
        mock_embed_cls,
        mock_create_pool,
        mock_ensure_schema,
        mock_close_pool,
    ):
        """Repos with no specs are skipped gracefully."""
        settings = MagicMock()
        settings.gh_app_id = "123"
        settings.gh_private_key = "key"
        settings.gh_installation_id = "456"
        settings.database_url = "postgres://localhost/test"
        settings.google_cloud_project = ""
        settings.google_cloud_location = "us-central1"
        settings.gcp_service_account_key = ""
        mock_settings_cls.return_value = settings

        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_client.list_installation_repos = AsyncMock(
            return_value=[
                {"owner": {"login": "org"}, "name": "empty-repo"},
            ]
        )

        mock_load_specs.return_value = []
        mock_embed = MagicMock()
        mock_embed.is_available = False
        mock_embed_cls.return_value = mock_embed

        from canon.search.reindex import run_reindex

        results = await run_reindex()

        assert results == []
        mock_index_spec.assert_not_awaited()
