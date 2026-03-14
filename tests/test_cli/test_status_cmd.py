"""Tests for canon status command."""

from __future__ import annotations

from pathlib import Path

from canon.cli.status_cmd import run_status

SAMPLE_SPEC = """\
---
title: Auth Spec
status: active
owner: dev
team: platform
---

## 1. Login Flow
<!-- specwright:system:1 status:done -->

### Acceptance Criteria

- [x] Username validation
- [x] Password hashing

## 2. OAuth
<!-- specwright:system:2 status:todo -->

### Acceptance Criteria

- [ ] Google OAuth
- [ ] GitHub OAuth
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


class TestRunStatus:
    def test_aggregate_dashboard(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_status(root=tmp_path)
        output = capsys.readouterr().out
        assert "Spec Coverage Dashboard" in output
        assert "Auth Spec" in output
        assert "2/4" in output  # ACs done

    def test_single_spec_detail(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_status(spec="auth", root=tmp_path)
        output = capsys.readouterr().out
        assert "Login Flow" in output
        assert "OAuth" in output
        assert "done" in output

    def test_no_specs(self, tmp_path: Path, capsys):
        run_status(root=tmp_path)
        output = capsys.readouterr().out
        assert "No spec files found" in output

    def test_spec_not_found(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_status(spec="nonexistent", root=tmp_path)
        output = capsys.readouterr().out
        assert "No spec matching" in output

    def test_coverage_percentage(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_status(root=tmp_path)
        output = capsys.readouterr().out
        assert "50%" in output  # 2/4 ACs = 50%
