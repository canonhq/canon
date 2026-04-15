"""Tests for spec_utils: doc pattern matching, directory extraction, load_repo_docs, load_repo_specs."""

from __future__ import annotations

from unittest.mock import AsyncMock

from canon.github.spec_utils import (
    DEFAULT_DOC_PATTERNS,
    extract_directories,
    filter_spec_files,
    is_spec_file,
    load_repo_docs,
    load_repo_specs,
    matches_doc_patterns,
)


class TestMatchesDocPatterns:
    def test_matches_default_spec_pattern(self):
        assert matches_doc_patterns("docs/specs/auth.md", DEFAULT_DOC_PATTERNS)

    def test_rejects_non_matching_path(self):
        assert not matches_doc_patterns("src/main.py", DEFAULT_DOC_PATTERNS)

    def test_rejects_nested_path_for_single_level_glob(self):
        assert not matches_doc_patterns("docs/specs/sub/auth.md", ["docs/specs/*.md"])

    def test_matches_recursive_pattern(self):
        patterns = ["docs/rfcs/**/*.md"]
        assert matches_doc_patterns("docs/rfcs/2026/auth.md", patterns)
        assert matches_doc_patterns("docs/rfcs/deep/nested/spec.md", patterns)

    def test_rejects_wrong_extension(self):
        assert not matches_doc_patterns("docs/specs/auth.txt", DEFAULT_DOC_PATTERNS)

    def test_matches_root_level_pattern(self):
        assert matches_doc_patterns("README.md", ["*.md"])

    def test_matches_with_multiple_patterns(self):
        patterns = ["docs/specs/*.md", "design/*.md"]
        assert matches_doc_patterns("docs/specs/auth.md", patterns)
        assert matches_doc_patterns("design/overview.md", patterns)
        assert not matches_doc_patterns("src/main.py", patterns)

    def test_empty_patterns_matches_nothing(self):
        assert not matches_doc_patterns("docs/specs/auth.md", [])


class TestExtractDirectories:
    def test_single_level_glob(self):
        result = extract_directories(["docs/specs/*.md"])
        assert result == [("docs/specs", False)]

    def test_recursive_glob(self):
        result = extract_directories(["docs/rfcs/**/*.md"])
        assert result == [("docs/rfcs", True)]

    def test_root_level_glob(self):
        result = extract_directories(["*.md"])
        assert result == [("", False)]

    def test_multiple_patterns(self):
        result = extract_directories(["docs/specs/*.md", "docs/rfcs/**/*.md", "design/*.md"])
        assert result == [
            ("docs/specs", False),
            ("docs/rfcs", True),
            ("design", False),
        ]

    def test_deep_directory(self):
        result = extract_directories(["a/b/c/d/*.md"])
        assert result == [("a/b/c/d", False)]


