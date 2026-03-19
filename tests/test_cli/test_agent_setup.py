"""Tests for canon setup --agent command."""

from __future__ import annotations

from pathlib import Path

from canon.cli.agent_setup import (
    CANON_MARKER_END,
    CANON_MARKER_START,
    SUPPORTED_PLATFORMS,
    generate_agent_config,
)


class TestGenerateAgentConfig:
    def test_creates_claude_config(self, tmp_path: Path):
        result = generate_agent_config(tmp_path, "claude")
        assert "Created .claude/CLAUDE.md" in result
        content = (tmp_path / ".claude" / "CLAUDE.md").read_text()
        assert CANON_MARKER_START in content
        assert CANON_MARKER_END in content
        assert "Canon" in content
        assert "MCP" in content

    def test_creates_cursor_config(self, tmp_path: Path):
        result = generate_agent_config(tmp_path, "cursor")
        assert "Created .cursorrules" in result
        content = (tmp_path / ".cursorrules").read_text()
        assert CANON_MARKER_START in content
        assert "Canon CLI" in content  # Cursor uses CLI, not MCP

    def test_creates_copilot_config(self, tmp_path: Path):
        result = generate_agent_config(tmp_path, "copilot")
        assert "Created .github/copilot-instructions.md" in result
        assert (tmp_path / ".github" / "copilot-instructions.md").exists()

    def test_creates_codex_config(self, tmp_path: Path):
        result = generate_agent_config(tmp_path, "codex")
        assert "Created AGENTS.md" in result
        content = (tmp_path / "AGENTS.md").read_text()
        assert "MCP" in content  # Codex supports MCP

    def test_creates_gemini_config(self, tmp_path: Path):
        result = generate_agent_config(tmp_path, "gemini")
        assert "Created GEMINI.md" in result
        content = (tmp_path / "GEMINI.md").read_text()
        assert "MCP" in content

    def test_all_platforms_supported(self):
        assert set(SUPPORTED_PLATFORMS) == {"claude", "cursor", "copilot", "codex", "gemini"}

    def test_generated_files_under_30_lines(self, tmp_path: Path):
        for platform in SUPPORTED_PLATFORMS:
            generate_agent_config(tmp_path, platform, force=True)

        for platform in SUPPORTED_PLATFORMS:
            from canon.cli.agent_setup import PLATFORM_CONFIG

            rel_path = PLATFORM_CONFIG[platform]
            content = (tmp_path / rel_path).read_text()
            line_count = len(content.strip().splitlines())
            assert line_count < 30, f"{platform} config has {line_count} lines (max 30)"

    def test_generated_files_include_canon_marker(self, tmp_path: Path):
        for platform in SUPPORTED_PLATFORMS:
            generate_agent_config(tmp_path, platform, force=True)
            from canon.cli.agent_setup import PLATFORM_CONFIG

            rel_path = PLATFORM_CONFIG[platform]
            content = (tmp_path / rel_path).read_text()
            assert CANON_MARKER_START in content
            assert CANON_MARKER_END in content

    def test_generated_files_reference_canon_yaml(self, tmp_path: Path):
        for platform in SUPPORTED_PLATFORMS:
            generate_agent_config(tmp_path, platform, force=True)
            from canon.cli.agent_setup import PLATFORM_CONFIG

            rel_path = PLATFORM_CONFIG[platform]
            content = (tmp_path / rel_path).read_text()
            assert "CANON.yaml" in content

    def test_unknown_platform_returns_error(self, tmp_path: Path):
        result = generate_agent_config(tmp_path, "vim")
        assert "Unknown platform" in result

    def test_updates_existing_canon_block(self, tmp_path: Path):
        # First create
        generate_agent_config(tmp_path, "claude")
        file_path = tmp_path / ".claude" / "CLAUDE.md"

        # Prepend user content
        original = file_path.read_text()
        file_path.write_text("# My Custom Config\n\nCustom stuff here.\n\n" + original)

        # Re-generate should replace only Canon block
        result = generate_agent_config(tmp_path, "claude")
        assert "Updated Canon block" in result

        updated = file_path.read_text()
        assert "My Custom Config" in updated
        assert "Custom stuff here" in updated
        assert updated.count(CANON_MARKER_START) == 1

    def test_refuses_overwrite_without_force(self, tmp_path: Path):
        # Create a file without Canon marker
        file_path = tmp_path / ".cursorrules"
        file_path.write_text("My existing cursor rules\n")

        result = generate_agent_config(tmp_path, "cursor")
        assert "--force" in result
        assert "already exists" in result

        # Original content preserved
        assert file_path.read_text() == "My existing cursor rules\n"

    def test_appends_with_force(self, tmp_path: Path):
        # Create a file without Canon marker
        file_path = tmp_path / ".cursorrules"
        file_path.write_text("My existing cursor rules\n")

        result = generate_agent_config(tmp_path, "cursor", force=True)
        assert "Appended" in result

        content = file_path.read_text()
        assert "My existing cursor rules" in content
        assert CANON_MARKER_START in content

    def test_no_spec_content_in_generated_files(self, tmp_path: Path):
        """Generated files reference CANON.yaml and tools, not spec content."""
        for platform in SUPPORTED_PLATFORMS:
            generate_agent_config(tmp_path, platform, force=True)
            from canon.cli.agent_setup import PLATFORM_CONFIG

            rel_path = PLATFORM_CONFIG[platform]
            content = (tmp_path / rel_path).read_text()
            # Should not contain actual spec content
            assert "acceptance_criteria" not in content.lower()
            assert "section_number" not in content.lower()
