"""Tests for canon search command."""

from __future__ import annotations

import json
from pathlib import Path

from canon.cli.search import run_search

SPEC_AUTH = """\
---
title: Auth Spec
status: active
owner: dev
team: platform
---

## 1. Login Flow
<!-- canon:system:1 status:done -->

### Acceptance Criteria

- [x] Username validation
- [x] Password hashing

## 2. OAuth Integration
<!-- canon:system:2 status:todo -->

### Acceptance Criteria

- [ ] Google OAuth support
- [ ] GitHub OAuth support
"""

SPEC_BILLING = """\
---
title: Billing Spec
status: draft
owner: dev
team: platform
---

## 1. Stripe Integration
<!-- canon:system:1 status:in_progress -->

### Acceptance Criteria

- [ ] Payment processing
- [x] Invoice generation
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
    (specs / "auth.md").write_text(SPEC_AUTH)
    (specs / "billing.md").write_text(SPEC_BILLING)
    return tmp_path


class TestRunSearch:
    def test_finds_matching_sections(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_search(query="OAuth", root=tmp_path)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "OAuth" in output
        assert "Auth Spec" in output

    def test_no_results_returns_1(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_search(query="nonexistent_xyz_term", root=tmp_path)
        assert exit_code == 1

    def test_status_filter(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_search(query="OAuth", status="done", root=tmp_path)
        # OAuth section is status:todo, not done — should return no results
        assert exit_code == 1

    def test_spec_filter(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_search(query="Integration", spec="billing.md", root=tmp_path)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "Billing Spec" in output

    def test_json_output(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_search(query="OAuth", json_output=True, root=tmp_path)
        output = capsys.readouterr().out
        data = json.loads(output)
        assert exit_code == 0
        assert data["count"] > 0
        assert len(data["results"]) == data["count"]
        assert data["results"][0]["spec"] == "Auth Spec"

    def test_json_no_results(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_search(query="nonexistent", json_output=True, root=tmp_path)
        output = capsys.readouterr().out
        data = json.loads(output)
        assert exit_code == 1
        assert data["count"] == 0
        assert data["results"] == []

    def test_no_specs_found(self, tmp_path: Path, capsys):
        (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
        exit_code = run_search(query="anything", root=tmp_path)
        assert exit_code == 1

    def test_multi_term_relevance_ranking(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        exit_code = run_search(query="OAuth GitHub", json_output=True, root=tmp_path)
        output = capsys.readouterr().out
        data = json.loads(output)
        assert exit_code == 0
        # Section with both terms should rank higher
        assert data["results"][0]["relevance"] >= data["results"][-1]["relevance"]
