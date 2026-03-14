"""Tests for canon plan command."""

from __future__ import annotations

from pathlib import Path

import pytest

from canon.cli.plan import run_plan

SAMPLE_SPEC = """\
---
title: Auth Spec
status: active
owner: dev
team: platform
depends_on:
  - user-profile-spec
---

## 1. Login Flow
<!-- specwright:system:1 status:todo -->

### Acceptance Criteria

- [ ] Username validation
- [x] Password hashing

## 2. OAuth
<!-- specwright:system:2 status:in_progress -->

### Acceptance Criteria

- [ ] Google OAuth

## 3. Session
<!-- specwright:system:3 status:done -->

### Acceptance Criteria

- [x] Session management
"""

SAMPLE_CONFIG = """\
team: platform
specs:
  doc_paths:
    - "docs/specs/*.md"
"""


def _setup(tmp_path: Path) -> Path:
    (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "auth.md").write_text(SAMPLE_SPEC)
    return tmp_path


class TestRunPlan:
    def test_generates_plan(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_plan(spec_file="auth", root=tmp_path)
        output = capsys.readouterr().out
        assert "Task Plan: Auth Spec" in output
        assert "Login Flow" in output
        assert "OAuth" in output
        assert "Session" not in output  # done, not actionable

    def test_shows_dependencies(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_plan(spec_file="auth", root=tmp_path)
        output = capsys.readouterr().out
        assert "Dependencies" in output
        assert "user-profile-spec" in output

    def test_shows_ac_subtasks(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_plan(spec_file="auth", root=tmp_path)
        output = capsys.readouterr().out
        assert "Username validation" in output
        assert "[ ]" in output  # Unchecked AC
        assert "[x]" in output  # Checked AC

    def test_output_to_file(self, tmp_path: Path):
        _setup(tmp_path)
        out_file = tmp_path / "plan.md"
        run_plan(spec_file="auth", output=str(out_file), root=tmp_path)
        assert out_file.exists()
        content = out_file.read_text()
        assert "Task Plan" in content

    def test_spec_not_found(self, tmp_path: Path):
        _setup(tmp_path)
        with pytest.raises(SystemExit):
            run_plan(spec_file="nonexistent", root=tmp_path)

    def test_summary_section(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_plan(spec_file="auth", root=tmp_path)
        output = capsys.readouterr().out
        assert "Summary" in output
        assert "Actionable tasks: 2" in output
