"""Tests for canon extension CLI command."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from canon.cli.extension_cmd import register, run_extension


class TestRegister:
    def test_registers_extension_parser(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["extension", "list"])
        assert args.command == "extension"
        assert args.ext_command == "list"

    def test_add_subcommand_args(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["extension", "add", "/some/path", "--dev"])
        assert args.source == "/some/path"
        assert args.dev is True

    def test_create_subcommand_args(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(
            [
                "extension",
                "create",
                "my-ext",
                "--skill",
                "--hook",
                "--author",
                "Test",
                "-o",
                "/out",
            ]
        )
        assert args.ext_id == "my-ext"
        assert args.skill is True
        assert args.hook is True
        assert args.command_ if hasattr(args, "command_") else True
        assert args.author == "Test"
        assert args.output == "/out"

    def test_search_subcommand_defaults(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["extension", "search"])
        assert args.query == ""
        assert args.tag is None
        assert args.category is None


class TestRunExtensionNoCommand:
    def test_no_subcommand_exits(self, capsys):
        args = argparse.Namespace(ext_command=None)
        with pytest.raises(SystemExit) as exc_info:
            run_extension(args)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Usage:" in captured.out

    def test_missing_ext_command_attr(self, capsys):
        """When ext_command attribute is missing entirely."""
        args = argparse.Namespace()
        with pytest.raises(SystemExit) as exc_info:
            run_extension(args)
        assert exc_info.value.code == 1


class TestRunAdd:
    def test_add_success(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        source = tmp_path / "my-ext"
        source.mkdir()

        mock_result = MagicMock()
        mock_result.ext_id = "my-ext"
        mock_result.version = "1.0.0"
        mock_result.installed_files = ["skills/foo.md"]
        mock_result.warnings = []

        args = argparse.Namespace(ext_command="add", source=str(source), dev=False)

        with patch(
            "canon.extensions.installer.install_extension",
            return_value=mock_result,
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "Installed extension 'my-ext'" in captured.out
        assert "1 file(s)" in captured.out

    def test_add_dev_mode(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        source = tmp_path / "my-ext"
        source.mkdir()

        mock_result = MagicMock()
        mock_result.ext_id = "my-ext"
        mock_result.version = "0.1.0"
        mock_result.installed_files = []
        mock_result.warnings = ["some warning"]

        args = argparse.Namespace(ext_command="add", source=str(source), dev=True)

        with patch(
            "canon.extensions.installer.install_extension",
            return_value=mock_result,
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "dev mode (symlinked)" in captured.out
        assert "Note: some warning" in captured.out

    def test_add_error(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(ext_command="add", source="/nonexistent", dev=False)

        with (
            patch(
                "canon.extensions.installer.install_extension",
                side_effect=FileNotFoundError("not found"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err


class TestRunRemove:
    def test_remove_success(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(ext_command="remove", ext_id="my-ext")

        with patch(
            "canon.extensions.installer.uninstall_extension",
            return_value=["file1.md", "file2.md"],
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "Removed extension 'my-ext'" in captured.out
        assert "2 file(s)" in captured.out

    def test_remove_not_found(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(ext_command="remove", ext_id="missing")

        with (
            patch(
                "canon.extensions.installer.uninstall_extension",
                side_effect=KeyError("not installed"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1


class TestRunList:
    def test_list_empty(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        mock_registry = MagicMock()
        mock_registry.extensions = {}
        args = argparse.Namespace(ext_command="list")

        with patch(
            "canon.extensions.registry.load_registry",
            return_value=mock_registry,
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "No extensions installed" in captured.out

    def test_list_with_extensions(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        entry = MagicMock()
        entry.version = "1.2.0"
        entry.enabled = True
        entry.dev_mode = True
        entry.installed_files = ["a.md", "b.md"]
        entry.source_path = "/src/my-ext"

        mock_registry = MagicMock()
        mock_registry.extensions = {"my-ext": entry}
        args = argparse.Namespace(ext_command="list")

        with patch(
            "canon.extensions.registry.load_registry",
            return_value=mock_registry,
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "my-ext" in captured.out
        assert "v1.2.0" in captured.out
        assert "enabled" in captured.out
        assert "(dev)" in captured.out
        assert "Source: /src/my-ext" in captured.out


class TestRunCreate:
    def test_create_success(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            ext_command="create",
            ext_id="new-ext",
            skill=True,
            command=False,
            hook=False,
            adapter=False,
            author="Test Author",
            output=str(tmp_path / "out"),
        )

        with patch(
            "canon.extensions.template.scaffold_extension",
            return_value=["canon-extension.yml", "skills/main.md"],
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "Created extension 'new-ext'" in captured.out
        assert "2 file(s) created" in captured.out

    def test_create_already_exists(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            ext_command="create",
            ext_id="existing",
            skill=False,
            command=False,
            hook=False,
            adapter=False,
            author="",
            output=None,
        )

        with (
            patch(
                "canon.extensions.template.scaffold_extension",
                side_effect=FileExistsError("already exists"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1


class TestRunValidate:
    def test_validate_pass(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        mock_manifest = MagicMock()
        mock_manifest.extension.name = "My Ext"
        mock_manifest.extension.id = "my-ext"
        mock_manifest.extension.version = "1.0.0"
        mock_manifest.requires.canon_version = ">=1.0"
        mock_manifest.provides.skills = []
        mock_manifest.provides.commands = [MagicMock()]
        mock_manifest.provides.adapters = []
        mock_manifest.provides.hooks = []
        mock_manifest.provides.mcp_tools = []
        mock_manifest.provides.agents = []

        args = argparse.Namespace(ext_command="validate", source=str(tmp_path))

        with (
            patch(
                "canon.extensions.manifest.load_manifest",
                return_value=mock_manifest,
            ),
            patch(
                "canon.extensions.manifest.validate_file_references",
                return_value=[],
            ),
            patch(
                "canon.extensions.installer.get_canon_version",
                return_value="1.50.0",
            ),
            patch(
                "canon.extensions.manifest.check_canon_version_compat",
                return_value=True,
            ),
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "Validation passed" in captured.out
        assert "1 command(s)" in captured.out

    def test_validate_manifest_not_found(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(ext_command="validate", source=str(tmp_path))

        with (
            patch(
                "canon.extensions.manifest.load_manifest",
                side_effect=FileNotFoundError("no manifest"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1

    def test_validate_with_errors(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        mock_manifest = MagicMock()
        mock_manifest.extension.name = "Bad Ext"
        mock_manifest.extension.id = "bad-ext"
        mock_manifest.extension.version = "0.1.0"
        mock_manifest.requires.canon_version = ">=99.0"
        mock_manifest.provides.skills = []
        mock_manifest.provides.commands = []
        mock_manifest.provides.adapters = []
        mock_manifest.provides.hooks = []
        mock_manifest.provides.mcp_tools = []
        mock_manifest.provides.agents = []

        args = argparse.Namespace(ext_command="validate", source=str(tmp_path))

        with (
            patch(
                "canon.extensions.manifest.load_manifest",
                return_value=mock_manifest,
            ),
            patch(
                "canon.extensions.manifest.validate_file_references",
                return_value=["missing file: skills/foo.md"],
            ),
            patch(
                "canon.extensions.installer.get_canon_version",
                return_value="1.50.0",
            ),
            patch(
                "canon.extensions.manifest.check_canon_version_compat",
                return_value=False,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "2 error(s) found" in captured.err


class TestRunSearch:
    def test_search_no_results(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            ext_command="search", query="nonexistent", tag=None, category=None
        )

        with patch(
            "canon.extensions.catalog.search_catalogs",
            return_value=[],
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "No extensions found" in captured.out

    def test_search_with_results(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        results = [
            {
                "id": "canon-jira",
                "version": "1.0.0",
                "verified": True,
                "bundled": False,
                "category": "sync",
                "description": "Jira integration",
                "tags": ["jira", "tickets"],
            }
        ]
        args = argparse.Namespace(ext_command="search", query="jira", tag=None, category=None)

        with patch(
            "canon.extensions.catalog.search_catalogs",
            return_value=results,
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "Found 1 extension(s)" in captured.out
        assert "canon-jira" in captured.out
        assert "[verified]" in captured.out
        assert "Tags: jira, tickets" in captured.out

    def test_search_error(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(ext_command="search", query="q", tag=None, category=None)

        with (
            patch(
                "canon.extensions.catalog.search_catalogs",
                side_effect=RuntimeError("network error"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error searching catalogs" in captured.err


class TestRunInfo:
    def test_info_not_found(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(ext_command="info", ext_id="missing")

        mock_registry = MagicMock()
        mock_registry.extensions = {}

        with (
            patch(
                "canon.extensions.catalog.get_extension_info",
                return_value=None,
            ),
            patch(
                "canon.extensions.registry.load_registry",
                return_value=mock_registry,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1

    def test_info_found(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        ext_data = {
            "id": "my-ext",
            "name": "My Extension",
            "version": "2.0.0",
            "author": "Alice",
            "category": "sync",
            "description": "Does things",
            "repository": "https://github.com/x/y",
            "tags": ["tag1"],
            "verified": True,
            "bundled": False,
        }
        mock_registry = MagicMock()
        mock_registry.extensions = {}
        args = argparse.Namespace(ext_command="info", ext_id="my-ext")

        with (
            patch(
                "canon.extensions.catalog.get_extension_info",
                return_value=ext_data,
            ),
            patch(
                "canon.extensions.registry.load_registry",
                return_value=mock_registry,
            ),
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "My Extension" in captured.out
        assert "2.0.0" in captured.out
        assert "Alice" in captured.out
        assert "Verified:    Yes" in captured.out
        assert "Installed:   No" in captured.out


class TestRunUpdate:
    def test_update_no_args_exits(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        mock_registry = MagicMock()
        mock_registry.extensions = {}
        args = argparse.Namespace(ext_command="update", ext_id=None, update_all=False)

        with (
            patch(
                "canon.extensions.registry.load_registry",
                return_value=mock_registry,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1

    def test_update_not_installed(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        mock_registry = MagicMock()
        mock_registry.extensions = {}
        args = argparse.Namespace(ext_command="update", ext_id="missing", update_all=False)

        with (
            patch(
                "canon.extensions.registry.load_registry",
                return_value=mock_registry,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1

    def test_update_dev_mode_skips(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        entry = MagicMock()
        entry.dev_mode = True
        mock_registry = MagicMock()
        mock_registry.extensions = {"my-ext": entry}
        args = argparse.Namespace(ext_command="update", ext_id="my-ext", update_all=False)

        with patch(
            "canon.extensions.registry.load_registry",
            return_value=mock_registry,
        ):
            run_extension(args)

        captured = capsys.readouterr()
        assert "dev mode" in captured.out


class TestRunEnableDisable:
    def test_enable_success(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(ext_command="enable", ext_id="my-ext")

        with patch("canon.extensions.installer.enable_extension"):
            run_extension(args)

        captured = capsys.readouterr()
        assert "Enabled extension 'my-ext'" in captured.out

    def test_enable_not_found(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(ext_command="enable", ext_id="missing")

        with (
            patch(
                "canon.extensions.installer.enable_extension",
                side_effect=KeyError("not installed"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1

    def test_disable_success(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(ext_command="disable", ext_id="my-ext")

        with patch("canon.extensions.installer.disable_extension"):
            run_extension(args)

        captured = capsys.readouterr()
        assert "Disabled extension 'my-ext'" in captured.out

    def test_disable_not_found(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(ext_command="disable", ext_id="missing")

        with (
            patch(
                "canon.extensions.installer.disable_extension",
                side_effect=KeyError("not installed"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_extension(args)

        assert exc_info.value.code == 1
