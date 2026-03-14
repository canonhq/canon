"""Tests for canon setup CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from canon.cli.setup_cmd import (
    _check_github_connection,
    _detect_existing_specs,
    _detect_project_key,
    run_setup,
)


class TestDetectProjectKey:
    def test_detects_from_remote(self, tmp_path: Path):
        with patch("canon.cli._local.resolve_github_remote", return_value=("Acme", "repo")):
            result = _detect_project_key(tmp_path)
        assert result == "Acme/repo"

    def test_returns_empty_when_none(self, tmp_path: Path):
        with patch("canon.cli._local.resolve_github_remote", return_value=None):
            result = _detect_project_key(tmp_path)
        assert result == ""


class TestDetectExistingSpecs:
    def test_finds_docs_specs(self, tmp_path: Path):
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "feature.md").write_text("# Feature")
        result = _detect_existing_specs(tmp_path)
        assert "docs/specs/*.md" in result

    def test_finds_docs_root(self, tmp_path: Path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "design.md").write_text("# Design")
        result = _detect_existing_specs(tmp_path)
        assert "docs/*.md" in result

    def test_finds_specs_dir(self, tmp_path: Path):
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "api.md").write_text("# API")
        result = _detect_existing_specs(tmp_path)
        assert "specs/*.md" in result

    def test_ignores_underscore_prefixed(self, tmp_path: Path):
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "_template.md").write_text("# Template")
        result = _detect_existing_specs(tmp_path)
        assert result == []

    def test_empty_directory(self, tmp_path: Path):
        result = _detect_existing_specs(tmp_path)
        assert result == []

    def test_multiple_locations(self, tmp_path: Path):
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "a.md").write_text("# A")
        (tmp_path / "docs" / "readme.md").write_text("# Readme")
        result = _detect_existing_specs(tmp_path)
        assert "docs/specs/*.md" in result
        assert "docs/*.md" in result


class TestCheckGithubConnection:
    def test_authenticated(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "Logged in to github.com account user\n"
            mock_run.return_value.stderr = ""
            status, _msg = _check_github_connection()
        assert status == "ok"

    def test_not_authenticated(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "not logged in"
            status, msg = _check_github_connection()
        assert status == "warning"
        assert "gh auth login" in msg

    def test_gh_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            status, msg = _check_github_connection()
        assert status == "none"
        assert "not installed" in msg


class TestRunSetupNonInteractive:
    def test_fresh_setup(self, tmp_path: Path, capsys):
        run_setup(non_interactive=True, target_dir=tmp_path)

        assert (tmp_path / "CANON.yaml").exists()
        assert (tmp_path / "docs" / "specs" / "_template.md").exists()

        config = (tmp_path / "CANON.yaml").read_text()
        assert "specs:" in config
        assert "system: github" in config

        output = capsys.readouterr().out
        assert "Created: CANON.yaml" in output

    def test_with_team_and_ticket_system(self, tmp_path: Path):
        run_setup(team="platform", ticket_system="jira", non_interactive=True, target_dir=tmp_path)

        config = (tmp_path / "CANON.yaml").read_text()
        assert "team: platform" in config
        assert "system: jira" in config

    def test_reconfigure_overwrites_config(self, tmp_path: Path, capsys):
        # Initial setup
        (tmp_path / "CANON.yaml").write_text("team: old\n")

        run_setup(team="new-team", non_interactive=True, target_dir=tmp_path)

        config = (tmp_path / "CANON.yaml").read_text()
        assert "team: new-team" in config
        assert "old" not in config

        output = capsys.readouterr().out
        assert "Updated: CANON.yaml" in output

    def test_skips_existing_template(self, tmp_path: Path, capsys):
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "_template.md").write_text("existing template")

        run_setup(non_interactive=True, target_dir=tmp_path)

        # Template should not be overwritten
        assert (tmp_path / "docs" / "specs" / "_template.md").read_text() == "existing template"

    def test_detects_existing_specs(self, tmp_path: Path, capsys):
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "auth.md").write_text("# Auth\n")
        (tmp_path / "specs" / "api.md").write_text("# API\n")

        run_setup(non_interactive=True, target_dir=tmp_path)

        config = (tmp_path / "CANON.yaml").read_text()
        assert '"specs/*.md"' in config

        output = capsys.readouterr().out
        assert "Found 2 existing spec files" in output


class TestRunSetupInteractive:
    def test_fresh_interactive_flow(self, tmp_path: Path, monkeypatch, capsys):
        inputs = iter(["my-team", "", "", "", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

        run_setup(target_dir=tmp_path)

        assert (tmp_path / "CANON.yaml").exists()
        config = (tmp_path / "CANON.yaml").read_text()
        assert "team: my-team" in config
        assert "system: github" in config

    def test_reconfigure_confirm(self, tmp_path: Path, monkeypatch, capsys):
        (tmp_path / "CANON.yaml").write_text("team: old\n")

        # y to reconfigure, team, system choice, project, confirm
        inputs = iter(["y", "new-team", "", "", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

        run_setup(target_dir=tmp_path)

        config = (tmp_path / "CANON.yaml").read_text()
        assert "team: new-team" in config

    def test_reconfigure_decline(self, tmp_path: Path, monkeypatch, capsys):
        (tmp_path / "CANON.yaml").write_text("team: old\n")

        inputs = iter(["n"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

        run_setup(target_dir=tmp_path)

        # Should not change
        assert (tmp_path / "CANON.yaml").read_text() == "team: old\n"

        output = capsys.readouterr().out
        assert "cancelled" in output

    def test_jira_host_prompt(self, tmp_path: Path, monkeypatch, capsys):
        # team, system=jira, project, jira host, confirm
        inputs = iter(["", "2", "", "acme.atlassian.net", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

        run_setup(target_dir=tmp_path)

        config = (tmp_path / "CANON.yaml").read_text()
        assert "system: jira" in config
        assert 'host: "acme.atlassian.net"' in config

    def test_github_connection_check(self, tmp_path: Path, monkeypatch, capsys):
        inputs = iter(["", "", "", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

        with patch(
            "canon.cli.setup_cmd._check_github_connection",
            return_value=("ok", "Authenticated with GitHub CLI"),
        ):
            run_setup(target_dir=tmp_path)

        output = capsys.readouterr().out
        assert "GitHub:" in output

    def test_write_cancelled(self, tmp_path: Path, monkeypatch, capsys):
        # team, system, project, decline write
        inputs = iter(["", "", "", "n"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

        run_setup(target_dir=tmp_path)

        assert not (tmp_path / "CANON.yaml").exists()
        output = capsys.readouterr().out
        assert "cancelled" in output


class TestCliEntryPoint:
    def test_setup_subcommand(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        from canon.cli import main

        main(["setup", "--non-interactive"])

        assert (tmp_path / "docs" / "specs" / "_template.md").exists()
        assert (tmp_path / "CANON.yaml").exists()

    def test_no_subcommand_exits(self):
        from canon.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main([])

        assert exc_info.value.code == 1

    def test_setup_with_options(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        from canon.cli import main

        main(["setup", "--non-interactive", "--team", "backend", "--ticket-system", "linear"])

        config = (tmp_path / "CANON.yaml").read_text()
        assert "team: backend" in config
        assert "system: linear" in config
