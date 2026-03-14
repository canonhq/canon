"""Tests for delta comment parsing and writing."""

from __future__ import annotations

import pytest

from canon.parser import parse_spec
from canon.parser.models import SpecDocument, SpecFrontmatter
from canon.parser.parse import DELTA_RE, extract_comments_from_content, extract_delta_comment
from canon.parser.writer import (
    DeltaInsertion,
    insert_delta_comments,
    remove_delta_comments,
)


class TestDeltaParsing:
    def test_parses_added_delta(self):
        content = """<!-- specwright:delta:added -->

New section content."""
        assert extract_delta_comment(content) == "added"

    def test_parses_modified_delta(self):
        content = """<!-- specwright:delta:modified -->

Updated content."""
        assert extract_delta_comment(content) == "modified"

    def test_parses_removed_delta(self):
        content = """<!-- specwright:delta:removed -->

Deprecated content."""
        assert extract_delta_comment(content) == "removed"

    def test_no_delta_by_default(self):
        content = "Just regular content without delta."
        assert extract_delta_comment(content) is None

    def test_coexists_with_status_and_ticket(self):
        content = """<!-- specwright:system:1 status:in_progress -->
<!-- specwright:ticket:jira:PAY-100 -->
<!-- specwright:delta:modified -->

Content here."""
        status, ticket = extract_comments_from_content(content, "1")
        assert status.state == "in_progress"
        assert ticket is not None
        assert ticket.ticket_id == "PAY-100"
        assert extract_delta_comment(content) == "modified"

    def test_delta_regex_pattern(self):
        assert DELTA_RE.search("<!-- specwright:delta:added -->") is not None
        assert DELTA_RE.search("<!-- specwright:delta:modified -->") is not None
        assert DELTA_RE.search("<!-- specwright:delta:removed -->") is not None
        assert DELTA_RE.search("<!-- specwright:delta:invalid -->") is None
        assert DELTA_RE.search("regular text") is None

    def test_integration_with_parse_spec(self):
        raw = """---
title: "Delta Spec"
status: draft
owner: test
team: test
---

# Delta Spec

## 1. New Section
<!-- specwright:delta:added -->

Brand new content.

## 2. Changed Section
<!-- specwright:delta:modified -->

Updated content.

## 3. Normal Section

No delta here."""

        result = parse_spec(raw)
        sections = result.document.sections
        assert sections[0].delta == "added"
        assert sections[1].delta == "modified"
        assert sections[2].delta is None

    def test_section_model_defaults(self):
        raw = """---
title: "Default"
status: draft
owner: test
team: test
---

## 1. Section

Content."""

        result = parse_spec(raw)
        assert result.document.sections[0].delta is None
        assert result.document.sections[0].scenarios == []


