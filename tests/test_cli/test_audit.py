"""Tests for canon audit command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from canon.agent.client import AgentAPIError, CompletionResult
from canon.cli.audit import (
    _audit_heuristic,
    _parse_audit_response,
    _parse_evidence,
    run_audit,
)

SAMPLE_SPEC = """\
---
title: Auth Spec
status: active
owner: dev
team: platform
---

## 1. Login Flow
<!-- specwright:system:1 status:in_progress -->

### Acceptance Criteria

- [ ] Username validation with regex
- [x] Password hashing with bcrypt

## 2. Session Management
<!-- specwright:system:2 status:todo -->

### Acceptance Criteria

- [ ] JWT token generation
- [ ] Token refresh endpoint

## 3. Logout
<!-- specwright:system:3 status:done -->

### Acceptance Criteria

- [x] Session invalidation
"""

ALL_DONE_SPEC = """\
---
title: Done Spec
status: active
owner: dev
team: platform
---

## 1. Feature A
<!-- specwright:system:1 status:done -->

- [x] Everything done

## 2. Feature B
<!-- specwright:system:2 status:deprecated -->

- [x] No longer needed
"""

SAMPLE_CONFIG = """\
team: platform
specs:
  doc_paths:
    - "docs/specs/*.md"
"""


def _setup(tmp_path: Path, spec_content: str = SAMPLE_SPEC) -> Path:
    (tmp_path / "CANON.yaml").write_text(SAMPLE_CONFIG)
    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "auth.md").write_text(spec_content)
    (tmp_path / "src").mkdir()
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    return tmp_path


MOCK_CLAUDE_RESPONSE = json.dumps(
    {
        "sections": [
            {
                "sectionId": "1-login-flow",
                "sectionNumber": "1",
                "currentStatus": "in_progress",
                "recommendedStatus": "done",
                "confidence": "high",
                "reasoning": "All ACs implemented",
                "acEvaluations": [
                    {
                        "acText": "Username validation with regex",
                        "status": "realized",
                        "evidence": "src/auth.py:10",
                    }
                ],
            },
            {
                "sectionId": "2-session-management",
                "sectionNumber": "2",
                "currentStatus": "todo",
                "recommendedStatus": "in_progress",
                "confidence": "medium",
                "reasoning": "JWT generation found but no refresh endpoint",
                "acEvaluations": [
                    {
                        "acText": "JWT token generation",
                        "status": "realized",
                        "evidence": "src/tokens.py:5",
                    },
                    {
                        "acText": "Token refresh endpoint",
                        "status": "not_realized",
                        "evidence": "",
                    },
                ],
            },
        ]
    }
)


def _make_mock_client(*, available: bool = True) -> MagicMock:
    """Create a mock ClaudeClient."""
    mock = MagicMock()
    mock.is_available = available
    if available:
        mock.complete.return_value = CompletionResult(
            text=MOCK_CLAUDE_RESPONSE,
            input_tokens=1000,
            output_tokens=500,
        )
    return mock


class TestNoSpecsFound:
    def test_no_specs_found(self, tmp_path: Path, capsys):
        run_audit(root=tmp_path)
        output = capsys.readouterr().out
        assert "No spec files found" in output


class TestAllDoneSkips:
    def test_all_done_skips(self, tmp_path: Path, capsys):
        _setup(tmp_path, ALL_DONE_SPEC)
        with patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client(available=False)):
            run_audit(root=tmp_path)
        output = capsys.readouterr().out
        assert "all sections done/deprecated" in output


class TestHeuristicMode:
    def test_heuristic_mode_no_api_key(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        (tmp_path / "src" / "auth.py").write_text(
            "def username_validation(): pass\ndef jwt_token(): pass"
        )

        with patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client(available=False)):
            run_audit(root=tmp_path)

        output = capsys.readouterr().out
        assert "heuristic mode" in output


class TestDryRun:
    def test_dry_run_no_write(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        spec_path = tmp_path / "docs" / "specs" / "auth.md"
        original = spec_path.read_text()

        with patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client()):
            run_audit(dry_run=True, root=tmp_path)

        # File should be unchanged
        assert spec_path.read_text() == original
        output = capsys.readouterr().out
        assert "dry run" in output


class TestClaudeAudit:
    def test_claude_audit_applies_changes(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        spec_path = tmp_path / "docs" / "specs" / "auth.md"

        with patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client()):
            run_audit(root=tmp_path)

        updated = spec_path.read_text()
        assert "status:done" in updated
        assert "status:in_progress" in updated
        output = capsys.readouterr().out
        assert "1-login-flow" in output


class TestClaudeAPIError:
    def test_api_error_skips_spec(self, tmp_path: Path, capsys):
        _setup(tmp_path)

        mock_client = _make_mock_client()
        mock_client.complete.side_effect = AgentAPIError("rate limited", status_code=429)

        with patch("canon.cli.audit.ClaudeClient", return_value=mock_client):
            run_audit(root=tmp_path)

        output = capsys.readouterr().out
        assert "Claude API error" in output
        assert "skipping" in output


class TestSpecFilter:
    def test_spec_filter(self, tmp_path: Path, capsys):
        _setup(tmp_path)
        # Add a second spec
        (tmp_path / "docs" / "specs" / "other.md").write_text(
            "---\ntitle: Other\nstatus: active\nowner: dev\nteam: t\n---\n\n## 1. Foo\n<!-- specwright:system:1 status:todo -->\n- [ ] Bar\n"
        )

        with patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client(available=False)):
            run_audit(spec="auth.md", root=tmp_path)

        output = capsys.readouterr().out
        assert "Auth Spec" in output
        assert "Other" not in output


class TestParseAuditResponse:
    def test_valid_json(self):
        from canon.parser.models import AcceptanceCriterion, SectionStatus, SpecSection

        sections = [
            SpecSection(
                id="1-login-flow",
                section_number="1",
                title="Login Flow",
                depth=2,
                content="",
                status=SectionStatus(state="in_progress"),
                acceptance_criteria=[
                    AcceptanceCriterion(text="Username validation", checked=False, line=10)
                ],
                start_line=1,
                end_line=10,
            )
        ]

        recs = _parse_audit_response(MOCK_CLAUDE_RESPONSE, sections)
        assert len(recs) == 2
        assert recs[0].section_id == "1-login-flow"
        assert recs[0].recommended_status == "done"
        assert recs[0].confidence == "high"
        assert len(recs[0].ac_evaluations) == 1

    def test_invalid_json(self, capsys):
        recs = _parse_audit_response("not json at all", [])
        assert recs == []
        output = capsys.readouterr().out
        assert "Warning" in output

    def test_json_in_code_fence(self):
        fenced = f"```json\n{MOCK_CLAUDE_RESPONSE}\n```"
        recs = _parse_audit_response(fenced, [])
        assert len(recs) == 2

    def test_invalid_status_filtered(self):
        """Claude returning an invalid status like 'complete' should be skipped."""
        response = json.dumps(
            {
                "sections": [
                    {
                        "sectionId": "1-foo",
                        "sectionNumber": "1",
                        "currentStatus": "todo",
                        "recommendedStatus": "complete",  # invalid
                        "confidence": "high",
                    },
                    {
                        "sectionId": "2-bar",
                        "sectionNumber": "2",
                        "currentStatus": "todo",
                        "recommendedStatus": "done",  # valid
                        "confidence": "high",
                    },
                ]
            }
        )
        recs = _parse_audit_response(response, [])
        assert len(recs) == 1
        assert recs[0].section_id == "2-bar"


class TestSyncFlag:
    def test_sync_flag_triggers_sync(self, tmp_path: Path, capsys):
        _setup(tmp_path)

        with (
            patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client()),
            # Patch at source — audit.py uses lazy `from .sync_cmd import run_sync`
            # inside run_audit(), so the import resolves to the patched object.
            patch("canon.cli.sync_cmd.run_sync") as mock_sync,
        ):
            run_audit(do_sync=True, root=tmp_path)

        output = capsys.readouterr().out
        assert "ticket sync" in output.lower()
        assert mock_sync.called


class TestAuditHeuristic:
    def test_suggests_in_progress_with_evidence(self):
        from canon.parser.models import AcceptanceCriterion, SectionStatus, SpecSection

        sections = [
            SpecSection(
                id="2-session",
                section_number="2",
                title="Session",
                depth=2,
                content="",
                status=SectionStatus(state="todo"),
                acceptance_criteria=[
                    AcceptanceCriterion(text="JWT tokens", checked=False, line=10)
                ],
                start_line=1,
                end_line=10,
            )
        ]
        evidence = {"2-session": ["src/tokens.py:5: def jwt_generate():"]}

        recs = _audit_heuristic(sections, evidence)
        assert len(recs) == 1
        assert recs[0].recommended_status == "in_progress"
        assert recs[0].confidence == "medium"

    def test_no_suggestion_without_evidence(self):
        from canon.parser.models import SectionStatus, SpecSection

        sections = [
            SpecSection(
                id="3-nope",
                section_number="3",
                title="Nope",
                depth=2,
                content="",
                status=SectionStatus(state="todo"),
                start_line=1,
                end_line=5,
            )
        ]
        evidence = {"3-nope": []}

        recs = _audit_heuristic(sections, evidence)
        assert len(recs) == 0


class TestParseEvidence:
    def test_file_with_line(self):
        assert _parse_evidence("src/auth.py:10") == ("src/auth.py", "10")

    def test_file_with_range(self):
        assert _parse_evidence("src/auth.py:10-20") == ("src/auth.py", "10-20")

    def test_file_only(self):
        assert _parse_evidence("src/auth.py") == ("src/auth.py", "")

    def test_empty_string(self):
        assert _parse_evidence("") == ("", "")


class TestACUpdates:
    def test_audit_checks_off_acs(self, tmp_path: Path, capsys):
        """Claude audit should check off realized ACs and insert evidence."""
        _setup(tmp_path)

        with patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client()):
            run_audit(root=tmp_path)

        spec_path = tmp_path / "docs" / "specs" / "auth.md"
        updated = spec_path.read_text()
        # "Username validation with regex" was realized in the mock response
        assert "- [x] Username validation with regex" in updated
        assert "<!-- canon:realized-in:audit file:src/auth.py:10 -->" in updated

    def test_no_ac_updates_flag(self, tmp_path: Path, capsys):
        """--no-ac-updates should skip AC check-offs."""
        _setup(tmp_path)

        with patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client()):
            run_audit(root=tmp_path, no_ac_updates=True)

        spec_path = tmp_path / "docs" / "specs" / "auth.md"
        updated = spec_path.read_text()
        # Status should be updated but ACs should not be checked off
        assert "status:done" in updated
        # The AC should still be unchecked
        assert "- [ ] Username validation with regex" in updated
        assert "realized-in:audit" not in updated

    def test_heuristic_mode_skips_ac_updates(self, tmp_path: Path, capsys):
        """Heuristic mode (no Claude) should not attempt AC updates."""
        _setup(tmp_path)
        (tmp_path / "src" / "auth.py").write_text(
            "def username_validation(): pass\ndef jwt_token(): pass"
        )

        with patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client(available=False)):
            run_audit(root=tmp_path)

        spec_path = tmp_path / "docs" / "specs" / "auth.md"
        updated = spec_path.read_text()
        # No realization comments should be added in heuristic mode
        assert "realized-in:audit" not in updated

    def test_only_realized_acs_checked_off(self, tmp_path: Path, capsys):
        """Only 'realized' ACs should be checked off, not 'not_realized'."""
        _setup(tmp_path)

        with patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client()):
            run_audit(root=tmp_path)

        spec_path = tmp_path / "docs" / "specs" / "auth.md"
        updated = spec_path.read_text()
        # "JWT token generation" was realized in section 2 mock
        assert "- [x] JWT token generation" in updated
        # "Token refresh endpoint" was not_realized — should stay unchecked
        assert "- [ ] Token refresh endpoint" in updated

    def test_per_ac_output(self, tmp_path: Path, capsys):
        """Audit should print per-AC evaluation results."""
        _setup(tmp_path)

        with patch("canon.cli.audit.ClaudeClient", return_value=_make_mock_client()):
            run_audit(root=tmp_path)

        output = capsys.readouterr().out
        assert "[+] Username validation with regex" in output
        assert "[-] Token refresh endpoint" in output

    def test_ac_updates_when_status_unchanged(self, tmp_path: Path, capsys):
        """ACs should be checked off even when section status stays the same."""
        _setup(tmp_path)

        # Claude says section 1 stays in_progress (no status change) but has a realized AC
        unchanged_response = json.dumps(
            {
                "sections": [
                    {
                        "sectionId": "1-login-flow",
                        "sectionNumber": "1",
                        "currentStatus": "in_progress",
                        "recommendedStatus": "in_progress",  # no change
                        "confidence": "high",
                        "reasoning": "Partial implementation",
                        "acEvaluations": [
                            {
                                "acText": "Username validation with regex",
                                "status": "realized",
                                "evidence": "src/auth.py:10",
                            }
                        ],
                    },
                ]
            }
        )
        mock = _make_mock_client()
        mock.complete.return_value = CompletionResult(
            text=unchanged_response, input_tokens=100, output_tokens=50
        )

        with patch("canon.cli.audit.ClaudeClient", return_value=mock):
            run_audit(root=tmp_path)

        spec_path = tmp_path / "docs" / "specs" / "auth.md"
        updated = spec_path.read_text()
        # AC should be checked off despite no status change
        assert "- [x] Username validation with regex" in updated
        assert "<!-- canon:realized-in:audit file:src/auth.py:10 -->" in updated
        # Status should remain in_progress (unchanged)
        assert "status:in_progress" in updated
