"""Tests for canon.cli.login — authentication flows."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from canon.cli.login import (
    _detect_org,
    _login_api_key,
    _login_token,
    register,
    run_login,
)


class TestRegister:
    def test_registers_login_subcommand(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["login"])
        assert args.command == "login"

    def test_accepts_all_options(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(
            [
                "login",
                "--api-key",
                "key123",
                "--token",
                "tok",
                "--api-url",
                "https://example.com",
                "--server",
                "https://server.com",
                "--org",
                "my-org",
            ]
        )
        assert args.api_key == "key123"
        assert args.token == "tok"
        assert args.api_url == "https://example.com"
        assert args.server == "https://server.com"
        assert args.org == "my-org"


class TestLoginToken:
    def test_stores_token_with_explicit_api_url(self, capsys):
        with patch("canon.cli._credentials.save_credentials") as mock_save:
            _login_token(token="my_token", api_url="https://custom.co", server="", org="acme")

        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved["method"] == "token"
        assert saved["token"] == "my_token"
        assert saved["api_url"] == "https://custom.co"
        assert saved["org"] == "acme"

        output = capsys.readouterr().out
        assert "https://custom.co" in output

    def test_defaults_api_url_when_not_provided(self, capsys):
        with patch("canon.cli._credentials.save_credentials") as mock_save:
            _login_token(token="tok", api_url="", server="", org="")

        saved = mock_save.call_args[0][0]
        assert saved["api_url"] == "https://api.canonhq.co"

    def test_falls_back_to_server_if_no_api_url(self, capsys):
        with patch("canon.cli._credentials.save_credentials") as mock_save:
            _login_token(token="tok", api_url="", server="https://my-server.co", org="")

        saved = mock_save.call_args[0][0]
        assert saved["api_url"] == "https://my-server.co"


class TestLoginApiKey:
    def test_successful_validation(self, capsys):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"org": "test-org"}
        mock_client.raw_get.return_value = mock_resp

        with patch("canon.cli._credentials.save_credentials") as mock_save:
            _login_api_key(mock_client, "api_key_123")

        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved["method"] == "api_key"
        assert saved["api_key"] == "api_key_123"
        assert saved["org"] == "test-org"

        output = capsys.readouterr().out
        assert "test-org" in output

    def test_failed_validation_exits(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_client.raw_get.return_value = mock_resp

        with pytest.raises(SystemExit):
            _login_api_key(mock_client, "bad_key")


class TestRunLogin:
    def test_token_path_skips_platform_client(self):
        with patch("canon.cli.login._login_token") as mock_token:
            run_login(token="ci_tok", api_url="https://x.co", server="", org="")

        mock_token.assert_called_once_with(
            token="ci_tok", api_url="https://x.co", server="", org=""
        )

    def test_api_key_path(self):
        with (
            patch("canon.cli._platform.PlatformClient"),
            patch("canon.cli.login._login_api_key") as mock_api_key,
        ):
            run_login(api_key="key123", server="")

        mock_api_key.assert_called_once()

    def test_device_flow_default(self):
        with (
            patch("canon.cli._platform.PlatformClient"),
            patch("canon.cli.login._detect_org", return_value="detected") as mock_det,
            patch("canon.cli.login._login_device") as mock_device,
        ):
            run_login(api_key="", server="", org="")

        mock_det.assert_called_once()
        mock_device.assert_called_once()
        assert mock_device.call_args.kwargs["org"] == "detected"

    def test_explicit_org_skips_detection(self):
        with (
            patch("canon.cli._platform.PlatformClient"),
            patch("canon.cli.login._detect_org") as mock_det,
            patch("canon.cli.login._login_device") as mock_device,
        ):
            run_login(api_key="", server="", org="explicit-org")

        mock_det.assert_not_called()
        assert mock_device.call_args.kwargs["org"] == "explicit-org"


class TestDetectOrg:
    def test_from_canon_yaml(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "CANON.yaml").write_text("team: yaml-org\n")

        result = _detect_org()

        assert result == "yaml-org"
        assert "yaml-org" in capsys.readouterr().out

    def test_from_git_remote(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        # No CANON.yaml

        with patch("canon.cli._local.resolve_github_remote", return_value=("git-org", "repo")):
            result = _detect_org()

        assert result == "git-org"

    def test_returns_empty_when_nothing_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with patch("canon.cli._local.resolve_github_remote", return_value=None):
            result = _detect_org()

        assert result == ""

    def test_handles_missing_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with patch(
            "canon.cli._local.resolve_github_remote",
            side_effect=FileNotFoundError("cwd gone"),
        ):
            result = _detect_org()

        assert result == ""
