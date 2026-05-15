"""Tests for canon.cli.triage — AI-powered issue classification."""

from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock, patch

from canon.cli.triage import (
    _detect_repo,
    _generate_spec_content,
    _load_triage_config,
    _sanitize_issue_body,
    register,
    run_triage,
)


class TestRegister:
    def test_registers_triage_subcommand(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["triage", "--issue", "42"])
        assert args.command == "triage"
        assert args.issue == 42

    def test_default_values(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["triage", "--issue", "1"])
        assert args.repo is None
        assert args.specs == "docs/specs"
        assert args.apply is False
        assert args.create_spec is False
        assert args.dry_run is False
        assert args.json_output is False
        assert args.confidence_threshold is None

    def test_all_flags(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(
            [
                "triage",
                "--issue",
                "10",
                "--repo",
                "owner/repo",
                "--apply",
                "--create-spec",
                "--dry-run",
                "--json",
                "--confidence-threshold",
                "0.9",
            ]
        )
        assert args.apply is True
        assert args.create_spec is True
        assert args.dry_run is True
        assert args.json_output is True
        assert args.confidence_threshold == 0.9


class TestDetectRepo:
    def test_detects_ssh_remote(self):

        mock_result = MagicMock()
        mock_result.stdout = "git@github.com:owner/repo.git\n"

        with patch("subprocess.run", return_value=mock_result):
            assert _detect_repo() == "owner/repo"

    def test_detects_https_remote(self):
        mock_result = MagicMock()
        mock_result.stdout = "https://github.com/owner/repo.git\n"

        with patch("subprocess.run", return_value=mock_result):
            assert _detect_repo() == "owner/repo"

    def test_detects_https_without_git_suffix(self):
        mock_result = MagicMock()
        mock_result.stdout = "https://github.com/owner/repo\n"

        with patch("subprocess.run", return_value=mock_result):
            assert _detect_repo() == "owner/repo"

    def test_returns_none_on_subprocess_error(self):
        import subprocess

        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            assert _detect_repo() is None

    def test_returns_none_for_non_github_remote(self):
        mock_result = MagicMock()
        mock_result.stdout = "https://gitlab.com/owner/repo.git\n"

        with patch("subprocess.run", return_value=mock_result):
            assert _detect_repo() is None


class TestLoadTriageConfig:
    def test_returns_default_when_no_yaml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _load_triage_config()
        assert result == {"enabled": True}

    def test_reads_triage_section(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "CANON.yaml").write_text(
            "triage:\n  enabled: false\n  ignore_labels:\n    - wontfix\n"
        )
        result = _load_triage_config()
        assert result["enabled"] is False
        assert "wontfix" in result["ignore_labels"]

    def test_returns_default_on_invalid_yaml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "CANON.yaml").write_text("{{{invalid yaml")
        result = _load_triage_config()
        assert result == {"enabled": True}

    def test_returns_default_when_no_triage_key(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "CANON.yaml").write_text("team: platform\n")
        result = _load_triage_config()
        assert result == {"enabled": True}


class TestSanitizeIssueBody:
    def test_strips_canon_comments(self):
        body = "Hello <!-- canon:ticket:123 --> world"
        assert _sanitize_issue_body(body) == "Hello  world"

    def test_strips_multiple_comments(self):
        body = "A <!-- canon:a --> B <!-- canon:b --> C"
        assert _sanitize_issue_body(body) == "A  B  C"

    def test_leaves_non_canon_comments(self):
        body = "Hello <!-- normal comment --> world"
        assert _sanitize_issue_body(body) == "Hello <!-- normal comment --> world"

    def test_empty_body(self):
        assert _sanitize_issue_body("") == ""


