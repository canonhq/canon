"""Tests for CLI auth commands (login, logout, auth status)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from canon.cli import main


class TestLoginSubcommand:
    def test_login_registered(self):
        """Login subcommand is recognized and doesn't print help."""
        # Without a server to connect to, it will fail, but the subcommand
        # should be recognized (not exit code 1 from "no subcommand")
        with (
            patch("canon.cli.login.run_login") as mock_run,
        ):
            main(["login"])
            mock_run.assert_called_once_with(api_key="", token="", api_url="", server="", org="")

    def test_login_with_api_key(self):
        with patch("canon.cli.login.run_login") as mock_run:
            main(["login", "--api-key", "sw_test123"])
            mock_run.assert_called_once_with(
                api_key="sw_test123", token="", api_url="", server="", org=""
            )

    def test_login_with_server(self):
        with patch("canon.cli.login.run_login") as mock_run:
            main(["login", "--server", "http://localhost:3000"])
            mock_run.assert_called_once_with(
                api_key="", token="", api_url="", server="http://localhost:3000", org=""
            )

    def test_login_with_org(self):
        with patch("canon.cli.login.run_login") as mock_run:
            main(["login", "--org", "canonhq"])
            mock_run.assert_called_once_with(
                api_key="", token="", api_url="", server="", org="canonhq"
            )

    def test_login_with_token_non_interactive(self, tmp_path: Path):
        """--token writes credentials directly without contacting the backend."""
        from canon.cli import _credentials

        cred_file = tmp_path / "credentials.json"
        with (
            patch.object(_credentials, "_NEW_CONFIG_DIR", tmp_path),
            patch.object(_credentials, "_NEW_CRED_FILE", cred_file),
        ):
            main(["login", "--token", "ci_test_token", "--api-url", "https://canon.example/"])

        saved = json.loads(cred_file.read_text())
        assert saved["method"] == "token"
        assert saved["token"] == "ci_test_token"
        assert saved["api_url"] == "https://canon.example/"

    def test_login_token_defaults_api_url(self, tmp_path: Path):
        from canon.cli import _credentials

        cred_file = tmp_path / "credentials.json"
        with (
            patch.object(_credentials, "_NEW_CONFIG_DIR", tmp_path),
            patch.object(_credentials, "_NEW_CRED_FILE", cred_file),
        ):
            main(["login", "--token", "ci_test_token"])

        saved = json.loads(cred_file.read_text())
        assert saved["api_url"] == "https://api.canonhq.co"

    def test_login_device_flow_sends_org_in_body(self):
        """When --org is set, it's forwarded in the POST body to /auth/device/code."""
        from canon.cli.login import _login_device

        # Build a fake client that captures POSTs and short-circuits the polling loop.
        class _FakeResp:
            def __init__(self, status_code, data):
                self.status_code = status_code
                self._data = data

            def json(self):
                return self._data

        calls: list[tuple[str, dict]] = []

        class _FakeClient:
            def raw_post(self, path, json=None):
                calls.append((path, json or {}))
                if path == "/auth/device/code":
                    return _FakeResp(
                        200,
                        {
                            "device_code": "dc",
                            "user_code": "UC",
                            "verification_uri": "http://x",
                            "verification_uri_complete": "http://x",
                            "interval": 0,
                            "expires_in": 1,
                        },
                    )
                if path == "/auth/device/token":
                    return _FakeResp(
                        200,
                        {
                            "status": "approved",
                            "access_token": "at",
                            "refresh_token": "rt",
                            "expires_in": 3600,
                            "email": "u@e",
                            "org": "canonhq",
                        },
                    )
                return _FakeResp(500, {})

        with (
            patch("canon.cli._credentials.save_credentials"),
            patch("canon.cli.login.webbrowser.open"),
        ):
            _login_device(_FakeClient(), org="canonhq")

        assert calls[0] == ("/auth/device/code", {"org": "canonhq"})

    def test_login_device_flow_omits_org_when_absent(self):
        """No --org → empty body (preserves backwards compatibility)."""
        from canon.cli.login import _login_device

        class _FakeResp:
            def __init__(self, status_code, data):
                self.status_code = status_code
                self._data = data

            def json(self):
                return self._data

        calls: list[tuple[str, dict]] = []

        class _FakeClient:
            def raw_post(self, path, json=None):
                calls.append((path, json or {}))
                if path == "/auth/device/code":
                    return _FakeResp(
                        200,
                        {
                            "device_code": "dc",
                            "user_code": "UC",
                            "verification_uri": "http://x",
                            "verification_uri_complete": "http://x",
                            "interval": 0,
                            "expires_in": 1,
                        },
                    )
                return _FakeResp(
                    200,
                    {
                        "status": "approved",
                        "access_token": "at",
                        "refresh_token": "rt",
                        "expires_in": 3600,
                        "email": "",
                        "org": "",
                    },
                )

        with (
            patch("canon.cli._credentials.save_credentials"),
            patch("canon.cli.login.webbrowser.open"),
        ):
            _login_device(_FakeClient(), org="")

        assert calls[0] == ("/auth/device/code", {})


