"""Unit tests for scripts/coverage_report.py."""

from __future__ import annotations

# Import the module under test
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location(
    "coverage_report",
    Path(__file__).resolve().parent.parent / "scripts" / "coverage_report.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

extract_summary = _mod.extract_summary
format_summary_row = _mod.format_summary_row
build_module_breakdown = _mod.build_module_breakdown
load_json = _mod.load_json
main = _mod.main
SENTINEL = _mod.SENTINEL


# -- Fixtures ----------------------------------------------------------------

SAMPLE_COVERAGE = {
    "totals": {
        "covered_lines": 80,
        "num_statements": 100,
        "percent_covered": 80.0,
        "covered_branches": 15,
        "num_branches": 20,
    },
    "files": {
        "src/canon/agent/client.py": {
            "summary": {
                "covered_lines": 40,
                "num_statements": 50,
                "covered_branches": 8,
                "num_branches": 10,
            }
        },
        "src/canon/agent/prompts.py": {
            "summary": {
                "covered_lines": 20,
                "num_statements": 25,
                "covered_branches": 5,
                "num_branches": 5,
            }
        },
        "src/canon/main.py": {
            "summary": {
                "covered_lines": 20,
                "num_statements": 25,
                "covered_branches": 2,
                "num_branches": 5,
            }
        },
    },
}


# -- extract_summary ---------------------------------------------------------


class TestExtractSummary:
    def test_extracts_all_fields(self):
        result = extract_summary(SAMPLE_COVERAGE)
        assert result["lines_covered"] == 80
        assert result["lines_total"] == 100
        assert result["line_pct"] == 80.0
        assert result["branches_covered"] == 15
        assert result["branches_total"] == 20

    def test_missing_totals_returns_zeros(self):
        result = extract_summary({})
        assert result["lines_covered"] == 0
        assert result["lines_total"] == 0
        assert result["line_pct"] == 0.0


# -- format_summary_row ------------------------------------------------------


class TestFormatSummaryRow:
    def test_formats_table_row(self):
        summary = extract_summary(SAMPLE_COVERAGE)
        row = format_summary_row("Unit", summary)
        assert row.startswith("| Unit |")
        assert "80.0%" in row
        assert "80/100" in row
        assert "75.0%" in row  # 15/20 branches

    def test_zero_branches_shows_na(self):
        summary = {
            "line_pct": 50.0,
            "lines_covered": 5,
            "lines_total": 10,
            "branches_covered": 0,
            "branches_total": 0,
        }
        row = format_summary_row("Test", summary)
        assert "N/A" in row


# -- build_module_breakdown --------------------------------------------------


class TestBuildModuleBreakdown:
    def test_groups_by_subpackage(self):
        modules = build_module_breakdown(SAMPLE_COVERAGE)
        names = [name for name, _ in modules]
        assert "canon.agent" in names
        assert "canon" in names  # main.py is top-level

    def test_aggregates_lines(self):
        modules = dict(build_module_breakdown(SAMPLE_COVERAGE))
        agent = modules["canon.agent"]
        # agent/client.py (40/50) + agent/prompts.py (20/25) = 60/75
        assert agent["lines_covered"] == 60
        assert agent["lines_total"] == 75

    def test_skips_non_canon_paths(self):
        data = {
            "files": {
                "vendor/other/lib.py": {
                    "summary": {
                        "covered_lines": 1,
                        "num_statements": 1,
                        "covered_branches": 0,
                        "num_branches": 0,
                    }
                },
            }
        }
        modules = build_module_breakdown(data)
        assert modules == []

    def test_empty_files(self):
        modules = build_module_breakdown({"files": {}})
        assert modules == []


# -- load_json ---------------------------------------------------------------


class TestLoadJson:
    def test_returns_none_for_none_path(self):
        assert load_json(None) is None

    def test_returns_none_for_missing_file(self):
        assert load_json("/nonexistent/path.json") is None

    def test_loads_valid_json(self, tmp_path):
        p = tmp_path / "cov.json"
        p.write_text(json.dumps({"totals": {}}))
        result = load_json(str(p))
        assert result == {"totals": {}}

    def test_returns_none_for_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json")
        assert load_json(str(p)) is None


# -- main (end-to-end) -------------------------------------------------------


class TestMain:
    def test_no_data_outputs_sentinel_and_message(self, capsys):
        with patch("sys.argv", ["coverage_report.py"]):
            main()
        output = capsys.readouterr().out
        assert output.startswith(SENTINEL)
        assert "No coverage data available" in output

    def test_with_unit_data(self, tmp_path, capsys):
        p = tmp_path / "unit.json"
        p.write_text(json.dumps(SAMPLE_COVERAGE))
        with patch(
            "sys.argv", ["coverage_report.py", "--unit", str(p), "--commit", "abc12345dead"]
        ):
            main()
        output = capsys.readouterr().out
        assert SENTINEL in output
        assert "## Coverage Report" in output
        assert "Unit" in output
        assert "80.0%" in output
        assert "abc12345" in output  # short SHA
        assert "Per-module breakdown" in output
