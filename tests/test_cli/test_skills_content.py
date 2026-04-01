"""Tests to validate plugin skill files are well-formed."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PLUGIN_DIR = Path(__file__).parent.parent.parent / "plugin"
SKILLS_DIR = PLUGIN_DIR / "skills"

EXPECTED_SKILLS = [
    "canon-audit",
    "canon-branch",
    "canon-context",
    "canon-implement",
    "canon-meta",
    "canon-new",
    "canon-plan",
    "canon-review",
    "canon-status",
    "canon-task",
    "canon-update",
    "canon-verify",
    "canon-worktree",
]

EXPECTED_AGENTS = [
    "canon-reviewer",
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


AGENTS_DIR = PLUGIN_DIR / "agents"


class TestAgentFiles:
    @pytest.mark.parametrize("agent_name", EXPECTED_AGENTS)
    def test_agent_exists(self, agent_name: str):
        agent_path = AGENTS_DIR / agent_name / "AGENT.md"
        assert agent_path.exists(), f"Missing agent: {agent_name}"

    @pytest.mark.parametrize("agent_name", EXPECTED_AGENTS)
    def test_agent_has_frontmatter(self, agent_name: str):
        agent_path = AGENTS_DIR / agent_name / "AGENT.md"
        content = agent_path.read_text()

        assert content.startswith("---"), f"{agent_name} missing YAML frontmatter"
        parts = content.split("---", 2)
        assert len(parts) >= 3, f"{agent_name} malformed frontmatter"

        fm = yaml.safe_load(parts[1])
        assert isinstance(fm, dict), f"{agent_name} frontmatter is not a dict"

    @pytest.mark.parametrize("agent_name", EXPECTED_AGENTS)
    def test_agent_has_required_fields(self, agent_name: str):
        agent_path = AGENTS_DIR / agent_name / "AGENT.md"
        content = agent_path.read_text()
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])

        assert "name" in fm, f"{agent_name} missing 'name'"
        assert "description" in fm, f"{agent_name} missing 'description'"
        assert "tools" in fm, f"{agent_name} missing 'tools'"

    @pytest.mark.parametrize("agent_name", EXPECTED_AGENTS)
    def test_agent_name_matches_directory(self, agent_name: str):
        agent_path = AGENTS_DIR / agent_name / "AGENT.md"
        content = agent_path.read_text()
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])

        assert fm["name"] == agent_name, (
            f"Agent name '{fm['name']}' doesn't match directory '{agent_name}'"
        )

    @pytest.mark.parametrize("agent_name", EXPECTED_AGENTS)
    def test_agent_has_markdown_body(self, agent_name: str):
        agent_path = AGENTS_DIR / agent_name / "AGENT.md"
        content = agent_path.read_text()
        parts = content.split("---", 2)
        body = parts[2].strip()

        assert len(body) > 50, f"{agent_name} body is too short"
        assert body.startswith("#"), f"{agent_name} body should start with a heading"

    def test_all_expected_agents_present(self):
        actual_agents = sorted(d.name for d in AGENTS_DIR.iterdir() if d.is_dir())
        assert actual_agents == sorted(EXPECTED_AGENTS)


HOOKS_DIR = PLUGIN_DIR / "hooks"


class TestHookFiles:
    def test_hooks_json_exists(self):
        assert (HOOKS_DIR / "hooks.json").exists()

    def test_hooks_json_valid(self):
        import json

        content = (HOOKS_DIR / "hooks.json").read_text()
        data = json.loads(content)
        assert "hooks" in data
        assert isinstance(data["hooks"], dict)

    def test_hooks_json_has_session_start(self):
        import json

        data = json.loads((HOOKS_DIR / "hooks.json").read_text())
        assert "SessionStart" in data["hooks"]

    def test_session_start_script_exists(self):
        assert (HOOKS_DIR / "session-start.sh").exists()

    def test_session_start_script_is_bash(self):
        content = (HOOKS_DIR / "session-start.sh").read_text()
        assert content.startswith("#!/usr/bin/env bash")

    def test_session_start_mentions_all_skills(self):
        """SessionStart hook should list all Canon skills for discovery."""
        content = (HOOKS_DIR / "session-start.sh").read_text()
        # Derive from EXPECTED_SKILLS so adding a skill forces updating the hook
        for skill_name in EXPECTED_SKILLS:
            colon_form = skill_name.replace("canon-", "canon:")
            assert colon_form in content, f"SessionStart hook missing skill: {colon_form}"

    def test_session_start_has_no_specs_fallback(self):
        """SessionStart hook should have adjusted messaging when no specs exist."""
        content = (HOOKS_DIR / "session-start.sh").read_text()
        assert "No specs found" in content or "no specs" in content.lower()

    def test_hooks_reference_existing_scripts(self):
        """All command hooks in hooks.json should reference scripts that exist."""
        import json

        data = json.loads((HOOKS_DIR / "hooks.json").read_text())
        for _event, matchers in data["hooks"].items():
            for matcher in matchers:
                for hook in matcher.get("hooks", []):
                    if hook.get("type") == "command":
                        cmd = hook["command"]
                        # Extract script path (handle ${CLAUDE_PLUGIN_ROOT} substitution)
                        cmd = cmd.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_DIR))
                        # Find the .sh file in the command
                        for part in cmd.split():
                            if part.endswith(".sh"):
                                script = Path(part)
                                assert script.exists(), f"Hook references missing script: {part}"


class TestSkillCrossReferences:
    """Verify skills reference each other correctly."""

    def test_canon_task_mentions_implement(self):
        content = (SKILLS_DIR / "canon-task" / "SKILL.md").read_text()
        assert "canon-implement" in content or "canon:implement" in content

    def test_canon_implement_mentions_task(self):
        content = (SKILLS_DIR / "canon-implement" / "SKILL.md").read_text()
        assert "canon-task" in content or "canon:task" in content

    def test_canon_implement_mentions_branch(self):
        content = (SKILLS_DIR / "canon-implement" / "SKILL.md").read_text()
        assert "canon-branch" in content or "canon:branch" in content

    def test_canon_implement_mentions_verify(self):
        content = (SKILLS_DIR / "canon-implement" / "SKILL.md").read_text()
        assert "canon verify" in content or "canon-verify" in content

    def test_canon_plan_mentions_implement(self):
        content = (SKILLS_DIR / "canon-plan" / "SKILL.md").read_text()
        assert "canon-implement" in content or "canon:implement" in content

    def test_canon_branch_mentions_verify(self):
        content = (SKILLS_DIR / "canon-branch" / "SKILL.md").read_text()
        assert "canon verify" in content or "canon-verify" in content

    def test_canon_meta_lists_all_skills(self):
        """The meta skill should reference every other Canon skill."""
        content = (SKILLS_DIR / "canon-meta" / "SKILL.md").read_text()
        for skill in EXPECTED_SKILLS:
            if skill == "canon-meta":
                continue
            assert skill in content, f"canon-meta missing reference to {skill}"

    def test_canon_worktree_mentions_next_skills(self):
        content = (SKILLS_DIR / "canon-worktree" / "SKILL.md").read_text()
        assert "canon:task" in content or "canon-task" in content
        assert "canon:implement" in content or "canon-implement" in content

    def test_canon_verify_documents_gate_mode(self):
        content = (SKILLS_DIR / "canon-verify" / "SKILL.md").read_text()
        assert "--gate" in content
        assert "Gate Mode" in content or "gate mode" in content


class TestReadmeCompleteness:
    """Verify README lists all skills and agents."""

    def test_readme_mentions_all_skills(self):
        content = (PLUGIN_DIR / "README.md").read_text()
        for skill in EXPECTED_SKILLS:
            colon_form = skill.replace("canon-", "canon:")
            assert colon_form in content, f"README missing skill: {colon_form}"

    def test_readme_mentions_all_agents(self):
        content = (PLUGIN_DIR / "README.md").read_text()
        for agent in EXPECTED_AGENTS:
            assert agent in content, f"README missing agent: {agent}"


class TestWorkflowChains:
    """Verify the documented workflow chains are supported by skill content."""

    def test_new_feature_chain(self):
        """canon-plan → canon-worktree → canon-implement → canon-branch"""
        # plan mentions worktree or implementation plan handoff
        plan = (SKILLS_DIR / "canon-plan" / "SKILL.md").read_text()
        assert "canon-implement" in plan or "canon:implement" in plan

        # implement mentions worktree
        impl = (SKILLS_DIR / "canon-implement" / "SKILL.md").read_text()
        assert "worktree" in impl.lower()

        # implement mentions branch
        assert "canon-branch" in impl or "canon:branch" in impl

        # branch handles merge/PR
        branch = (SKILLS_DIR / "canon-branch" / "SKILL.md").read_text()
        assert "merge" in branch.lower()
        assert "PR" in branch or "pr create" in branch.lower()

    def test_single_task_chain(self):
        """canon-context → canon-task → canon-verify"""
        task = (SKILLS_DIR / "canon-task" / "SKILL.md").read_text()
        assert "canon verify" in task or "canon-verify" in task

    def test_audit_chain(self):
        """canon-audit → canon-status"""
        audit = (SKILLS_DIR / "canon-audit" / "SKILL.md").read_text()
        assert "canon-status" in audit or "canon:status" in audit or "status" in audit.lower()

    def test_spec_drift_chain(self):
        """canon-update → canon-status"""
        update = (SKILLS_DIR / "canon-update" / "SKILL.md").read_text()
        assert "status" in update.lower()
