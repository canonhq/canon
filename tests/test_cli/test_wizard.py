"""Tests for the guided onboarding wizard."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from canon.cli.wizard import WizardState, _load_existing_config, _step_repo_detection


class TestWizardState:
    def test_defaults(self):
        state = WizardState()
        assert state.repo_owner == ""
        assert state.authenticated is False
        assert state.integration_connected is False
        assert state.skipped_steps == []


class TestLoadExistingConfig:
    def test_loads_team_and_system(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text(
            "team: myteam\nticket_system: jira\nproject_key: acme/repo\n"
        )
        state = WizardState(root=tmp_path)
        _load_existing_config(state)
        assert state.team == "myteam"
        assert state.ticket_system == "jira"
        assert state.project_key == "acme/repo"

    def test_no_yaml_is_noop(self, tmp_path: Path):
        state = WizardState(root=tmp_path)
        _load_existing_config(state)
        assert state.team == ""

    def test_invalid_yaml_is_noop(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("[invalid: yaml: {")
        state = WizardState(root=tmp_path)
        _load_existing_config(state)
        assert state.team == ""


class TestStepRepoDetection:
    def test_detects_git_remote(self, tmp_path: Path):
        state = WizardState(root=tmp_path, non_interactive=True)
        with patch("canon.cli._local.resolve_github_remote", return_value=("acme", "repo")):
            _step_repo_detection(state)
        assert state.repo_owner == "acme"
        assert state.repo_name == "repo"
        assert state.project_key == "acme/repo"

    def test_no_remote_non_interactive(self, tmp_path: Path):
        state = WizardState(root=tmp_path, non_interactive=True)
        with patch("canon.cli._local.resolve_github_remote", return_value=None):
            _step_repo_detection(state)
        assert state.project_key == ""

    def test_counts_spec_files(self, tmp_path: Path):
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "a.md").write_text("# A")
        (tmp_path / "docs" / "specs" / "b.md").write_text("# B")
        (tmp_path / "docs" / "specs" / "_template.md").write_text("# T")

        state = WizardState(root=tmp_path, non_interactive=True)
        with patch("canon.cli._local.resolve_github_remote", return_value=None):
            _step_repo_detection(state)
        assert state.spec_count == 2  # _template excluded

    def test_existing_config_non_interactive_proceeds(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("team: old\nticket_system: github\n")
        state = WizardState(root=tmp_path, non_interactive=True)
        with patch("canon.cli._local.resolve_github_remote", return_value=None):
            _step_repo_detection(state)
        # Non-interactive doesn't prompt, just proceeds


class TestWizardNonInteractive:
    def test_full_non_interactive_run(self, tmp_path: Path):
        """Non-interactive wizard should complete without prompts."""
        from canon.cli.wizard import run_wizard

        with (
            patch("canon.cli._local.resolve_github_remote", return_value=("acme", "repo")),
            patch("canon.cli._credentials.load_credentials", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            run_wizard(
                team="testteam",
                ticket_system="github",
                non_interactive=True,
                target_dir=tmp_path,
            )

        # Should have created config files
        assert (tmp_path / "CANON.yaml").exists()
        config = (tmp_path / "CANON.yaml").read_text()
        assert "testteam" in config
