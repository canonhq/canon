"""Tests for the canon export command."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from canon.cli._local import load_local_config, parse_all_local_specs
from canon.cli.export import (
    CSV_FIELDS,
    ExportRow,
    _format_realization,
    _render_csv,
    _render_json,
    build_rows,
    run_export,
)
from canon.parser.models import RealizationRef

CANON_YAML = """\
team: platform
specs:
  doc_paths:
    - "docs/specs/*.md"
"""


SPEC = """\
---
title: Auth Hardening
status: in_progress
owner: alice
team: platform
---

## 1. OAuth Login
<!-- canon:system:1 status:done -->

### Acceptance Criteria

- [x] OAuth client registered
<!-- canon:realized-in:PR#42 file:src/auth/oauth.py:10-30 -->
- [x] Login route handles callback
<!-- canon:realized-in:PR#42 file:src/auth/routes.py:55 -->

## 2. Session Management
<!-- canon:system:2 status:in_progress -->

### Acceptance Criteria

- [ ] Sessions persist across restarts
- [ ] Token refresh endpoint
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "CANON.yaml").write_text(CANON_YAML)
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / "docs" / "specs" / "auth.md").write_text(SPEC)
    return tmp_path


# ─── Helpers ─────────────────────────────────────────────


class TestFormatRealization:
    def test_pr_with_lines(self):
        ref = RealizationRef(pr_number=42, file_path="src/foo.py", lines="10-30")
        assert _format_realization(ref) == "PR#42 src/foo.py:10-30"

    def test_pr_without_lines(self):
        ref = RealizationRef(pr_number=99, file_path="src/foo.py")
        assert _format_realization(ref) == "PR#99 src/foo.py"

    def test_audit_source(self):
        ref = RealizationRef(file_path="src/foo.py", lines="42")
        assert _format_realization(ref) == "audit src/foo.py:42"


class TestBuildRows:
    def test_one_row_per_ac(self, repo: Path):
        config = load_local_config(repo)
        docs = parse_all_local_specs(repo, config)
        rows = list(build_rows(docs, repo))
        # 4 ACs total: 2 in section 1, 2 in section 2
        assert len(rows) == 4

    def test_row_fields_populated(self, repo: Path):
        config = load_local_config(repo)
        docs = parse_all_local_specs(repo, config)
        rows = list(build_rows(docs, repo))
        first = rows[0]
        assert first.spec == "docs/specs/auth.md"
        assert first.spec_title == "Auth Hardening"
        assert first.spec_status == "in_progress"
        assert first.owner == "alice"
        assert first.team == "platform"
        assert first.section_id == "1-oauth-login"
        assert first.section_status == "done"
        assert first.ac_checked is True
        assert first.realizations == ["PR#42 src/auth/oauth.py:10-30"]

    def test_unchecked_ac_has_no_realizations(self, repo: Path):
        config = load_local_config(repo)
        docs = parse_all_local_specs(repo, config)
        rows = list(build_rows(docs, repo))
        unchecked = [r for r in rows if not r.ac_checked]
        assert len(unchecked) == 2
        for row in unchecked:
            assert row.realizations == []


# ─── JSON rendering ──────────────────────────────────────


class TestRenderJson:
    def test_shape(self):
        rows = [
            ExportRow(
                spec="docs/specs/auth.md",
                spec_title="Auth",
                spec_status="in_progress",
                owner="alice",
                team="platform",
                section_id="1-foo",
                section_number="1",
                section_title="Foo",
                section_status="done",
                ac_text="OAuth client registered",
                ac_checked=True,
                ac_line=10,
                realizations=["PR#42 src/auth.py:10-30"],
                spec_last_modified="2026-04-11T12:00:00+00:00",
            )
        ]
        payload = json.loads(_render_json(rows))
        assert payload["schema_version"] == 1
        assert "generated_at" in payload
        assert payload["summary"]["rows"] == 1
        assert payload["summary"]["specs"] == 1
        assert payload["summary"]["checked"] == 1
        assert payload["summary"]["unchecked"] == 0
        assert len(payload["rows"]) == 1
        assert payload["rows"][0]["ac_text"] == "OAuth client registered"

    def test_empty(self):
        payload = json.loads(_render_json([]))
        assert payload["summary"]["rows"] == 0
        assert payload["rows"] == []


# ─── CSV rendering ───────────────────────────────────────


class TestRenderCsv:
    def test_header_and_row(self):
        rows = [
            ExportRow(
                spec="docs/specs/auth.md",
                spec_title="Auth Hardening",
                spec_status="done",
                owner="alice",
                team="platform",
                section_id="1-oauth",
                section_number="1",
                section_title="OAuth",
                section_status="done",
                ac_text="OAuth client registered",
                ac_checked=True,
                ac_line=10,
                realizations=["PR#42 src/auth.py:10-30", "PR#42 src/routes.py:55"],
                spec_last_modified="2026-04-11T12:00:00+00:00",
            )
        ]
        out = _render_csv(rows)
        reader = csv.DictReader(io.StringIO(out))
        assert reader.fieldnames == CSV_FIELDS
        records = list(reader)
        assert len(records) == 1
        rec = records[0]
        assert rec["spec"] == "docs/specs/auth.md"
        assert rec["ac_checked"] == "true"
        assert "PR#42 src/auth.py:10-30" in rec["realizations"]
        assert ";" in rec["realizations"]  # joined with semicolons

    def test_empty_writes_header_only(self):
        out = _render_csv([])
        reader = csv.DictReader(io.StringIO(out))
        assert reader.fieldnames == CSV_FIELDS
        assert list(reader) == []


# ─── Integration ─────────────────────────────────────────


class TestRunExport:
    def test_json_to_stdout(self, repo: Path, capsys):
        run_export(root=repo)
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["summary"]["rows"] == 4

    def test_csv_to_stdout(self, repo: Path, capsys):
        run_export(export_format="csv", root=repo)
        out = capsys.readouterr().out
        reader = csv.DictReader(io.StringIO(out))
        rows = list(reader)
        assert len(rows) == 4

    def test_writes_to_file(self, repo: Path, tmp_path: Path):
        out_file = tmp_path / "report.json"
        run_export(output=str(out_file), root=repo)
        assert out_file.exists()
        payload = json.loads(out_file.read_text())
        assert payload["summary"]["rows"] == 4

    def test_spec_filter(self, repo: Path, capsys):
        # Add a second spec
        (repo / "docs" / "specs" / "other.md").write_text(
            "---\ntitle: Other\nstatus: draft\nowner: b\nteam: c\n---\n\n## 1. X\n<!-- canon:system:1 status:todo -->\n\n- [ ] foo\n"
        )
        run_export(spec="auth", root=repo)
        payload = json.loads(capsys.readouterr().out)
        # Filter should narrow to the auth spec only
        spec_paths = {r["spec"] for r in payload["rows"]}
        assert spec_paths == {"docs/specs/auth.md"}

    def test_no_specs(self, tmp_path: Path, capsys):
        run_export(root=tmp_path)
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["rows"] == 0
