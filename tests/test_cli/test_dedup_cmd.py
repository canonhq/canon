"""Tests for canon dedup CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from canon.cli.dedup import _resolve_project_key, run_dedup
from canon.sync.dedup import DedupResult, DuplicateGroup
from canon.sync.mapping import TicketMappingConfig, TicketSystemConfig
from canon.sync.models import SearchResult


def _make_search_result(ticket_id: str, state: str = "open") -> SearchResult:
    """Helper to create a SearchResult for testing."""
    return SearchResult(ticket_id=ticket_id, title="Test", state=state, ticket_url="")


class TestResolveProjectKey:
    def test_returns_project_from_single_system(self):
        mapping = TicketMappingConfig(
            ticket_systems={
                "github": TicketSystemConfig(system="github", project="acme/repo"),
            }
        )
        result = _resolve_project_key(mapping)
        assert result == "acme/repo"

    def test_returns_empty_when_no_systems(self):
        mapping = TicketMappingConfig()
        result = _resolve_project_key(mapping)
        assert result == ""

    def test_returns_empty_when_multiple_systems(self):
        mapping = TicketMappingConfig(
            ticket_systems={
                "github": TicketSystemConfig(system="github", project="acme/repo"),
                "jira": TicketSystemConfig(system="jira", project="ACME"),
            }
        )
        result = _resolve_project_key(mapping)
        assert result == ""

    def test_returns_empty_when_project_is_none(self):
        mapping = TicketMappingConfig(
            ticket_systems={
                "github": TicketSystemConfig(system="github", project=None),
            }
        )
        result = _resolve_project_key(mapping)
        assert result == ""


class TestRunDedupNoAdapter:
    def test_exits_when_no_adapter(self, capsys):
        with (
            patch("canon.cli.dedup.load_local_config") as mock_config,
            patch(
                "canon.cli.dedup.create_adapter_local",
                return_value=(None, TicketMappingConfig()),
            ),
        ):
            mock_config.return_value = MagicMock()
            with pytest.raises(SystemExit) as exc_info:
                run_dedup(dry_run=False)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "no ticket adapter configured" in captured.out


class TestRunDedupSpecNotFound:
    def test_skips_missing_spec(self, tmp_path: Path, capsys):
        mock_adapter = MagicMock()
        mapping = TicketMappingConfig()

        with (
            patch("canon.cli.dedup.load_local_config") as mock_config,
            patch(
                "canon.cli.dedup.create_adapter_local",
                return_value=(mock_adapter, mapping),
            ),
        ):
            mock_config.return_value = MagicMock()
            run_dedup(
                dry_run=False,
                spec=str(tmp_path / "nonexistent.md"),
            )

        captured = capsys.readouterr()
        assert "not found, skipping" in captured.out


class TestRunDedupRewriteUnknown:
    def test_dry_run_does_not_write(self, tmp_path: Path, capsys):
        spec_file = tmp_path / "test.md"
        spec_file.write_text(
            "---\ntitle: Test\n---\n# Section\n<!-- canon:ticket:unknown:123 -->\n"
        )
        mock_adapter = MagicMock()
        mapping = TicketMappingConfig()
        mock_doc = MagicMock()
        mock_doc.frontmatter.ticket_project = ""
        mock_parse_result = MagicMock()
        mock_parse_result.document = mock_doc

        with (
            patch("canon.cli.dedup.load_local_config") as mock_config,
            patch(
                "canon.cli.dedup.create_adapter_local",
                return_value=(mock_adapter, mapping),
            ),
            patch(
                "canon.cli.dedup.rewrite_unknown_systems",
                return_value=("updated content", 2),
            ),
            patch("canon.cli.dedup.parse_spec", return_value=mock_parse_result),
            patch(
                "canon.cli.dedup.find_duplicates",
                return_value=DedupResult(),
            ),
        ):
            mock_config.return_value = MagicMock()
            run_dedup(dry_run=True, spec=str(spec_file))

        captured = capsys.readouterr()
        assert "[dry-run]" in captured.out
        assert "Would rewrite" in captured.out
        # File should not be modified in dry-run
        assert "unknown" in spec_file.read_text()

    def test_rewrites_unknown_in_place(self, tmp_path: Path, capsys):
        spec_file = tmp_path / "test.md"
        spec_file.write_text("original content")
        mock_adapter = MagicMock()
        mapping = TicketMappingConfig()
        mock_doc = MagicMock()
        mock_doc.frontmatter.ticket_project = ""
        mock_parse_result = MagicMock()
        mock_parse_result.document = mock_doc

        with (
            patch("canon.cli.dedup.load_local_config") as mock_config,
            patch(
                "canon.cli.dedup.create_adapter_local",
                return_value=(mock_adapter, mapping),
            ),
            patch(
                "canon.cli.dedup.rewrite_unknown_systems",
                return_value=("rewritten content", 3),
            ),
            patch("canon.cli.dedup.parse_spec", return_value=mock_parse_result),
            patch(
                "canon.cli.dedup.find_duplicates",
                return_value=DedupResult(),
            ),
        ):
            mock_config.return_value = MagicMock()
            run_dedup(dry_run=False, spec=str(spec_file))

        # File should be written with rewritten content
        assert spec_file.read_text() == "rewritten content"
        captured = capsys.readouterr()
        assert "Rewrote 3" in captured.out


class TestRunDedupDuplicateGroups:
    def test_reports_duplicate_groups(self, tmp_path: Path, capsys):
        spec_file = tmp_path / "test.md"
        spec_file.write_text("---\ntitle: Test\n---\n# Section\n")
        mock_adapter = MagicMock()
        mapping = TicketMappingConfig()
        mock_doc = MagicMock()
        mock_doc.frontmatter.ticket_project = "acme/repo"
        mock_parse_result = MagicMock()
        mock_parse_result.document = mock_doc

        keep = _make_search_result("10", state="open")
        dupe = _make_search_result("11", state="open")
        group = DuplicateGroup(
            section_id="s1",
            section_title="Login",
            tickets=[keep, dupe],
            keep=keep,
        )
        dedup_result = DedupResult(groups=[group])

        with (
            patch("canon.cli.dedup.load_local_config") as mock_config,
            patch(
                "canon.cli.dedup.create_adapter_local",
                return_value=(mock_adapter, mapping),
            ),
            patch(
                "canon.cli.dedup.rewrite_unknown_systems",
                return_value=(spec_file.read_text(), 0),
            ),
            patch("canon.cli.dedup.parse_spec", return_value=mock_parse_result),
            patch(
                "canon.cli.dedup.find_duplicates",
                return_value=dedup_result,
            ),
        ):
            mock_config.return_value = MagicMock()
            run_dedup(dry_run=False, spec=str(spec_file))

        captured = capsys.readouterr()
        assert "Login" in captured.out
        assert "Keep: #10" in captured.out
        assert "Close: #11" in captured.out

    def test_dry_run_shows_would_close(self, tmp_path: Path, capsys):
        spec_file = tmp_path / "test.md"
        spec_file.write_text("---\ntitle: Test\n---\n# Section\n")
        mock_adapter = MagicMock()
        mapping = TicketMappingConfig()
        mock_doc = MagicMock()
        mock_doc.frontmatter.ticket_project = "acme/repo"
        mock_parse_result = MagicMock()
        mock_parse_result.document = mock_doc

        keep = _make_search_result("10", state="open")
        dupe = _make_search_result("11", state="open")
        group = DuplicateGroup(
            section_id="s1",
            section_title="Auth",
            tickets=[keep, dupe],
            keep=keep,
        )
        dedup_result = DedupResult(groups=[group])

        with (
            patch("canon.cli.dedup.load_local_config") as mock_config,
            patch(
                "canon.cli.dedup.create_adapter_local",
                return_value=(mock_adapter, mapping),
            ),
            patch(
                "canon.cli.dedup.rewrite_unknown_systems",
                return_value=(spec_file.read_text(), 0),
            ),
            patch("canon.cli.dedup.parse_spec", return_value=mock_parse_result),
            patch(
                "canon.cli.dedup.find_duplicates",
                return_value=dedup_result,
            ),
        ):
            mock_config.return_value = MagicMock()
            run_dedup(dry_run=True, spec=str(spec_file))

        captured = capsys.readouterr()
        assert "[dry-run] Would close: #11" in captured.out


class TestRunDedupSummary:
    def test_summary_counts(self, tmp_path: Path, capsys):
        spec_file = tmp_path / "test.md"
        spec_file.write_text("---\ntitle: Test\n---\n")
        mock_adapter = MagicMock()
        mapping = TicketMappingConfig()
        mock_doc = MagicMock()
        mock_doc.frontmatter.ticket_project = "acme/repo"
        mock_parse_result = MagicMock()
        mock_parse_result.document = mock_doc

        keep = _make_search_result("1")
        dupe = _make_search_result("2")
        group = DuplicateGroup(
            section_id="s1",
            section_title="X",
            tickets=[keep, dupe],
            keep=keep,
        )
        dedup_result = DedupResult(groups=[group])

        with (
            patch("canon.cli.dedup.load_local_config") as mock_config,
            patch(
                "canon.cli.dedup.create_adapter_local",
                return_value=(mock_adapter, mapping),
            ),
            patch(
                "canon.cli.dedup.rewrite_unknown_systems",
                return_value=("updated", 1),
            ),
            patch("canon.cli.dedup.parse_spec", return_value=mock_parse_result),
            patch(
                "canon.cli.dedup.find_duplicates",
                return_value=dedup_result,
            ),
        ):
            mock_config.return_value = MagicMock()
            run_dedup(dry_run=False, spec=str(spec_file))

        captured = capsys.readouterr()
        assert "1 unknown links rewritten" in captured.out
        assert "1 duplicate groups found" in captured.out


class TestRunDedupErrors:
    def test_reports_errors(self, tmp_path: Path, capsys):
        spec_file = tmp_path / "test.md"
        spec_file.write_text("---\ntitle: Test\n---\n")
        mock_adapter = MagicMock()
        mapping = TicketMappingConfig()
        mock_doc = MagicMock()
        mock_doc.frontmatter.ticket_project = "acme/repo"
        mock_parse_result = MagicMock()
        mock_parse_result.document = mock_doc

        dedup_result = DedupResult(errors=["API rate limited"])

        with (
            patch("canon.cli.dedup.load_local_config") as mock_config,
            patch(
                "canon.cli.dedup.create_adapter_local",
                return_value=(mock_adapter, mapping),
            ),
            patch(
                "canon.cli.dedup.rewrite_unknown_systems",
                return_value=(spec_file.read_text(), 0),
            ),
            patch("canon.cli.dedup.parse_spec", return_value=mock_parse_result),
            patch(
                "canon.cli.dedup.find_duplicates",
                return_value=dedup_result,
            ),
        ):
            mock_config.return_value = MagicMock()
            run_dedup(dry_run=False, spec=str(spec_file))

        captured = capsys.readouterr()
        assert "Error: API rate limited" in captured.out
