"""Tests for canon dashboard command."""

from __future__ import annotations

import json
from pathlib import Path

from canon.cli.dashboard import run_dashboard

SPEC_ACTIVE = """\
---
title: Active Spec
status: active
owner: dev
team: platform
---

## 1. Done Section
<!-- canon:system:1 status:done -->

### Acceptance Criteria

- [x] First AC
- [x] Second AC

## 2. In Progress Section
<!-- canon:system:2 status:in_progress -->

### Acceptance Criteria

- [x] Started
- [ ] Not done yet

## 3. Todo Section
<!-- canon:system:3 status:todo -->

### Acceptance Criteria

- [ ] Planned work
"""

SPEC_COMPLETE = """\
---
title: Complete Spec
status: done
owner: dev
team: platform
---

## 1. Only Section
<!-- canon:system:1 status:done -->

### Acceptance Criteria

- [x] All done
"""

SAMPLE_CONFIG = """\
team: platform
specs:
  doc_paths:
    - "docs/specs/*.md"
"""


def _setup(tmp_path: Path, *, complete_only: bool = False) -> Path:
    (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    if not complete_only:
        (specs / "active.md").write_text(SPEC_ACTIVE)
    (specs / "complete.md").write_text(SPEC_COMPLETE)
    return tmp_path


class TestRunDashboard:
    def test_shows_coverage(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_dashboard(root=tmp_path)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "Coverage" in output
        assert "specs" in output

    def test_shows_active_tasks(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_dashboard(root=tmp_path)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "Active Tasks" in output
        assert "In Progress Section" in output or "Todo Section" in output

    def test_shows_incomplete_specs(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_dashboard(root=tmp_path)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "Incomplete Specs" in output

    def test_all_complete(self, tmp_path: Path, capsys):
        _setup(tmp_path, complete_only=True)
        exit_code = run_dashboard(root=tmp_path)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "all caught up" in output.lower() or "complete" in output.lower()

    def test_json_output(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_dashboard(json_output=True, root=tmp_path)
        output = capsys.readouterr().out
        data = json.loads(output)
        assert exit_code == 0
        assert "coverage" in data
        assert data["coverage"]["specs"] == 2
        assert data["coverage"]["ac_total"] > 0
        assert "tasks" in data
        assert "incomplete_specs" in data

    def test_no_specs(self, tmp_path: Path, capsys):
        (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
        exit_code = run_dashboard(root=tmp_path)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "No spec files found" in output

    def test_json_no_specs(self, tmp_path: Path, capsys):
        (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
        exit_code = run_dashboard(json_output=True, root=tmp_path)
        output = capsys.readouterr().out
        data = json.loads(output)
        assert exit_code == 0
        assert data["coverage"] == {}
