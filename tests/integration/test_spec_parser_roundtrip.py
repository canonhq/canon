"""Integration tests for spec parser round-trip.

Parse real spec files from docs/examples/, verify the parsed model is
well-formed, and confirm that re-parsing the raw markdown produces an
identical document model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from canon.parser.parse import parse_spec

pytestmark = pytest.mark.integration

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "examples"
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.md")) if EXAMPLES_DIR.is_dir() else []

if not EXAMPLE_FILES:
    pytest.skip("No example spec files found in docs/examples/", allow_module_level=True)


@pytest.mark.parametrize(
    "spec_file",
    EXAMPLE_FILES,
    ids=[f.stem for f in EXAMPLE_FILES],
)
class TestSpecParserRoundtrip:
    """Parse → verify → re-parse cycle for each example spec file."""

    def test_parse_produces_valid_document(self, spec_file: Path):
        raw = spec_file.read_text()
        result = parse_spec(raw)

        doc = result.document
        assert doc.frontmatter.title, f"Missing title in {spec_file.name}"
        assert doc.frontmatter.status, f"Missing status in {spec_file.name}"
        assert doc.frontmatter.owner, f"Missing owner in {spec_file.name}"
        assert len(doc.sections) > 0, f"No sections parsed from {spec_file.name}"

    def test_sections_have_valid_structure(self, spec_file: Path):
        raw = spec_file.read_text()
        result = parse_spec(raw)

        for section in result.document.sections:
            assert section.title, "Section has empty title"
            assert section.depth >= 1, "Section depth should be >= 1"
            assert section.start_line >= 1, "Section start_line should be >= 1"
            assert section.end_line >= section.start_line

    def test_no_error_diagnostics(self, spec_file: Path):
        raw = spec_file.read_text()
        result = parse_spec(raw)

        errors = [d for d in result.diagnostics if d.severity == "error"]
        assert errors == [], f"Parse errors in {spec_file.name}: {errors}"

    def test_reparse_produces_identical_model(self, spec_file: Path):
        """Parsing the raw markdown twice should yield identical documents."""
        raw = spec_file.read_text()
        result1 = parse_spec(raw)
        result2 = parse_spec(raw)

        # Compare the full document models (excluding raw which is always the same)
        doc1 = result1.document.model_dump(exclude={"raw"})
        doc2 = result2.document.model_dump(exclude={"raw"})
        assert doc1 == doc2, f"Re-parse mismatch in {spec_file.name}"
