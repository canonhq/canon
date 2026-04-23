"""Tests for canon integrations CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from canon.cli.integrations_cmd import (
    _format_provider,
    _format_source,
    _format_status,
    _get_org,
    _run_list,
    _run_test,
)


class TestFormatHelpers:
    def test_format_provider(self):
        assert _format_provider("jira") == "Jira"
        assert _format_provider("linear") == "Linear"
        assert _format_provider("github") == "GitHub Issues"
        assert _format_provider("unknown") == "unknown"

    def test_format_status(self):
        assert _format_status("connected") == "connected"
        assert _format_status("not_configured") == "not configured"
        assert _format_status("needs_reauth") == "needs reauth"

    def test_format_source(self):
        assert _format_source("backend") == "backend"
        assert _format_source("env_var") == "env var"
        assert _format_source("canon_yaml") == "canon.yaml"


class TestGetOrg:
    def test_returns_org_from_credentials(self):
        cred = {"method": "oauth", "org": "testorg"}
        with patch("canon.cli._credentials.load_credentials", return_value=cred):
            assert _get_org() == "testorg"

    def test_returns_none_when_no_credentials_and_no_remote(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("canon.cli._credentials.load_credentials", return_value=None):
            assert _get_org() is None

    def test_falls_back_to_canon_yaml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "CANON.yaml").write_text("team: acme\n")
        cred = {"method": "oauth"}  # no org field
        with patch("canon.cli._credentials.load_credentials", return_value=cred):
            assert _get_org() == "acme"

    def test_falls_back_to_git_remote(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cred = {"method": "oauth"}  # no org field
        with (
            patch("canon.cli._credentials.load_credentials", return_value=cred),
            patch("canon.cli._local.resolve_github_remote", return_value=("acme", "repo")),
        ):
            assert _get_org() == "acme"

    def test_returns_none_when_no_org_and_no_remote(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cred = {"method": "oauth"}
        with (
            patch("canon.cli._credentials.load_credentials", return_value=cred),
            patch("canon.cli._local.resolve_github_remote", return_value=None),
        ):
            assert _get_org() is None


class TestRunList:
    def test_json_output(self, capsys, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("canon.cli._credentials.load_credentials", return_value=None):
            _run_list(json_output=True)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == 3
        providers = [d["provider"] for d in data]
        assert "jira" in providers
        assert "linear" in providers
        assert "github" in providers

    def test_human_output_shows_header(self, capsys, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("canon.cli._credentials.load_credentials", return_value=None):
            _run_list(json_output=False)

        captured = capsys.readouterr()
        assert "Provider" in captured.out
        assert "not configured" in captured.out

    def test_source_filter(self, capsys, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LINEAR_API_KEY", "key")
        with patch("canon.cli._credentials.load_credentials", return_value=None):
            _run_list(json_output=True, source_filter="env")

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert all(d["source"] == "env_var" for d in data)
        assert any(d["provider"] == "linear" for d in data)

    def test_with_env_vars_set(self, capsys, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("JIRA_HOST", "acme.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@acme.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "secret")
        with patch("canon.cli._credentials.load_credentials", return_value=None):
            _run_list(json_output=True)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        jira = next(d for d in data if d["provider"] == "jira")
        assert jira["status"] == "configured"
        assert jira["source"] == "env_var"


class TestRunTest:
    def test_no_configured_exits(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with (
            patch("canon.cli._credentials.load_credentials", return_value=None),
            pytest.raises(SystemExit) as exc_info,
        ):
            _run_test(provider=None, json_output=False)
        assert exc_info.value.code == 1

    def test_test_single_provider_json(self, capsys, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from canon.cli.integration_manager import IntegrationManager, TestResult

        mock_result = TestResult(provider="jira", ok=True, message="OK", latency_ms=42.0)
        with (
            patch("canon.cli._credentials.load_credentials", return_value=None),
            patch.object(IntegrationManager, "test_connection", return_value=mock_result),
        ):
            _run_test(provider="jira", json_output=True)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) == 1
        assert data[0]["provider"] == "jira"
        assert data[0]["ok"] is True


class TestRunIntegrations:
    def test_dispatch_no_subcommand(self, capsys):
        """No subcommand prints usage and exits 1."""
        import argparse

        args = argparse.Namespace(int_command=None)
        with pytest.raises(SystemExit) as exc_info:
            from canon.cli.integrations_cmd import run_integrations

            run_integrations(args)
        assert exc_info.value.code == 1
