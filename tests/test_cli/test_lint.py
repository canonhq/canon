"""Tests for canon lint command."""

from __future__ import annotations

import json
from pathlib import Path

from canon.cli.lint import (
    _check_depends_on,
    _check_frontmatter,
    _check_section_numbering,
    _check_status_comments,
    _is_iso_date,
    run_lint,
)
from canon.parser.parse import parse_spec

SAMPLE_CONFIG = """\
team: platform
specs:
  doc_paths:
    - "docs/specs/*.md"
"""


VALID_SPEC = """\
---
title: Auth Hardening
status: in_progress
owner: alice
team: platform
created: 2026-04-01
updated: 2026-04-11
---

# Auth Hardening

## 1. Background

Context paragraph.

## 2. Requirements
<!-- canon:system:2 status:in_progress -->

### Acceptance Criteria

- [ ] Tokens are scoped per-org
- [x] JWTs use RS256 signing
"""


def _write_spec(root: Path, name: str, content: str) -> Path:
    (root / "CANON.yaml").write_text(SAMPLE_CONFIG)
    specs = root / "docs" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    path = specs / name
    path.write_text(content)
    return path


# ─── Unit tests for helpers ─────────────────────────────────


class TestIsIsoDate:
    def test_valid(self):
        assert _is_iso_date("2026-04-11")

    def test_invalid_format(self):
        assert not _is_iso_date("April 11, 2026")
        assert not _is_iso_date("2026/04/11")
        assert not _is_iso_date("2026-4-11")

    def test_empty(self):
        assert not _is_iso_date("")


class TestCheckFrontmatter:
    def test_valid_spec_has_no_issues(self):
        result = parse_spec(VALID_SPEC)
        issues = _check_frontmatter("auth.md", result.document)
        assert not issues

    def test_empty_title_is_error(self):
        spec = VALID_SPEC.replace("title: Auth Hardening", 'title: ""')
        result = parse_spec(spec)
        issues = _check_frontmatter("auth.md", result.document)
        assert any(i.rule == "frontmatter.title" and i.severity == "error" for i in issues)

    def test_empty_owner_is_warning(self):
        spec = VALID_SPEC.replace("owner: alice", 'owner: ""')
        result = parse_spec(spec)
        issues = _check_frontmatter("auth.md", result.document)
        assert any(i.rule == "frontmatter.owner" and i.severity == "warning" for i in issues)

    def test_bad_created_date_is_warning(self):
        spec = VALID_SPEC.replace("created: 2026-04-01", "created: April 1 2026")
        result = parse_spec(spec)
        issues = _check_frontmatter("auth.md", result.document)
        assert any(i.rule == "frontmatter.created" for i in issues)


class TestCheckSectionNumbering:
    def test_monotonic_sections_pass(self):
        result = parse_spec(VALID_SPEC)
        issues = _check_section_numbering("auth.md", result.document)
        assert not issues

    def test_out_of_order_sections_flagged(self):
        spec = """\
---
title: Bad
status: draft
owner: a
team: b
---

## 1. First
text

## 3. Third
text

## 2. Second
text
"""
        result = parse_spec(spec)
        issues = _check_section_numbering("bad.md", result.document)
        # 2 after 3 should trigger the rule
        assert any(i.rule == "section.numbering" for i in issues)


class TestCheckStatusComments:
    def test_valid_comment_no_issue(self):
        raw = "## 1. Foo\n<!-- canon:system:1 status:todo -->\n"
        issues = _check_status_comments("x.md", raw)
        assert not issues

    def test_unknown_keyword_flagged(self):
        raw = "## 1. Foo\n<!-- canon:systme:1 status:todo -->\n"
        issues = _check_status_comments("x.md", raw)
        assert any(i.rule == "comment.unknown" for i in issues)

    def test_specwright_legacy_valid(self):
        raw = "## 1. Foo\n<!-- specwright:system:1 status:todo -->\n"
        issues = _check_status_comments("x.md", raw)
        assert not issues

    def test_realized_in_valid(self):
        raw = "<!-- canon:realized-in:PR#42 file:src/foo.py -->\n"
        issues = _check_status_comments("x.md", raw)
        assert not issues

    def test_inline_code_span_ignored(self):
        # Documentation text that describes the comment syntax inside
        # backticks should not trip lint even when the wrapped text is
        # itself a malformed canon directive.
        raw = "Use the `<!-- canon:... -->` placeholder in your spec.\n"
        issues = _check_status_comments("x.md", raw)
        assert not issues

    def test_fenced_code_block_ignored(self):
        raw = "Example:\n```\n<!-- canon:systme:1 status:todo -->\n```\n"
        issues = _check_status_comments("x.md", raw)
        assert not issues

    def test_fenced_block_does_not_swallow_later_lines(self):
        # After a fenced block closes, regular lines should still be linted.
        raw = "Example:\n```\n<!-- canon:systme:1 status:todo -->\n```\n<!-- canon:oops:1 -->\n"
        issues = _check_status_comments("x.md", raw)
        assert len(issues) == 1
        assert issues[0].line == 5


