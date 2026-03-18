"""Tests to validate plugin skill files are well-formed."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PLUGIN_DIR = Path(__file__).parent.parent.parent / "plugin"
SKILLS_DIR = PLUGIN_DIR / "skills"

EXPECTED_SKILLS = [
    "canon-audit",
    "canon-context",
    "canon-task",
    "canon-verify",
    "canon-new",
    "canon-review",
    "canon-status",
    "canon-plan",
    "canon-update",
]


class TestPluginStructure:
    def test_plugin_json_exists(self):
        assert (PLUGIN_DIR / ".claude-plugin" / "plugin.json").exists()

    def test_mcp_json_exists(self):
        assert (PLUGIN_DIR / ".mcp.json").exists()

    def test_settings_exists(self):
        assert (PLUGIN_DIR / "settings.json").exists()


class TestSkillFiles:
    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
    def test_skill_exists(self, skill_name: str):
        skill_path = SKILLS_DIR / skill_name / "SKILL.md"
        assert skill_path.exists(), f"Missing skill: {skill_name}"

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
    def test_skill_has_frontmatter(self, skill_name: str):
        skill_path = SKILLS_DIR / skill_name / "SKILL.md"
        content = skill_path.read_text()

        # Should start with ---
        assert content.startswith("---"), f"{skill_name} missing YAML frontmatter"

        # Extract frontmatter
        parts = content.split("---", 2)
        assert len(parts) >= 3, f"{skill_name} malformed frontmatter"

        fm = yaml.safe_load(parts[1])
        assert isinstance(fm, dict), f"{skill_name} frontmatter is not a dict"

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
    def test_skill_has_required_fields(self, skill_name: str):
        skill_path = SKILLS_DIR / skill_name / "SKILL.md"
        content = skill_path.read_text()
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])

        assert "name" in fm, f"{skill_name} missing 'name'"
        assert "description" in fm, f"{skill_name} missing 'description'"
        assert "allowed-tools" in fm, f"{skill_name} missing 'allowed-tools'"

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
    def test_skill_name_matches_directory(self, skill_name: str):
        skill_path = SKILLS_DIR / skill_name / "SKILL.md"
        content = skill_path.read_text()
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])

        assert fm["name"] == skill_name, (
            f"Skill name '{fm['name']}' doesn't match directory '{skill_name}'"
        )

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
    def test_skill_has_markdown_body(self, skill_name: str):
        skill_path = SKILLS_DIR / skill_name / "SKILL.md"
        content = skill_path.read_text()
        parts = content.split("---", 2)
        body = parts[2].strip()

        assert len(body) > 50, f"{skill_name} body is too short"
        assert body.startswith("#"), f"{skill_name} body should start with a heading"

    def test_all_expected_skills_present(self):
        actual_skills = sorted(d.name for d in SKILLS_DIR.iterdir() if d.is_dir())
        assert actual_skills == sorted(EXPECTED_SKILLS)