class TestGenerateSpecContent:
    def test_generates_valid_frontmatter(self):
        # Create a mock IssueContext
        issue_ctx = MagicMock()
        issue_ctx.title = "Add dark mode"
        issue_ctx.body = "We need dark mode support for the dashboard."
        issue_ctx.author = "testuser"
        issue_ctx.number = 42

        content = _generate_spec_content(issue_ctx)

        assert 'title: "Add dark mode"' in content
        assert "status: draft" in content
        assert "owner: testuser" in content
        assert "# Add dark mode" in content
        assert "canon:ticket:github:42" in content
        assert "dark mode support" in content

    def test_escapes_special_characters_in_title(self):
        issue_ctx = MagicMock()
        issue_ctx.title = 'Feature with "quotes" and \\backslash'
        issue_ctx.body = "Body text"
        issue_ctx.author = "user"
        issue_ctx.number = 1

        content = _generate_spec_content(issue_ctx)

        assert '\\"quotes\\"' in content
        assert "\\\\" in content

    def test_truncates_long_body(self):
        issue_ctx = MagicMock()
        issue_ctx.title = "Feature"
        issue_ctx.body = "x" * 5000
        issue_ctx.author = "user"
        issue_ctx.number = 1

        content = _generate_spec_content(issue_ctx)

        # Body should be truncated to 2000 chars
        lines = content.split("\n")
        body_section = [line for line in lines if "x" * 10 in line]
        assert all(len(line) <= 2000 for line in body_section)

    def test_handles_empty_body(self):
        issue_ctx = MagicMock()
        issue_ctx.title = "Feature"
        issue_ctx.body = ""
        issue_ctx.author = "user"
        issue_ctx.number = 1

        content = _generate_spec_content(issue_ctx)

        assert "Brief overview of this feature." in content


