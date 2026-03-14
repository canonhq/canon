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
            mock_run.assert_called_once_with(api_key="", server="")

    def test_login_with_api_key(self):
        with patch("canon.cli.login.run_login") as mock_run:
            main(["login", "--api-key", "sw_test123"])
            mock_run.assert_called_once_with(api_key="sw_test123", server="")

    def test_login_with_server(self):
        with patch("canon.cli.login.run_login") as mock_run:
            main(["login", "--server", "http://localhost:3000"])
            mock_run.assert_called_once_with(api_key="", server="http://localhost:3000")


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