class TestCheckDependsOn:
    def test_unresolved_depends_on_flagged(self, tmp_path: Path):
        spec_a = """\
---
title: A
status: draft
owner: a
team: b
depends_on: [ghost-spec]
---

## 1. Intro

Text.
"""
        path_a = _write_spec(tmp_path, "spec-a.md", spec_a)
        result_a = parse_spec(spec_a)
        issues = _check_depends_on([result_a.document], [path_a], tmp_path)
        assert any(i.rule == "depends_on.unresolved" for i in issues)

    def test_resolved_depends_on_passes(self, tmp_path: Path):
        spec_a = """\
---
title: A
status: draft
owner: a
team: b
depends_on: [spec-b]
---

## 1. Intro

Text.
"""
        spec_b = """\
---
title: B
status: draft
owner: a
team: b
---

## 1. Intro

Text.
"""
        path_a = _write_spec(tmp_path, "spec-a.md", spec_a)
        path_b = _write_spec(tmp_path, "spec-b.md", spec_b)
        result_a = parse_spec(spec_a)
        result_b = parse_spec(spec_b)
        issues = _check_depends_on(
            [result_a.document, result_b.document],
            [path_a, path_b],
            tmp_path,
        )
        assert not issues


# ─── Integration tests for run_lint ──────────────────────


class TestRunLint:
    def test_valid_spec_returns_zero(self, tmp_path: Path, capsys):
        _write_spec(tmp_path, "auth.md", VALID_SPEC)
        exit_code = run_lint(root=tmp_path)
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "0 error" in captured.out

    def test_no_specs_found_returns_zero(self, tmp_path: Path, capsys):
        (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        exit_code = run_lint(root=tmp_path)
        assert exit_code == 0

    def test_error_returns_one(self, tmp_path: Path, capsys):
        bad = VALID_SPEC.replace("title: Auth Hardening", 'title: ""')
        _write_spec(tmp_path, "auth.md", bad)
        exit_code = run_lint(root=tmp_path)
        assert exit_code == 1

    def test_warnings_as_errors(self, tmp_path: Path):
        warn_only = VALID_SPEC.replace("owner: alice", 'owner: ""')
        _write_spec(tmp_path, "auth.md", warn_only)
        assert run_lint(root=tmp_path) == 0
        assert run_lint(root=tmp_path, warnings_as_errors=True) == 1

    def test_json_output_shape(self, tmp_path: Path, capsys):
        _write_spec(tmp_path, "auth.md", VALID_SPEC)
        exit_code = run_lint(root=tmp_path, json_output=True)
        assert exit_code == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert "issues" in payload
        assert "summary" in payload
        assert payload["summary"]["files"] == 1
        assert payload["summary"]["errors"] == 0

    def test_spec_filter(self, tmp_path: Path, capsys):
        _write_spec(tmp_path, "auth.md", VALID_SPEC)
        _write_spec(tmp_path, "other.md", VALID_SPEC.replace("Auth Hardening", "Other"))
        exit_code = run_lint(root=tmp_path, spec="auth", json_output=True)
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["files"] == 1

    def test_unresolved_spec_filter_returns_error(self, tmp_path: Path):
        _write_spec(tmp_path, "auth.md", VALID_SPEC)
        exit_code = run_lint(root=tmp_path, spec="nonexistent")
        assert exit_code == 2

    def test_filter_resolves_depends_on_against_full_repo(self, tmp_path: Path, capsys):
        """A `--spec` filter must not false-positive on depends_on entries
        that point at other specs in the same repo. The filter narrows what
        gets reported but cross-file checks see the full spec set."""
        # spec_a depends on spec_b which exists outside the filter
        spec_a = """\
---
title: Spec A
status: draft
owner: alice
team: platform
depends_on: [spec-b]
---

## 1. Intro

Text.
"""
        spec_b = """\
---
title: Spec B
status: draft
owner: bob
team: platform
---

## 1. Intro

Text.
"""
        _write_spec(tmp_path, "spec-a.md", spec_a)
        _write_spec(tmp_path, "spec-b.md", spec_b)

        exit_code = run_lint(root=tmp_path, spec="spec-a", json_output=True)
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        # Filter narrows to one file
        assert payload["summary"]["files"] == 1
        # depends_on.unresolved should NOT fire because spec-b exists in the
        # full repo even though the filter excluded it from this run
        rules = {issue["rule"] for issue in payload["issues"]}
        assert "depends_on.unresolved" not in rules
