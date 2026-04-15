"""Tests for `canon ide-config` CLI subcommand."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_cmd(cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "canon", "ide-config", "--json"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestIdeConfigDefaults:
    def test_missing_canon_yaml_returns_defaults(self, tmp_path: Path):
        rc, out, _ = run_cmd(tmp_path)
        assert rc == 0
        data = json.loads(out)
        assert data["auto_context"]["enabled"] is True
        assert data["auto_context"]["on_session_start"] is True
        assert data["auto_verify"]["enabled"] is True
        assert data["ai_exposure"]["default"] == "full"

    def test_empty_canon_yaml_returns_defaults(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("")
        rc, out, _ = run_cmd(tmp_path)
        assert rc == 0
        data = json.loads(out)
        assert data["auto_context"]["max_specs"] == 5

    def test_missing_ide_section_returns_defaults(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text(
            "team: alpha\nspecs:\n  doc_paths:\n    - docs/specs/*.md\n"
        )
        rc, out, _ = run_cmd(tmp_path)
        assert rc == 0
        data = json.loads(out)
        assert data["auto_context"]["on_session_start"] is True


class TestIdeConfigPopulated:
    def test_full_ide_section(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("""\
ide:
  auto_context:
    enabled: true
    on_session_start: false
    on_prompt: true
    max_specs: 3
  auto_verify:
    enabled: false
    on_stop: false
    on_commit: false
  ai_exposure:
    default: metadata
    restricted_tags:
      - security
      - pricing
""")
        rc, out, _ = run_cmd(tmp_path)
        assert rc == 0
        data = json.loads(out)
        assert data["auto_context"]["on_session_start"] is False
        assert data["auto_context"]["max_specs"] == 3
        assert data["auto_verify"]["enabled"] is False
        assert data["ai_exposure"]["default"] == "metadata"
        assert "security" in data["ai_exposure"]["restricted_tags"]


class TestIdeConfigErrors:
    def test_malformed_yaml_emits_defaults(self, tmp_path: Path):
        (tmp_path / "CANON.yaml").write_text("ide: [this is not valid yaml")
        rc, out, _ = run_cmd(tmp_path)
        # Either parser tolerates it or emits warning + defaults; rc must be 0
        assert rc == 0
        data = json.loads(out)
        assert "auto_context" in data
