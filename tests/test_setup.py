"""Tests for shared setup module."""

from __future__ import annotations

import json
from pathlib import Path

from canon.setup import (
    create_mcp_json,
    create_spec_template,
    create_specwright_yaml,
    install_skills,
    list_setup_files,
)


class TestCreateSpecwrightYaml:
    def test_default_yaml(self):
        result = create_specwright_yaml()
        assert "specs:" in result
        assert "agents:" in result
        assert "doc_paths:" in result
        assert "# team: my-team" in result
        assert "ticket_systems:" in result
        assert "system: github" in result

    def test_with_team(self):
        result = create_specwright_yaml(team="platform")
        assert "team: platform" in result
        assert "# team:" not in result

    def test_with_ticket_system(self):
        result = create_specwright_yaml(ticket_system="jira")
        assert "system: jira" in result

    def test_with_all_options(self):
        result = create_specwright_yaml(team="payments", ticket_system="linear")
        assert "team: payments" in result
        assert "system: linear" in result

    def test_with_project_key(self):
        result = create_specwright_yaml(project_key="Acme/widgets")
        assert 'project: "Acme/widgets"' in result
        assert "# project:" not in result

    def test_without_project_key(self):
        result = create_specwright_yaml()
        assert '# project: "Owner/repo"' in result

    def test_with_custom_doc_paths(self):
        result = create_specwright_yaml(doc_paths=["specs/*.md", "docs/*.md"])
        assert '"specs/*.md"' in result
        assert '"docs/*.md"' in result

    def test_default_doc_paths(self):
        result = create_specwright_yaml()
        assert '"docs/specs/*.md"' in result


class TestCreateSpecTemplate:
    def test_spec_template(self):
        result = create_spec_template("spec")
        assert "title:" in result
        assert "## 1. Background" in result

    def test_invalid_type(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown template type"):
            create_spec_template("invalid")


class TestListSetupFiles:
    def test_with_config(self):
        files = list_setup_files(has_config=True)
        assert len(files) == 1
        assert files[0].path == "docs/specs/_template.md"
        assert "title:" in files[0].content

    def test_without_config(self):
        files = list_setup_files(has_config=False)
        assert len(files) == 2
        paths = [f.path for f in files]
        assert "docs/specs/_template.md" in paths
        assert "CANON.yaml" in paths

    def test_passes_options_to_yaml(self):
        files = list_setup_files(team="backend", ticket_system="jira")
        yaml_file = next(f for f in files if f.path == "CANON.yaml")
        assert "team: backend" in yaml_file.content
        assert "system: jira" in yaml_file.content

    def test_passes_project_key(self):
        files = list_setup_files(project_key="Acme/widgets")
        yaml_file = next(f for f in files if f.path == "CANON.yaml")
        assert 'project: "Acme/widgets"' in yaml_file.content

    def test_passes_doc_paths(self):
        files = list_setup_files(doc_paths=["specs/*.md"])
        yaml_file = next(f for f in files if f.path == "CANON.yaml")
        assert '"specs/*.md"' in yaml_file.content


class TestCreateMcpJson:
    def test_creates_new_file(self, tmp_path: Path):
        assert create_mcp_json(tmp_path) == "created"
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert data["mcpServers"]["canon"]["command"] == "uvx"

    def test_merges_into_existing(self, tmp_path: Path):
        (tmp_path / ".mcp.json").write_text('{"mcpServers":{"other":{"command":"x"}}}')
        assert create_mcp_json(tmp_path) == "updated"
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert "other" in data["mcpServers"]
        assert "canon" in data["mcpServers"]

    def test_skips_if_already_present(self, tmp_path: Path):
        (tmp_path / ".mcp.json").write_text('{"mcpServers":{"canon":{"command":"existing"}}}')
        assert create_mcp_json(tmp_path) is None

    def test_bails_on_invalid_json(self, tmp_path: Path, capsys):
        (tmp_path / ".mcp.json").write_text("not json{{{")
        assert create_mcp_json(tmp_path) is None
        assert (tmp_path / ".mcp.json").read_text() == "not json{{{"
        assert "invalid JSON" in capsys.readouterr().out

    def test_handles_empty_file(self, tmp_path: Path):
        (tmp_path / ".mcp.json").write_text("")
        assert create_mcp_json(tmp_path) == "updated"
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert "canon" in data["mcpServers"]

    def test_bails_on_non_dict_json(self, tmp_path: Path, capsys):
        (tmp_path / ".mcp.json").write_text("[]")
        assert create_mcp_json(tmp_path) is None
        assert (tmp_path / ".mcp.json").read_text() == "[]"
        assert "not a JSON object" in capsys.readouterr().out


class TestInstallSkills:
    def test_installs_skills(self, tmp_path: Path):
        installed, skipped = install_skills(tmp_path)
        assert len(installed) > 0
        assert skipped == 0
        assert "canon-context" in installed
        skill_path = tmp_path / ".claude" / "skills" / "canon-context" / "SKILL.md"
        assert skill_path.exists()
        assert "canon-context" in skill_path.read_text()

    def test_skips_existing_skills(self, tmp_path: Path):
        dest = tmp_path / ".claude" / "skills" / "canon-context" / "SKILL.md"
        dest.parent.mkdir(parents=True)
        dest.write_text("customized by user")

        installed, skipped = install_skills(tmp_path)
        assert "canon-context" not in installed
        assert skipped >= 1
        assert dest.read_text() == "customized by user"

    def test_idempotent(self, tmp_path: Path):
        installed, _ = install_skills(tmp_path)
        second_installed, second_skipped = install_skills(tmp_path)
        assert len(installed) > 0
        assert len(second_installed) == 0
        assert second_skipped == len(installed)
