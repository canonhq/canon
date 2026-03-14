"""Tests for canon start command."""

from __future__ import annotations

from pathlib import Path

import pytest

from canon.cli.start import run_start

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

## 2. OAuth
<!-- specwright:system:2 status:in_progress -->

### Acceptance Criteria

- [ ] Google OAuth
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


class TestRunStart:
    def test_starts_todo_section(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_start(section_id="1", root=tmp_path)
        output = capsys.readouterr().out
        assert "in_progress" in output

        # Verify markdown was updated
        content = (tmp_path / "docs" / "specs" / "auth.md").read_text()
        assert "status:in_progress" in content

    def test_already_in_progress(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_start(section_id="2", root=tmp_path)
        output = capsys.readouterr().out
        assert "already in_progress" in output

    def test_section_not_found(self, tmp_path: Path):
        _setup(tmp_path)
        with pytest.raises(SystemExit):
            run_start(section_id="nonexistent", root=tmp_path)

    def test_inserts_status_when_missing(self, tmp_path: Path, capsys):
        """When no status comment exists, insert one."""
        spec = """\
---
title: Test
status: active
owner: dev
team: t
---

## 1. Feature
"""
        (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
        specs = tmp_path / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "test.md").write_text(spec)

        run_start(section_id="1", root=tmp_path)
        content = (specs / "test.md").read_text()
        assert "status:in_progress" in content
