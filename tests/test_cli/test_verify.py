"""Tests for canon verify command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from canon.cli.verify import _check_ac, _extract_keywords, run_verify

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

- [ ] Username validation with regex
- [x] Password hashing with bcrypt
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
    # Create src dir for grep
    (tmp_path / "src").mkdir()
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    return tmp_path


class TestExtractKeywords:
    def test_extracts_meaningful_words(self):
        kws = _extract_keywords("Username validation with regex patterns")
        assert "username" in kws
        assert "validation" in kws
        assert "regex" in kws
        # "with" should be filtered
        assert "with" not in kws

    def test_limits_to_five(self):
        kws = _extract_keywords("a b c one two three four five six seven eight")
        assert len(kws) <= 5

    def test_strips_backticks(self):
        kws = _extract_keywords("`parse_spec()` function works correctly")
        assert "parse_spec()" in kws or "parse_spec" in [k.rstrip("()") for k in kws]


class TestCheckAc:
    def test_likely_when_found(self, tmp_path: Path):
        _setup(tmp_path)
        (tmp_path / "src" / "validation.py").write_text("def username_validator(): pass")
        result = _check_ac(tmp_path, "Username validation with regex")
        assert result == "likely"

    def test_not_started_when_missing(self, tmp_path: Path):
        _setup(tmp_path)
        result = _check_ac(tmp_path, "Blockchain integration for payments")
        assert result == "not_started"


class TestRunVerify:
    def test_shows_unchecked_acs(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        with patch("canon.cli.verify._grep_codebase", return_value=False):
            run_verify(root=tmp_path)
        output = capsys.readouterr().out
        assert "Username validation" in output
        assert "Password hashing" not in output  # Already checked

    def test_all_checked(self, tmp_path: Path, capsys):
        spec = """\
---
title: Done Spec
status: active
owner: dev
team: t
---

## 1. Feature
<!-- specwright:system:1 status:done -->

### Acceptance Criteria

- [x] Everything done
"""
        (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
        specs = tmp_path / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "done.md").write_text(spec)
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "frontend" / "src").mkdir(parents=True, exist_ok=True)

        run_verify(root=tmp_path)
        output = capsys.readouterr().out
        assert "All ACs are checked" in output

    def test_no_specs(self, tmp_path: Path, capsys):
        run_verify(root=tmp_path)
        output = capsys.readouterr().out
        assert "No spec files found" in output

    def test_section_filter(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        with patch("canon.cli.verify._grep_codebase", return_value=False):
            run_verify(section="1", root=tmp_path)
        output = capsys.readouterr().out
        assert "Login Flow" in output
