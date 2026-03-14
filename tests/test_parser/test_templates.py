"""Tests for doc-type templates."""

from __future__ import annotations

import pytest

from canon.parser import parse_spec
from canon.parser.templates import get_template, list_template_types


class TestGetTemplate:
    def test_loads_spec_template(self):
        content = get_template("spec")
        assert "title:" in content
        assert "type: spec" in content

    def test_loads_proposal_template(self):
        content = get_template("proposal")
        assert "type: proposal" in content
        assert "Problem Statement" in content

    def test_loads_design_template(self):
        content = get_template("design")
        assert "type: design" in content
        assert "Architecture" in content

    def test_loads_adr_template(self):
        content = get_template("adr")
        assert "type: adr" in content
        assert "Decision" in content

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown template type"):
            get_template("whitepaper")

    def test_templates_parse_without_errors(self):
        for doc_type in list_template_types():
            raw = get_template(doc_type)
            result = parse_spec(raw)
            errors = [d for d in result.diagnostics if d.severity == "error"]
            assert errors == [], f"{doc_type} template has parse errors: {errors}"
            assert result.document.frontmatter.doc_type == doc_type


class TestListTemplateTypes:
    def test_returns_all_types(self):
        types = list_template_types()
        assert set(types) == {"spec", "proposal", "design", "adr"}

    def test_returns_list(self):
        assert isinstance(list_template_types(), list)

    def test_all_listed_types_have_template_files(self):
        """Every type from list_template_types() must have a loadable template file."""
        for doc_type in list_template_types():
            content = get_template(doc_type)
            assert content, f"Template for {doc_type} is empty"
