"""Tests for CLI shared local operations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from canon.cli._local import (
    create_github_adapter_local,
    discover_spec_files,
    find_section_by_id,
    load_local_config,
    parse_all_local_specs,
    resolve_github_remote,
    resolve_github_token,
)
from canon.config.parse import DEFAULT_CONFIG

SAMPLE_SPEC = """\
---
title: Test Spec
status: active
owner: test
team: platform
---

## 1. Feature One
<!-- specwright:system:1 status:todo -->

### Acceptance Criteria

- [ ] First AC
- [x] Second AC

## 2. Feature Two
<!-- specwright:system:2 status:in_progress -->

### Acceptance Criteria

- [ ] Third AC

### 2.1. Sub Feature
<!-- specwright:system:2.1 status:done -->
"""

SAMPLE_CONFIG = """\
team: platform
ticket_system: github
project_key: org/repo
specs:
  doc_paths:
    - "docs/specs/*.md"
"""


def _setup_repo(
    tmp_path: Path, spec_content: str = SAMPLE_SPEC, config_content: str = SAMPLE_CONFIG
) -> Path:
    """Create a minimal repo structure."""
    (tmp_path / "CANON.yaml").write_text(config_content)
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / "test-spec.md").write_text(spec_content)
    return tmp_path


class TestLoadLocalConfig:
    def test_loads_config(self, tmp_path: Path):
        _setup_repo(tmp_path)
        config = load_local_config(tmp_path)
        assert config.team == "platform"
        assert config.ticket_system == "github"

    def test_falls_back_to_default(self, tmp_path: Path):
        config = load_local_config(tmp_path)
        assert config == DEFAULT_CONFIG

    def test_empty_config(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("")
        config = load_local_config(tmp_path)
        # Empty YAML → defaults
        assert config.specs.doc_paths == ["docs/specs/*.md"]


class TestDiscoverSpecFiles:
    def test_discovers_specs(self, tmp_path: Path):
        _setup_repo(tmp_path)
        files = discover_spec_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "test-spec.md"

    def test_skips_underscore_prefix(self, tmp_path: Path):
        _setup_repo(tmp_path)
        (tmp_path / "docs" / "specs" / "_template.md").write_text("template")
        files = discover_spec_files(tmp_path)
        assert len(files) == 1  # Only test-spec.md

    def test_no_specs(self, tmp_path: Path):
        files = discover_spec_files(tmp_path)
        assert files == []


class TestParseAllLocalSpecs:
    def test_parses_specs(self, tmp_path: Path):
        _setup_repo(tmp_path)
        docs = parse_all_local_specs(tmp_path)
        assert len(docs) == 1
        assert docs[0].frontmatter.title == "Test Spec"
        assert len(docs[0].sections) >= 2


class TestFindSectionById:
    def test_exact_id(self, tmp_path: Path):
        _setup_repo(tmp_path)
        docs = parse_all_local_specs(tmp_path)
        result = find_section_by_id(docs, "1-feature-one")
        assert result is not None
        _, section = result
        assert section.title == "Feature One"

    def test_section_number(self, tmp_path: Path):
        _setup_repo(tmp_path)
        docs = parse_all_local_specs(tmp_path)
        result = find_section_by_id(docs, "1")
        assert result is not None
        _, section = result
        assert section.title == "Feature One"

    def test_partial_slug(self, tmp_path: Path):
        _setup_repo(tmp_path)
        docs = parse_all_local_specs(tmp_path)
        result = find_section_by_id(docs, "feature-two")
        assert result is not None
        _, section = result
        assert section.title == "Feature Two"

    def test_not_found(self, tmp_path: Path):
        _setup_repo(tmp_path)
        docs = parse_all_local_specs(tmp_path)
        result = find_section_by_id(docs, "nonexistent")
        assert result is None


class TestResolveGithubRemote:
    def test_from_config(self):
        from canon.config.parse import CanonConfig

        config = CanonConfig(project_key="owner/repo")
        result = resolve_github_remote(config)
        assert result == ("owner", "repo")

    def test_from_git_remote_ssh(self, tmp_path: Path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "git@github.com:myorg/myrepo.git\n"
            result = resolve_github_remote(root=tmp_path)
            assert result == ("myorg", "myrepo")

    def test_from_git_remote_https(self, tmp_path: Path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "https://github.com/myorg/myrepo.git\n"
            result = resolve_github_remote(root=tmp_path)
            assert result == ("myorg", "myrepo")

    def test_no_remote(self, tmp_path: Path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            result = resolve_github_remote(root=tmp_path)
            assert result is None

    def test_https_no_git_suffix(self, tmp_path: Path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "https://github.com/Acme/my-repo\n"
            result = resolve_github_remote(root=tmp_path)
            assert result == ("Acme", "my-repo")

    def test_non_github_remote(self, tmp_path: Path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "https://gitlab.com/Acme/my-repo.git\n"
            result = resolve_github_remote(root=tmp_path)
            assert result is None

    def test_git_not_installed(self, tmp_path: Path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = resolve_github_remote(root=tmp_path)
            assert result is None

    def test_subprocess_error(self, tmp_path: Path):
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.SubprocessError):
            result = resolve_github_remote(root=tmp_path)
            assert result is None


class TestResolveGithubToken:
    def test_from_env(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test123"}):
            assert resolve_github_token() == "ghp_test123"

    def test_from_gh_cli(self):
        with patch.dict("os.environ", {}, clear=True), patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "gho_token\n"
            assert resolve_github_token() == "gho_token"

    def test_no_token(self):
        with patch.dict("os.environ", {}, clear=True), patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            assert resolve_github_token() is None


class TestCreateGithubAdapterLocal:
    def test_creates_adapter(self, tmp_path: Path):
        _setup_repo(tmp_path)
        config = load_local_config(tmp_path)
        with patch("canon.cli._local.resolve_github_token", return_value="ghp_test"):
            adapter = create_github_adapter_local(config, tmp_path)
            assert adapter is not None
            assert adapter.config.token == "ghp_test"

    def test_no_token_returns_none(self, tmp_path: Path):
        _setup_repo(tmp_path)
        config = load_local_config(tmp_path)
        with patch("canon.cli._local.resolve_github_token", return_value=None):
            assert create_github_adapter_local(config, tmp_path) is None