class TestLogoutSubcommand:
    def test_logout_clears_credentials(self, tmp_path: Path):
        cred_file = tmp_path / "credentials.json"
        cred_file.write_text(json.dumps({"method": "oauth"}))
        old_cred_file = tmp_path / "old_credentials.json"

        with (
            patch("canon.cli._credentials._NEW_CRED_FILE", cred_file),
            patch("canon.cli._credentials._OLD_CRED_FILE", old_cred_file),
        ):
            from canon.cli.logout import run_logout

            run_logout()

        assert not cred_file.exists()

    def test_logout_registered(self):
        with patch("canon.cli.logout.run_logout") as mock_run:
            main(["logout"])
            mock_run.assert_called_once()


class TestAuthStatusSubcommand:
    def test_auth_status_not_logged_in(self, capsys):
        with patch("canon.cli._credentials.load_credentials", return_value=None):
            from canon.cli.auth_cmd import run_auth_status

            run_auth_status()

        output = capsys.readouterr().out
        assert "Not logged in" in output

    def test_auth_status_oauth(self, capsys):
        cred = {
            "method": "oauth",
            "org": "my-org",
            "email": "user@example.com",
            "expires_at": time.time() + 7200,
        }
        with patch("canon.cli._credentials.load_credentials", return_value=cred):
            from canon.cli.auth_cmd import run_auth_status

            run_auth_status()

        output = capsys.readouterr().out
        assert "oauth" in output
        assert "my-org" in output
        assert "user@example.com" in output
        assert "valid" in output

    def test_auth_status_expired_with_refresh(self, capsys):
        cred = {
            "method": "oauth",
            "org": "my-org",
            "email": "user@example.com",
            "expires_at": time.time() - 100,
            "refresh_token": "rt-123",
        }
        with patch("canon.cli._credentials.load_credentials", return_value=cred):
            from canon.cli.auth_cmd import run_auth_status

            run_auth_status()

        output = capsys.readouterr().out
        assert "expired" in output
        assert "available" in output

    def test_auth_status_api_key(self, capsys):
        cred = {
            "method": "api_key",
            "api_key": "sw_longtestkey1234567890",
            "org": "test-org",
        }
        with patch("canon.cli._credentials.load_credentials", return_value=cred):
            from canon.cli.auth_cmd import run_auth_status

            run_auth_status()

        output = capsys.readouterr().out
        assert "api_key" in output
        assert "sw_" in output
        assert "7890" in output
        # Should not contain the full key
        assert "sw_longtestkey1234567890" not in output

    def test_auth_status_registered(self):
        with patch("canon.cli.auth_cmd.run_auth_status") as mock_run:
            main(["auth", "status"])
            mock_run.assert_called_once()


class TestDetectOrg:
    def test_returns_team_from_canon_yaml(self, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "CANON.yaml").write_text("team: acme\n")
        from canon.cli.login import _detect_org

        result = _detect_org()

        assert result == "acme"
        assert "acme" in capsys.readouterr().out

    def test_falls_back_to_git_remote(self, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from canon.cli.login import _detect_org

        with patch(
            "canon.cli._local.resolve_github_remote",
            return_value=("acme", "widgets"),
        ):
            result = _detect_org()

        assert result == "acme"
        assert "acme" in capsys.readouterr().out

    def test_returns_empty_when_no_sources(self, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from canon.cli.login import _detect_org

        with patch("canon.cli._local.resolve_github_remote", return_value=None):
            # Non-interactive (stdin not a tty in tests)
            result = _detect_org()

        assert result == ""

    def test_returns_empty_when_cwd_missing(self, tmp_path, monkeypatch):
        """FileNotFoundError from resolve_github_remote is handled."""
        monkeypatch.chdir(tmp_path)
        from canon.cli.login import _detect_org

        with patch(
            "canon.cli._local.resolve_github_remote",
            side_effect=FileNotFoundError("cwd deleted"),
        ):
            result = _detect_org()
        assert result == ""


class TestRunLoginAutoDetect:
    def test_auto_detects_when_org_omitted(self):
        """run_login with no --org falls back to auto-detection."""
        from canon.cli.login import run_login

        with (
            patch("canon.cli.login._detect_org", return_value="detected-org") as mock_det,
            patch("canon.cli.login._login_device") as mock_login,
            patch("canon.cli._platform.PlatformClient"),
        ):
            run_login(api_key="", server="", org="")

        mock_det.assert_called_once()
        # The detected org must be threaded into _login_device.
        assert mock_login.call_args.kwargs["org"] == "detected-org"

    def test_explicit_org_skips_auto_detect(self):
        """An explicit --org value overrides git auto-detection."""
        from canon.cli.login import run_login

        with (
            patch("canon.cli.login._detect_org_from_git") as mock_det,
            patch("canon.cli.login._login_device") as mock_login,
            patch("canon.cli._platform.PlatformClient"),
        ):
            run_login(api_key="", server="", org="explicit-org")

        mock_det.assert_not_called()
        assert mock_login.call_args.kwargs["org"] == "explicit-org"
