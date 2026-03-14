"""Tests for canon done command."""

from __future__ import annotations

from pathlib import Path

import pytest

from canon.cli.done import run_done

SAMPLE_SPEC = """\
---
title: Auth Spec
status: active
owner: dev
team: platform
---

## 1. Login Flow
<!-- specwright:system:1 status:in_progress -->

### Acceptance Criteria

- [x] Username validation

## 2. OAuth
<!-- specwright:system:2 status:done -->

### Acceptance Criteria

- [x] Google OAuth
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


class TestRunDone:
    def test_marks_done(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_done(section_id="1", root=tmp_path)
        output = capsys.readouterr().out
        assert "done" in output

        content = (tmp_path / "docs" / "specs" / "auth.md").read_text()
        assert "status:done" in content

    def test_already_done(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        run_done(section_id="2", root=tmp_path)
        output = capsys.readouterr().out
        assert "already done" in output

    def test_section_not_found(self, tmp_path: Path):
        _setup(tmp_path)
        with pytest.raises(SystemExit):
            run_done(section_id="nonexistent", root=tmp_path)

    def test_warns_from_draft(self, tmp_path: Path, capsys):
        spec = """\
---
title: Test
status: active
owner: dev
team: t
---

## 1. Feature
<!-- specwright:system:1 status:draft -->
"""
        (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
        specs = tmp_path / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "test.md").write_text(spec)

        run_done(section_id="1", root=tmp_path)
        output = capsys.readouterr().out
        assert "Warning" in output
        content = (specs / "test.md").read_text()
        assert "status:done" in content