class TestRunTriage:
    def test_error_when_no_repo_detected(self, capsys):
        with patch("canon.cli.triage._detect_repo", return_value=None):
            exit_code = run_triage(issue=1)

        assert exit_code == 1
        assert "Could not detect repository" in capsys.readouterr().err

    def test_error_when_repo_format_invalid(self, capsys):
        exit_code = run_triage(issue=1, repo="noslash")

        assert exit_code == 1
        assert "owner/name format" in capsys.readouterr().err

    def test_error_when_no_github_token(self, monkeypatch, capsys):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

        with (
            patch("canon.cli.triage._detect_repo", return_value="owner/repo"),
            patch.dict(
                "sys.modules", {"issue_triage": MagicMock(), "issue_triage.matcher": MagicMock()}
            ),
            patch("canon.cli.triage.Path.exists", return_value=False),
        ):
            exit_code = run_triage(issue=1, repo="owner/repo")

        assert exit_code == 1
        assert "GITHUB_TOKEN" in capsys.readouterr().err

    def test_error_when_issue_fetch_fails(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")

        with (
            patch.dict(
                "sys.modules", {"issue_triage": MagicMock(), "issue_triage.matcher": MagicMock()}
            ),
            patch("canon.cli.triage.Path.exists", return_value=False),
            patch("asyncio.run", return_value=None),
        ):
            exit_code = run_triage(issue=999, repo="owner/repo")

        assert exit_code == 1
        assert "Could not fetch issue" in capsys.readouterr().err

    def test_skips_when_triage_disabled(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")

        mock_issue = MagicMock()
        mock_issue.labels = []
        mock_issue.author = "user"
        mock_issue.title = "Test"

        with (
            patch.dict(
                "sys.modules", {"issue_triage": MagicMock(), "issue_triage.matcher": MagicMock()}
            ),
            patch("canon.cli.triage.Path.exists", return_value=False),
            patch("asyncio.run", return_value=mock_issue),
            patch("canon.cli.triage._load_triage_config", return_value={"enabled": False}),
        ):
            exit_code = run_triage(issue=1, repo="owner/repo")

        assert exit_code == 0
        assert "disabled" in capsys.readouterr().err

    def test_skips_when_issue_has_ignored_label(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")

        mock_issue = MagicMock()
        mock_issue.labels = ["wontfix"]
        mock_issue.author = "user"
        mock_issue.title = "Test"

        with (
            patch.dict(
                "sys.modules", {"issue_triage": MagicMock(), "issue_triage.matcher": MagicMock()}
            ),
            patch("canon.cli.triage.Path.exists", return_value=False),
            patch("asyncio.run", return_value=mock_issue),
            patch(
                "canon.cli.triage._load_triage_config",
                return_value={"enabled": True, "ignore_labels": ["wontfix"]},
            ),
        ):
            exit_code = run_triage(issue=1, repo="owner/repo")

        assert exit_code == 0
        assert "ignored label" in capsys.readouterr().err

    def test_skips_when_author_ignored(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")

        mock_issue = MagicMock()
        mock_issue.labels = []
        mock_issue.author = "bot-user"
        mock_issue.title = "Test"

        with (
            patch.dict(
                "sys.modules", {"issue_triage": MagicMock(), "issue_triage.matcher": MagicMock()}
            ),
            patch("canon.cli.triage.Path.exists", return_value=False),
            patch("asyncio.run", return_value=mock_issue),
            patch(
                "canon.cli.triage._load_triage_config",
                return_value={"enabled": True, "ignore_authors": ["bot-user"]},
            ),
        ):
            exit_code = run_triage(issue=1, repo="owner/repo")

        assert exit_code == 0
        assert "author is ignored" in capsys.readouterr().err

    def test_json_output_mode(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")

        mock_issue = MagicMock()
        mock_issue.labels = []
        mock_issue.author = "user"
        mock_issue.title = "Test Issue"

        mock_result = MagicMock()
        mock_result.classification.value = "feature-request"
        mock_result.confidence = 0.85
        mock_result.reasoning = "Looks like a feature"
        mock_result.related_specs = []
        mock_result.suggested_labels = ["enhancement"]
        mock_result.duplicate_of = None

        mock_classifier = MagicMock()
        mock_classifier.classify_issue.return_value = mock_result

        with (
            patch.dict(
                "sys.modules",
                {
                    "issue_triage": MagicMock(),
                    "issue_triage.matcher": MagicMock(),
                    "issue_triage.classifier": mock_classifier,
                },
            ),
            patch("canon.cli.triage.Path.exists", return_value=False),
            patch("asyncio.run", return_value=mock_issue),
            patch("canon.cli.triage._load_triage_config", return_value={"enabled": True}),
            patch("canon.agent.client.ClaudeClient"),
        ):
            exit_code = run_triage(issue=42, repo="owner/repo", json_output=True)

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["issue"] == 42
        assert output["classification"] == "feature-request"
        assert output["confidence"] == 0.85

    def test_dry_run_does_not_apply(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")

        mock_issue = MagicMock()
        mock_issue.labels = []
        mock_issue.author = "user"
        mock_issue.title = "Test"

        mock_result = MagicMock()
        mock_result.classification.value = "bug"
        mock_result.confidence = 0.95
        mock_result.reasoning = "Bug report"
        mock_result.related_specs = []
        mock_result.suggested_labels = ["bug"]
        mock_result.duplicate_of = None

        mock_classifier = MagicMock()
        mock_classifier.classify_issue.return_value = mock_result

        with (
            patch.dict(
                "sys.modules",
                {
                    "issue_triage": MagicMock(),
                    "issue_triage.matcher": MagicMock(),
                    "issue_triage.classifier": mock_classifier,
                },
            ),
            patch("canon.cli.triage.Path.exists", return_value=False),
            patch("asyncio.run", return_value=mock_issue),
            patch("canon.cli.triage._load_triage_config", return_value={"enabled": True}),
            patch("canon.agent.client.ClaudeClient"),
        ):
            exit_code = run_triage(issue=1, repo="owner/repo", apply=True, dry_run=True)

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "dry-run" in output

    def test_below_threshold_skips_actions(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")

        mock_issue = MagicMock()
        mock_issue.labels = []
        mock_issue.author = "user"
        mock_issue.title = "Test"

        mock_result = MagicMock()
        mock_result.classification.value = "question"
        mock_result.confidence = 0.3
        mock_result.reasoning = "Not sure"
        mock_result.related_specs = []
        mock_result.suggested_labels = []
        mock_result.duplicate_of = None

        mock_classifier = MagicMock()
        mock_classifier.classify_issue.return_value = mock_result

        with (
            patch.dict(
                "sys.modules",
                {
                    "issue_triage": MagicMock(),
                    "issue_triage.matcher": MagicMock(),
                    "issue_triage.classifier": mock_classifier,
                },
            ),
            patch("canon.cli.triage.Path.exists", return_value=False),
            patch("asyncio.run", return_value=mock_issue),
            patch("canon.cli.triage._load_triage_config", return_value={"enabled": True}),
            patch("canon.agent.client.ClaudeClient"),
        ):
            exit_code = run_triage(issue=1, repo="owner/repo", apply=True, confidence_threshold=0.8)

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "below threshold" in output