class TestLoadRepoDocs:
    async def test_loads_default_patterns(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(
            return_value=[
                {"path": "docs/specs/auth.md", "type": "file", "name": "auth.md"},
                {"path": "docs/specs/_template.md", "type": "file", "name": "_template.md"},
            ]
        )
        client.get_file_content = AsyncMock(
            return_value=(
                "---\ntitle: Auth\nstatus: draft\nowner: test\nteam: platform\n---\n# Auth\n",
                "abc123",
            )
        )

        docs = await load_repo_docs(client, "org", "repo")
        # _template.md should be excluded (starts with _)
        assert len(docs) == 1
        assert docs[0]["file_path"] == "docs/specs/auth.md"

    async def test_loads_custom_patterns(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(
            return_value=[
                {"path": "design/overview.md", "type": "file", "name": "overview.md"},
            ]
        )
        client.get_file_content = AsyncMock(
            return_value=(
                "---\ntitle: Overview\nstatus: draft\nowner: test\nteam: design\n---\n# Overview\n",
                "def456",
            )
        )

        docs = await load_repo_docs(client, "org", "repo", patterns=["design/*.md"])
        assert len(docs) == 1
        assert docs[0]["file_path"] == "design/overview.md"

    async def test_empty_directory_returns_empty(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(return_value=[])

        docs = await load_repo_docs(client, "org", "repo")
        assert docs == []

    async def test_deduplicates_across_patterns(self):
        """If multiple patterns match the same directory, files aren't duplicated."""
        client = AsyncMock()
        client.list_directory = AsyncMock(
            return_value=[
                {"path": "docs/specs/auth.md", "type": "file", "name": "auth.md"},
            ]
        )
        client.get_file_content = AsyncMock(
            return_value=(
                "---\ntitle: Auth\nstatus: draft\nowner: test\nteam: platform\n---\n# Auth\n",
                "abc123",
            )
        )

        docs = await load_repo_docs(
            client,
            "org",
            "repo",
            patterns=["docs/specs/*.md", "docs/specs/*.md"],
        )
        assert len(docs) == 1

    async def test_skips_non_md_files(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(
            return_value=[
                {"path": "docs/specs/auth.md", "type": "file", "name": "auth.md"},
                {"path": "docs/specs/data.json", "type": "file", "name": "data.json"},
            ]
        )
        client.get_file_content = AsyncMock(
            return_value=(
                "---\ntitle: Auth\nstatus: draft\nowner: test\nteam: platform\n---\n# Auth\n",
                "abc123",
            )
        )

        docs = await load_repo_docs(client, "org", "repo")
        assert len(docs) == 1

    async def test_handles_parse_failure_gracefully(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(
            return_value=[
                {"path": "docs/specs/bad.md", "type": "file", "name": "bad.md"},
            ]
        )
        client.get_file_content = AsyncMock(side_effect=Exception("network error"))

        docs = await load_repo_docs(client, "org", "repo")
        assert docs == []


class TestIsSpecFile:
    def test_default_pattern(self):
        assert is_spec_file("docs/specs/auth.md")

    def test_default_rejects_non_spec(self):
        assert not is_spec_file("src/main.py")

    def test_custom_patterns(self):
        patterns = ["design/*.md"]
        assert is_spec_file("design/overview.md", patterns=patterns)
        assert not is_spec_file("docs/specs/auth.md", patterns=patterns)

    def test_none_patterns_uses_default(self):
        assert is_spec_file("docs/specs/auth.md", patterns=None)
        assert not is_spec_file("design/overview.md", patterns=None)


class TestFilterSpecFiles:
    def test_default_patterns(self):
        paths = ["docs/specs/auth.md", "src/main.py", "docs/specs/api.md"]
        result = filter_spec_files(paths)
        assert result == ["docs/specs/auth.md", "docs/specs/api.md"]

    def test_custom_patterns(self):
        paths = ["design/auth.md", "docs/specs/auth.md", "src/main.py"]
        result = filter_spec_files(paths, patterns=["design/*.md"])
        assert result == ["design/auth.md"]


class TestLoadRepoSpecs:
    async def test_loads_default_patterns(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(
            return_value=[
                {"path": "docs/specs/auth.md", "type": "file", "name": "auth.md"},
                {"path": "docs/specs/_template.md", "type": "file", "name": "_template.md"},
            ]
        )
        client.get_file_content = AsyncMock(
            return_value=(
                "---\ntitle: Auth\nstatus: draft\nowner: test\nteam: platform\n---\n# Auth\n",
                "abc123",
            )
        )

        specs = await load_repo_specs(client, "org", "repo")
        assert len(specs) == 1
        assert specs[0]["file_path"] == "docs/specs/auth.md"
        assert "raw" in specs[0]

    async def test_loads_custom_patterns(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(
            return_value=[
                {"path": "design/overview.md", "type": "file", "name": "overview.md"},
            ]
        )
        client.get_file_content = AsyncMock(
            return_value=(
                "---\ntitle: Overview\nstatus: draft\nowner: test\nteam: design\n---\n# Overview\n",
                "def456",
            )
        )

        specs = await load_repo_specs(client, "org", "repo", patterns=["design/*.md"])
        assert len(specs) == 1
        assert specs[0]["file_path"] == "design/overview.md"

    async def test_empty_directory_returns_empty(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(return_value=[])

        specs = await load_repo_specs(client, "org", "repo")
        assert specs == []

    async def test_excludes_underscore_files(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(
            return_value=[
                {"path": "docs/specs/auth.md", "type": "file", "name": "auth.md"},
                {"path": "docs/specs/_template.md", "type": "file", "name": "_template.md"},
            ]
        )
        client.get_file_content = AsyncMock(
            return_value=(
                "---\ntitle: Auth\nstatus: draft\nowner: test\nteam: platform\n---\n# Auth\n",
                "abc123",
            )
        )

        specs = await load_repo_specs(client, "org", "repo")
        assert len(specs) == 1
        assert specs[0]["file_path"] == "docs/specs/auth.md"

    async def test_deduplicates_across_patterns(self):
        client = AsyncMock()
        client.list_directory = AsyncMock(
            return_value=[
                {"path": "docs/specs/auth.md", "type": "file", "name": "auth.md"},
            ]
        )
        client.get_file_content = AsyncMock(
            return_value=(
                "---\ntitle: Auth\nstatus: draft\nowner: test\nteam: platform\n---\n# Auth\n",
                "abc123",
            )
        )

        specs = await load_repo_specs(
            client, "org", "repo", patterns=["docs/specs/*.md", "docs/specs/*.md"]
        )
        assert len(specs) == 1
