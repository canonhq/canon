"""Tests for canon db CLI command."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from canon.cli.db import register, run_db


class TestRegister:
    def test_registers_db_parser(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["db", "upgrade"])
        assert args.command == "db"
        assert args.db_command == "upgrade"

    def test_upgrade_default_revision(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["db", "upgrade"])
        assert args.revision == "head"

    def test_upgrade_custom_revision(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["db", "upgrade", "--revision", "abc123"])
        assert args.revision == "abc123"

    def test_db_no_subcommand(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["db"])
        assert args.db_command is None


class TestRunDbUpgrade:
    def test_upgrade_success(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        mock_run_upgrade = MagicMock()
        mock_module = MagicMock()
        mock_module.run_upgrade = mock_run_upgrade
        args = argparse.Namespace(db_command="upgrade", revision="head")

        with patch.dict("sys.modules", {"canon.db.migrate": mock_module}):
            run_db(args)

        mock_run_upgrade.assert_called_once_with("postgresql://localhost/test", revision="head")

    def test_upgrade_custom_revision(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        mock_run_upgrade = MagicMock()
        mock_module = MagicMock()
        mock_module.run_upgrade = mock_run_upgrade
        args = argparse.Namespace(db_command="upgrade", revision="abc123")

        with patch.dict("sys.modules", {"canon.db.migrate": mock_module}):
            run_db(args)

        mock_run_upgrade.assert_called_once_with("postgresql://localhost/test", revision="abc123")

    def test_upgrade_missing_database_url(self, monkeypatch, capsys):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        args = argparse.Namespace(db_command="upgrade", revision="head")

        with pytest.raises(SystemExit) as exc_info:
            run_db(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "DATABASE_URL" in captured.err

    def test_upgrade_import_error(self, monkeypatch, capsys):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        args = argparse.Namespace(db_command="upgrade", revision="head")

        # Remove the module so the import fails
        with (
            patch.dict("sys.modules", {"canon.db.migrate": None}),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_db(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "cloud-only feature" in captured.err

    def test_upgrade_prints_success(self, monkeypatch, capsys):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        mock_module = MagicMock()
        args = argparse.Namespace(db_command="upgrade", revision="head")

        with patch.dict("sys.modules", {"canon.db.migrate": mock_module}):
            run_db(args)

        captured = capsys.readouterr()
        assert "Migrations applied successfully" in captured.out


class TestRunDbNoCommand:
    def test_no_subcommand_exits(self, capsys):
        args = argparse.Namespace(db_command=None)

        with pytest.raises(SystemExit) as exc_info:
            run_db(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Usage:" in captured.err

    def test_unknown_subcommand_exits(self, capsys):
        args = argparse.Namespace(db_command="unknown")

        with pytest.raises(SystemExit) as exc_info:
            run_db(args)

        assert exc_info.value.code == 1
