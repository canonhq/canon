"""Tests for the canon release-notes command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from canon.cli.release_notes import (
    CompletedSection,
    NewSpec,
    ReleaseNotes,
    RemovedSpec,
    _diff_sections,
    _realization_key,
    render_markdown,
    run_release_notes,
)
from canon.parser.models import RealizationRef
from canon.parser.parse import parse_spec

CANON_YAML = """\
team: platform
specs:
  doc_paths:
    - "docs/specs/*.md"
"""


SPEC_TODO = """\
---
title: Auth Hardening
status: in_progress
owner: alice
team: platform
---

# Auth Hardening

## 1. OAuth Login
<!-- canon:system:1 status:todo -->

### Acceptance Criteria

- [ ] OAuth client registered with provider
- [ ] Login route handles callback

## 2. Session Management
<!-- canon:system:2 status:in_progress -->

### Acceptance Criteria

- [ ] Sessions persist across restarts
"""


SPEC_DONE = """\
---
title: Auth Hardening
status: in_progress
owner: alice
team: platform
---

# Auth Hardening

## 1. OAuth Login
<!-- canon:system:1 status:done -->

### Acceptance Criteria

- [x] OAuth client registered with provider
<!-- canon:realized-in:PR#42 file:src/auth/oauth.py:10-30 -->
- [x] Login route handles callback
<!-- canon:realized-in:PR#42 file:src/auth/routes.py:55 -->

## 2. Session Management
<!-- canon:system:2 status:in_progress -->

### Acceptance Criteria

- [ ] Sessions persist across restarts
"""


def _git(repo: Path, *args: str) -> str:
    """Run a git command in the given repo and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.fixture
