"""Tests for the spec matcher."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from issue_triage.matcher import _parse_spec_summary, load_spec_summaries


@pytest.fixture
def tmp_specs(tmp_path):
    """Create a temporary specs directory with fixture specs."""
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)

    # Valid spec
    (specs_dir / "feature-a.md").write_text("""\
---
title: "Feature A"
status: draft
owner: user1
---

# Feature A

Overview of feature A.

## 1. Background

Why this exists.

## 2. Requirements

### 2.1 Functional Requirements

Something.

### Acceptance Criteria

- [ ] Criterion one
""")

    # Another spec
    (specs_dir / "feature-b.md").write_text("""\
---
title: "Feature B"
status: done
owner: user2
---

# Feature B

## 1. Background

## 2. Design

## 3. Rollout
""")

    # Template (should be skipped)
    (specs_dir / "_template.md").write_text("""\
---
title: "Template"
status: draft
---

# Template
""")

    return specs_dir


class TestLoadSpecSummaries:
    def test_loads_valid_specs(self, tmp_specs):
        summaries = load_spec_summaries(tmp_specs)
        assert len(summaries) == 2  # _template.md skipped
        titles = {s["title"] for s in summaries}
        assert titles == {"Feature A", "Feature B"}

    def test_skips_templates(self, tmp_specs):
        summaries = load_spec_summaries(tmp_specs)
        for s in summaries:
            assert not Path(s["path"]).name.startswith("_")

    def test_extracts_status(self, tmp_specs):
        summaries = load_spec_summaries(tmp_specs)
        by_title = {s["title"]: s for s in summaries}
        assert by_title["Feature A"]["status"] == "draft"
        assert by_title["Feature B"]["status"] == "done"

    def test_extracts_sections(self, tmp_specs):
        summaries = load_spec_summaries(tmp_specs)
        by_title = {s["title"]: s for s in summaries}
        # Feature A has Background, Requirements, Functional Requirements
        sections_a = by_title["Feature A"]["sections"]
        assert "1. Background" in sections_a
        assert "2. Requirements" in sections_a

    def test_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        summaries = load_spec_summaries(empty)
        assert summaries == []


class TestParseSpecSummary:
    def test_extracts_frontmatter_title(self, tmp_specs):
        spec_file = tmp_specs / "feature-a.md"
        result = _parse_spec_summary(spec_file)
        assert result is not None
        assert result["title"] == "Feature A"

    def test_fallback_to_h1_title(self, tmp_path):
        spec = tmp_path / "no-frontmatter.md"
        spec.write_text("# My Spec Title\n\nSome content.\n")
        result = _parse_spec_summary(spec)
        assert result is not None
        assert result["title"] == "My Spec Title"

    def test_returns_none_for_empty_file(self, tmp_path):
        spec = tmp_path / "empty.md"
        spec.write_text("")
        result = _parse_spec_summary(spec)
        assert result is None

    def test_caps_sections(self, tmp_path):
        # Create spec with many sections
        lines = ["---\ntitle: Big Spec\nstatus: draft\n---\n\n# Big Spec\n"]
        for i in range(20):
            lines.append(f"\n## {i}. Section {i}\n")
        spec = tmp_path / "big.md"
        spec.write_text("\n".join(lines))
        result = _parse_spec_summary(spec)
        assert len(result["sections"]) <= 15
