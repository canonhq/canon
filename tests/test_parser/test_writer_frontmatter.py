"""Tests for update_frontmatter_field in writer.py."""

from __future__ import annotations

from canon.parser.writer import update_frontmatter_field


class TestUpdateFrontmatterField:
    def test_insert_new_field(self):
        raw = """---
title: Test Spec
status: draft
owner: alice
team: platform
---

## 1. Section One

Content."""
        result = update_frontmatter_field(raw, "review_status", "approved")
        assert "review_status: approved" in result
        # Original fields preserved
        assert "title: Test Spec" in result
        assert "status: draft" in result
        assert "## 1. Section One" in result

    def test_update_existing_field(self):
        raw = """---
title: Test Spec
status: draft
owner: alice
team: platform
review_status: draft
---

## 1. Section One

Content."""
        result = update_frontmatter_field(raw, "review_status", "approved")
        assert "review_status: approved" in result
        # Should not have duplicate review_status
        assert result.count("review_status") == 1

    def test_preserves_other_fields(self):
        raw = """---
title: My Spec
status: in_progress
owner: bob
team: backend
tags:
  - api
  - payments
ticket_project: PAY
---

Body content here."""
        result = update_frontmatter_field(raw, "review_status", "in_review")
        assert "title: My Spec" in result
        assert "status: in_progress" in result
        assert "owner: bob" in result
        assert "team: backend" in result
        assert "ticket_project: PAY" in result
        assert "review_status: in_review" in result
        assert "Body content here." in result

    def test_preserves_body_content(self):
        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. First

Some content with **bold** and `code`.

- [ ] AC item one
- [x] AC item two"""
        result = update_frontmatter_field(raw, "review_status", "approved")
        assert "## 1. First" in result
        assert "Some content with **bold** and `code`." in result
        assert "- [ ] AC item one" in result
        assert "- [x] AC item two" in result

    def test_handles_empty_frontmatter(self):
        raw = """---
---

Body."""
        result = update_frontmatter_field(raw, "review_status", "draft")
        assert "review_status: draft" in result
        assert "Body." in result