class TestDeltaWriter:
    def _make_doc(self, raw: str) -> SpecDocument:
        return SpecDocument(
            file_path="test.md",
            frontmatter=SpecFrontmatter(title="Test", status="draft", owner="", team=""),
            sections=[],
            raw=raw,
        )

    def test_insert_delta_comment(self):
        raw = """---
title: Test
---

## 1. Section

Content here."""
        doc = self._make_doc(raw)
        result = insert_delta_comments(doc, [DeltaInsertion(heading_line=5, delta_type="added")])
        assert "<!-- canon:delta:added -->" in result

    def test_insert_multiple_delta_comments(self):
        raw = """---
title: Test
---

## 1. First

Content.

## 2. Second

More content."""
        doc = self._make_doc(raw)
        result = insert_delta_comments(
            doc,
            [
                DeltaInsertion(heading_line=5, delta_type="added"),
                DeltaInsertion(heading_line=9, delta_type="modified"),
            ],
        )
        assert "<!-- canon:delta:added -->" in result
        assert "<!-- canon:delta:modified -->" in result

    def test_no_insertions_returns_raw(self):
        raw = "## Section\n\nContent."
        doc = self._make_doc(raw)
        assert insert_delta_comments(doc, []) == raw

    def test_remove_delta_comments(self):
        raw = """## 1. Section
<!-- specwright:delta:added -->

Content.

## 2. Another
<!-- specwright:delta:modified -->

More."""
        result = remove_delta_comments(raw)
        assert "specwright:delta" not in result
        assert "## 1. Section" in result
        assert "## 2. Another" in result
        assert "Content." in result

    def test_remove_preserves_other_comments(self):
        raw = """<!-- specwright:system:1 status:done -->
<!-- specwright:delta:added -->
<!-- specwright:ticket:jira:PAY-1 -->"""
        result = remove_delta_comments(raw)
        assert "specwright:system:1" in result
        assert "specwright:ticket:jira:PAY-1" in result
        assert "specwright:delta" not in result

    def test_replace_existing_delta_comment(self):
        raw = """---
title: Test
---

## 1. Section
<!-- specwright:delta:added -->

Content here."""
        doc = self._make_doc(raw)
        result = insert_delta_comments(doc, [DeltaInsertion(heading_line=5, delta_type="modified")])
        assert "<!-- canon:delta:modified -->" in result
        assert "<!-- specwright:delta:added -->" not in result
        assert result.count("canon:delta:") == 1

    def test_remove_hand_written_extra_whitespace(self):
        raw = "## Section\n<!--  specwright:delta:added  -->\n\nContent."
        result = remove_delta_comments(raw)
        assert "specwright:delta" not in result
        assert "## Section" in result

    def test_remove_no_deltas_unchanged(self):
        raw = "## Section\n\nNo deltas here."
        assert remove_delta_comments(raw) == raw

    def test_replace_removes_duplicate_delta_comments(self):
        """When a section has multiple delta comments, replace first and remove extras."""
        raw = """---
title: Test
---

## 1. Section
<!-- specwright:delta:added -->
<!-- specwright:delta:added -->

Content here."""
        doc = self._make_doc(raw)
        result = insert_delta_comments(doc, [DeltaInsertion(heading_line=5, delta_type="modified")])
        assert "<!-- canon:delta:modified -->" in result
        assert "<!-- specwright:delta:added -->" not in result
        assert result.count("canon:delta:") == 1

    def test_insert_delta_at_end_of_file(self):
        """Heading is the last line — insert_idx reaches len(lines) boundary."""
        raw = "## 1. Final Section"
        doc = self._make_doc(raw)
        result = insert_delta_comments(doc, [DeltaInsertion(heading_line=1, delta_type="added")])
        assert "<!-- canon:delta:added -->" in result
        lines = result.split("\n")
        assert lines[0] == "## 1. Final Section"
        assert lines[1] == "<!-- canon:delta:added -->"

    def test_mixed_existing_and_new_deltas(self):
        """Mix of sections — one with existing delta, one without — in a single call."""
        raw = """---
title: Test
---

## 1. Has Existing
<!-- specwright:delta:added -->

Content.

## 2. No Existing

More content.

## 3. Also Existing
<!-- specwright:delta:removed -->

Old stuff."""
        doc = self._make_doc(raw)
        result = insert_delta_comments(
            doc,
            [
                DeltaInsertion(heading_line=5, delta_type="modified"),
                DeltaInsertion(heading_line=10, delta_type="added"),
                DeltaInsertion(heading_line=14, delta_type="modified"),
            ],
        )
        assert result.count("canon:delta:modified") == 2
        assert result.count("canon:delta:added") == 1
        assert "canon:delta:removed" not in result
        # Verify ordering is preserved
        lines = result.split("\n")
        delta_lines = [line for line in lines if "canon:delta:" in line]
        assert len(delta_lines) == 3

    def test_duplicate_heading_line_raises(self):
        """Duplicate heading_line values should raise ValueError."""
        raw = "## 1. Section\n\nContent."
        doc = self._make_doc(raw)
        with pytest.raises(ValueError, match="Duplicate heading_line"):
            insert_delta_comments(
                doc,
                [
                    DeltaInsertion(heading_line=1, delta_type="added"),
                    DeltaInsertion(heading_line=1, delta_type="modified"),
                ],
            )