def repo_with_two_commits(tmp_path: Path) -> Path:
    """Create a tiny git repo with two commits and a tag at v0.1.0."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")

    (tmp_path / "CANON.yaml").write_text(CANON_YAML)
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / "docs" / "specs" / "auth.md").write_text(SPEC_TODO)

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "v0.1.0")
    _git(tmp_path, "tag", "v0.1.0")

    # Second commit: section 1 transitions to done with realization evidence
    (tmp_path / "docs" / "specs" / "auth.md").write_text(SPEC_DONE)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "complete oauth")

    return tmp_path


# ─── Helpers and small unit tests ─────────────────────────


class TestRealizationKey:
    def test_pr_with_lines(self):
        ref = RealizationRef(pr_number=42, file_path="src/foo.py", lines="10-30")
        assert _realization_key(ref) == "PR#42 src/foo.py:10-30"

    def test_pr_without_lines(self):
        ref = RealizationRef(pr_number=99, file_path="src/foo.py")
        assert _realization_key(ref) == "PR#99 src/foo.py"

    def test_audit_source(self):
        ref = RealizationRef(file_path="src/foo.py", lines="42")
        assert _realization_key(ref) == "audit src/foo.py:42"


class TestDiffSections:
    def test_detects_status_transition_to_done(self):
        from_doc = parse_spec(SPEC_TODO).document
        to_doc = parse_spec(SPEC_DONE).document
        completed = _diff_sections(from_doc, to_doc)

        assert len(completed) == 1
        c = completed[0]
        assert c.section_id == "1-oauth-login"
        assert c.previous_status == "todo"
        assert c.section_title == "OAuth Login"
        # Two new realization comments landed
        assert len(c.new_realizations) == 2
        assert any("oauth.py" in r for r in c.new_realizations)
        assert any("routes.py" in r for r in c.new_realizations)

    def test_skips_already_done(self):
        # Both sides done — no transition reported
        completed = _diff_sections(parse_spec(SPEC_DONE).document, parse_spec(SPEC_DONE).document)
        assert completed == []

    def test_no_transition_when_still_in_progress(self):
        # SPEC_TODO -> SPEC_TODO: nothing changed
        completed = _diff_sections(parse_spec(SPEC_TODO).document, parse_spec(SPEC_TODO).document)
        assert completed == []

    def test_new_section_already_done_counts_as_completed(self):
        # A section that didn't exist in `from` and is `done` in `to` is reported
        # with previous_status = "(new)"
        new_section_spec = (
            SPEC_DONE.rstrip()
            + "\n\n## 3. Brand New\n<!-- canon:system:3 status:done -->\n\n- [x] Done from the start\n"
        )
        completed = _diff_sections(
            parse_spec(SPEC_DONE).document, parse_spec(new_section_spec).document
        )
        new_secs = [c for c in completed if c.section_id == "3-brand-new"]
        assert len(new_secs) == 1
        assert new_secs[0].previous_status == "(new)"


# ─── Markdown rendering ──────────────────────────────────


class TestRenderMarkdown:
    def test_no_changes(self):
        notes = ReleaseNotes(from_ref="v0.1.0", to_ref="HEAD")
        text = render_markdown(notes)
        assert "No spec-level changes" in text

    def test_completed_section_rendered(self):
        notes = ReleaseNotes(
            from_ref="v0.1.0",
            to_ref="v0.2.0",
            completed=[
                CompletedSection(
                    spec="docs/specs/auth.md",
                    spec_title="Auth Hardening",
                    section_id="1-oauth-login",
                    section_number="1",
                    section_title="OAuth Login",
                    previous_status="todo",
                    new_realizations=["PR#42 src/auth/oauth.py:10-30"],
                )
            ],
        )
        text = render_markdown(notes)
        assert "v0.1.0" in text and "v0.2.0" in text
        assert "OAuth Login" in text
        assert "was: todo" in text
        assert "PR#42" in text
        assert "## Completed (1)" in text

    def test_new_specs_rendered(self):
        notes = ReleaseNotes(
            from_ref="v0.1.0",
            to_ref="v0.2.0",
            new_specs=[NewSpec(spec="docs/specs/new.md", title="New Feature", status="draft")],
        )
        text = render_markdown(notes)
        assert "## New specs (1)" in text
        assert "New Feature" in text

    def test_removed_specs_rendered(self):
        notes = ReleaseNotes(
            from_ref="v0.1.0",
            to_ref="v0.2.0",
            removed_specs=[RemovedSpec(spec="docs/specs/old.md", title="Sunset")],
        )
        text = render_markdown(notes)
        assert "## Removed specs (1)" in text


# ─── Integration tests via real git refs ─────────────────


class TestRunReleaseNotes:
    def test_detects_completed_section(self, repo_with_two_commits: Path, capsys):
        exit_code = run_release_notes(
            from_ref="v0.1.0",
            to_ref="HEAD",
            root=repo_with_two_commits,
        )
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "OAuth Login" in out
        assert "was: todo" in out

    def test_json_output_shape(self, repo_with_two_commits: Path, capsys):
        exit_code = run_release_notes(
            from_ref="v0.1.0",
            to_ref="HEAD",
            json_output=True,
            root=repo_with_two_commits,
        )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["schema_version"] == 1
        assert payload["from_ref"] == "v0.1.0"
        assert payload["to_ref"] == "HEAD"
        assert payload["summary"]["completed"] == 1
        assert payload["completed"][0]["section_id"] == "1-oauth-login"
        assert payload["completed"][0]["previous_status"] == "todo"
        assert len(payload["completed"][0]["new_realizations"]) == 2

    def test_missing_from_ref_returns_error(self, tmp_path: Path, capsys):
        # tmp_path is not a git repo and no --from given
        exit_code = run_release_notes(from_ref=None, to_ref="HEAD", root=tmp_path)
        assert exit_code == 2
        # Error message went to stderr
        captured = capsys.readouterr()
        assert (
            "could not detect a previous tag" in captured.err.lower()
            or "could not detect" in captured.err
        )

    def test_missing_from_ref_json_returns_error_payload(self, tmp_path: Path, capsys):
        exit_code = run_release_notes(from_ref=None, to_ref="HEAD", json_output=True, root=tmp_path)
        assert exit_code == 2
        payload = json.loads(capsys.readouterr().out)
        assert "error" in payload

    def test_output_writes_file(self, repo_with_two_commits: Path, tmp_path: Path):
        output_path = tmp_path / "release-notes.md"
        exit_code = run_release_notes(
            from_ref="v0.1.0",
            to_ref="HEAD",
            output=str(output_path),
            root=repo_with_two_commits,
        )
        assert exit_code == 0
        assert output_path.exists()
        content = output_path.read_text()
        assert "OAuth Login" in content

    def test_no_changes_between_identical_refs(self, repo_with_two_commits: Path, capsys):
        exit_code = run_release_notes(
            from_ref="HEAD",
            to_ref="HEAD",
            root=repo_with_two_commits,
        )
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "No spec-level changes" in out
