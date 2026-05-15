"""Tests for canon.cli.logout — clear credentials and revoke session."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from canon.cli.logout import register, run_logout


class TestRegister:
    def test_registers_logout_subcommand(self):
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["logout"])
        assert args.command == "logout"


class TestRunLogout:
    def test_clears_credentials_when_no_cred(self, capsys):
        with (
            patch("canon.cli._credentials.load_credentials", return_value=None),
            patch("canon.cli._credentials.clear_credentials") as mock_clear,
        ):
            run_logout()

        mock_clear.assert_called_once()
        assert "Logged out" in capsys.readouterr().out

    def test_clears_credentials_without_revoke_for_api_key(self, capsys):
        cred = {"method": "api_key", "api_key": "test_key"}
        with (
            patch("canon.cli._credentials.load_credentials", return_value=cred),
            patch("canon.cli._credentials.clear_credentials") as mock_clear,
        ):
            run_logout()

        mock_clear.assert_called_once()
        assert "Logged out" in capsys.readouterr().out

    def test_revokes_oauth_session_before_clearing(self, capsys):
        cred = {
            "method": "oauth",
            "refresh_token": "rt_123",
            "access_token": "at_456",
        }
        mock_client = MagicMock()

        with (
            patch("canon.cli._credentials.load_credentials", return_value=cred),
            patch("canon.cli._credentials.clear_credentials") as mock_clear,
            patch("canon.cli._platform.PlatformClient", return_value=mock_client),
        ):
            run_logout()

        mock_client.post.assert_called_once_with("/auth/revoke", json={"refresh_token": "rt_123"})
        mock_client.close.assert_called_once()
        mock_clear.assert_called_once()

    def test_clears_even_if_revoke_fails(self, capsys):
        cred = {
            "method": "oauth",
            "refresh_token": "rt_123",
        }
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("network error")

        with (
            patch("canon.cli._credentials.load_credentials", return_value=cred),
            patch("canon.cli._credentials.clear_credentials") as mock_clear,
            patch("canon.cli._platform.PlatformClient", return_value=mock_client),
        ):
            run_logout()

        # Credentials should still be cleared even though revoke failed
        mock_clear.assert_called_once()
        assert "Logged out" in capsys.readouterr().out

    def test_skips_revoke_when_no_refresh_token(self, capsys):
        cred = {"method": "oauth", "access_token": "at_456"}
        with (
            patch("canon.cli._credentials.load_credentials", return_value=cred),
            patch("canon.cli._credentials.clear_credentials") as mock_clear,
            patch("canon.cli._platform.PlatformClient") as mock_platform_cls,
        ):
            run_logout()

        # PlatformClient should not be instantiated when there's no refresh_token
        mock_platform_cls.assert_not_called()
        mock_clear.assert_called_once()
