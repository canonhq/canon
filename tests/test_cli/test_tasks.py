"""Tests for canon tasks command."""

from __future__ import annotations

from pathlib import Path

from canon.cli.tasks import run_tasks

SAMPLE_SPEC = """\
---
title: Auth Spec
status: active
owner: dev
team: platform
---

## 1. Login Flow
<!-- specwright:system:1 status:todo -->

### Acceptance Criteria

- [ ] Username validation
- [x] Password hashing

## 2. OAuth
<!-- specwright:system:2 status:in_progress -->
<!-- specwright:ticket:github:42 -->

### Acceptance Criteria

- [ ] Google OAuth
- [ ] GitHub OAuth

## 3. Done Feature
<!-- specwright:system:3 status:done -->

### Acceptance Criteria

- [x] Implemented
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


class TestRunTasks:
    def test_lists_active_tasks(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_tasks(root=tmp_path)
        output = capsys.readouterr().out
        assert "Login Flow" in output
        assert "OAuth" in output
        assert "Done Feature" not in output

    def test_status_filter(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_tasks(status="todo", root=tmp_path)
        output = capsys.readouterr().out
        assert "Login Flow" in output
        assert "OAuth" not in output

    def test_show_all(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_tasks(show_all=True, root=tmp_path)
        output = capsys.readouterr().out
        assert "Login Flow" in output
        assert "Done Feature" in output

    def test_spec_filter(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_tasks(spec="auth", root=tmp_path)
        output = capsys.readouterr().out
        assert "Login Flow" in output

    def test_no_specs(self, tmp_path: Path, capsys):
        run_tasks(root=tmp_path)
        output = capsys.readouterr().out
        assert "No spec files found" in output

    def test_shows_ac_progress(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_tasks(root=tmp_path)
        output = capsys.readouterr().out
        assert "1/2" in output  # Login Flow AC progress

    def test_shows_ticket_link(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_tasks(root=tmp_path)
        output = capsys.readouterr().out
        assert "github:42" in output
