"""Port of spec-writer tests — ticket link insertion and status updates."""

from __future__ import annotations

from canon.parser.models import SpecDocument, SpecFrontmatter
from canon.parser.writer import (
    RealizationInsertion,
    StatusUpdate,
    TicketLinkInsertion,
    check_off_acs,
    insert_realization_comments,
    insert_ticket_links,
    update_status_comments,
)


def _make_doc(raw: str) -> SpecDocument:
    """Helper to create a minimal SpecDocument for writer tests."""
    return SpecDocument(
        file_path="test.md",
        frontmatter=SpecFrontmatter(title="Test", status="draft", owner="", team=""),
        sections=[],
        raw=raw,
    )


class TestInsertTicketLinks:
    def test_no_change_on_empty_insertions(self):
        doc = _make_doc("## 1. Section\n\nContent.")
        assert insert_ticket_links(doc, []) == doc.raw

    def test_inserts_single_ticket_link(self):
        raw = "---\ntitle: T\n---\n\n## 1. Section\n\nContent."
        doc = _make_doc(raw)
        result = insert_ticket_links(
            doc,
            [TicketLinkInsertion(heading_line=5, system="jira", ticket_id="PAY-1")],
        )
        assert "<!-- canon:ticket:jira:PAY-1 -->" in result

    def test_inserts_after_existing_comments(self):
        raw = (
            "---\ntitle: T\n---\n\n"
            "## 1. Section\n"
            "<!-- specwright:system:1 status:draft -->\n\n"
            "Content."
        )
        doc = _make_doc(raw)
        result = insert_ticket_links(
            doc,
            [TicketLinkInsertion(heading_line=5, system="jira", ticket_id="PAY-1")],
        )
        lines = result.split("\n")
        # The ticket comment should appear after existing comment + blank line
        ticket_idx = next(i for i, line in enumerate(lines) if "ticket:jira:PAY-1" in line)
        status_idx = next(i for i, line in enumerate(lines) if "system:1 status:draft" in line)
        assert ticket_idx > status_idx

    def test_inserts_multiple_links_preserving_order(self):
        raw = "---\ntitle: T\n---\n\n## 1. First\n\nContent.\n\n## 2. Second\n\nContent."
        doc = _make_doc(raw)
        result = insert_ticket_links(
            doc,
            [
                TicketLinkInsertion(heading_line=5, system="jira", ticket_id="PAY-1"),
                TicketLinkInsertion(heading_line=9, system="jira", ticket_id="PAY-2"),
            ],
        )
        assert "ticket:jira:PAY-1" in result
        assert "ticket:jira:PAY-2" in result
        # PAY-1 should appear before PAY-2
        assert result.index("PAY-1") < result.index("PAY-2")

    def test_handles_github_ticket_format(self):
        raw = "---\ntitle: T\n---\n\n## 1. Section\n\nContent."
        doc = _make_doc(raw)
        result = insert_ticket_links(
            doc,
            [TicketLinkInsertion(heading_line=5, system="github", ticket_id="42")],
        )
        assert "<!-- canon:ticket:github:42 -->" in result


class TestUpdateStatusComments:
    def test_no_change_on_empty_updates(self):
        doc = _make_doc("## 1. Section\n\nContent.")
        assert update_status_comments(doc, []) == doc.raw

    def test_updates_single_status(self):
        raw = (
            "---\ntitle: T\n---\n\n"
            "## 1. Section\n"
            "<!-- specwright:system:1 status:draft -->\n\n"
            "Content."
        )
        doc = _make_doc(raw)
        result = update_status_comments(
            doc,
            [StatusUpdate(section_number="1", new_state="done")],
        )
        assert "<!-- canon:system:1 status:done -->" in result
        assert "status:draft" not in result

    def test_updates_multiple_statuses(self):
        raw = (
            "---\ntitle: T\n---\n\n"
            "## 1. First\n"
            "<!-- specwright:system:1 status:draft -->\n\n"
            "## 2. Second\n"
            "<!-- specwright:system:2 status:todo -->\n\n"
        )
        doc = _make_doc(raw)
        result = update_status_comments(
            doc,
            [
                StatusUpdate(section_number="1", new_state="in_progress"),
                StatusUpdate(section_number="2", new_state="done"),
            ],
        )
        assert "system:1 status:in_progress" in result
        assert "system:2 status:done" in result

    def test_leaves_unmatched_comments_unchanged(self):
        raw = (
            "---\ntitle: T\n---\n\n"
            "## 1. Section\n"
            "<!-- specwright:system:1 status:draft -->\n\n"
            "## 2. Section\n"
            "<!-- specwright:system:2 status:todo -->\n\n"
        )
        doc = _make_doc(raw)
        result = update_status_comments(
            doc,
            [StatusUpdate(section_number="1", new_state="done")],
        )
        assert "system:1 status:done" in result
        assert "system:2 status:todo" in result  # unchanged

    def test_round_trip_with_fixture(self, payments_spec: str):
        """Parse a real spec, update statuses, verify they round-trip."""
        from canon.parser.parse import parse_spec

        result = parse_spec(payments_spec)
        doc = result.document
        # Update section 1 from done → in_progress
        updated = update_status_comments(
            doc,
            [StatusUpdate(section_number="1", new_state="in_progress")],
        )
        # Re-parse and verify
        result2 = parse_spec(updated)
        assert result2.document.sections[0].status.state == "in_progress"
        # Other sections should be unchanged
        assert result2.document.sections[1].status.state == "in_progress"


class TestInsertRealizationComments:
    def test_no_change_on_empty_insertions(self):
        doc = _make_doc("## 1. Section\n\n- [ ] Some AC")
        assert insert_realization_comments(doc, []) == doc.raw

    def test_inserts_after_matching_ac(self):
        raw = "## 1. Section\n\n- [x] OAuth support\n\nMore content."
        doc = _make_doc(raw)
        result = insert_realization_comments(
            doc,
            [
                RealizationInsertion(
                    ac_text="OAuth support",
                    pr_number=42,
                    file_path="src/auth.py",
                    lines="10-20",
                )
            ],
        )
        assert "<!-- canon:realized-in:PR#42 file:src/auth.py:10-20 -->" in result

    def test_inserts_without_lines(self):
        raw = "## 1. Section\n\n- [ ] Basic feature\n\nEnd."
        doc = _make_doc(raw)
        result = insert_realization_comments(
            doc,
            [
                RealizationInsertion(
                    ac_text="Basic feature",
                    pr_number=10,
                    file_path="src/feature.py",
                )
            ],
        )
        assert "<!-- canon:realized-in:PR#10 file:src/feature.py -->" in result

    def test_case_insensitive_matching(self):
        raw = "## 1. Section\n\n- [x] OAuth Support\n\nEnd."
        doc = _make_doc(raw)
        result = insert_realization_comments(
            doc,
            [
                RealizationInsertion(
                    ac_text="oauth support",
                    pr_number=5,
                    file_path="auth.py",
                )
            ],
        )
        assert "<!-- canon:realized-in:PR#5 file:auth.py -->" in result

    def test_does_not_duplicate_existing(self):
        raw = (
            "## 1. Section\n\n"
            "- [x] Auth flow\n"
            "<!-- specwright:realized-in:PR#42 file:auth.py -->\n\n"
            "End."
        )
        doc = _make_doc(raw)
        result = insert_realization_comments(
            doc,
            [RealizationInsertion(ac_text="Auth flow", pr_number=42, file_path="auth.py")],
        )
        assert result.count("PR#42") == 1

    def test_adds_new_ref_alongside_existing(self):
        raw = (
            "## 1. Section\n\n"
            "- [x] Auth flow\n"
            "<!-- specwright:realized-in:PR#10 file:old.py -->\n\n"
            "End."
        )
        doc = _make_doc(raw)
        result = insert_realization_comments(
            doc,
            [RealizationInsertion(ac_text="Auth flow", pr_number=20, file_path="new.py")],
        )
        assert "PR#10" in result
        assert "PR#20" in result

    def test_multiple_insertions_different_acs(self):
        raw = "## 1. Section\n\n- [ ] Feature A\n- [ ] Feature B\n\nEnd."
        doc = _make_doc(raw)
        result = insert_realization_comments(
            doc,
            [
                RealizationInsertion(ac_text="Feature A", pr_number=1, file_path="a.py"),
                RealizationInsertion(ac_text="Feature B", pr_number=2, file_path="b.py"),
            ],
        )
        assert "PR#1 file:a.py" in result
        assert "PR#2 file:b.py" in result

    def test_no_match_leaves_raw_unchanged(self):
        raw = "## 1. Section\n\n- [ ] Existing AC\n\nEnd."
        doc = _make_doc(raw)
        result = insert_realization_comments(
            doc,
            [RealizationInsertion(ac_text="Nonexistent AC", pr_number=99, file_path="x.py")],
        )
        assert result == raw

    def test_round_trip_with_parser(self):
        """Insert a realization comment and verify the parser reads it back."""
        from canon.parser.parse import parse_spec

        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section

- [ ] OAuth support

Content here."""
        doc = _make_doc(raw)
        updated = insert_realization_comments(
            doc,
            [
                RealizationInsertion(
                    ac_text="OAuth support", pr_number=42, file_path="auth.py", lines="5-10"
                )
            ],
        )
        result = parse_spec(updated)
        ac = result.document.sections[0].acceptance_criteria[0]
        assert len(ac.realized_in) == 1
        assert ac.realized_in[0].pr_number == 42
        assert ac.realized_in[0].file_path == "auth.py"
        assert ac.realized_in[0].lines == "5-10"

    def test_audit_realization_insertion(self):
        """Insert a realization with pr_number=None (audit source)."""
        raw = "## 1. Section\n\n- [x] Feature done\n\nEnd."
        doc = _make_doc(raw)
        result = insert_realization_comments(
            doc,
            [RealizationInsertion(ac_text="Feature done", file_path="src/feature.py", lines="1-5")],
        )
        assert "<!-- canon:realized-in:audit file:src/feature.py:1-5 -->" in result
        assert "PR#" not in result

    def test_audit_realization_round_trip(self):
        """Audit realization comment round-trips through parser."""
        from canon.parser.parse import parse_spec

        raw = """---
title: Test
status: draft
owner: test
team: test
---

## 1. Section

- [x] Feature done

Content here."""
        doc = _make_doc(raw)
        updated = insert_realization_comments(
            doc,
            [RealizationInsertion(ac_text="Feature done", file_path="src/f.py", lines="10")],
        )
        result = parse_spec(updated)
        ac = result.document.sections[0].acceptance_criteria[0]
        assert len(ac.realized_in) == 1
        assert ac.realized_in[0].pr_number is None
        assert ac.realized_in[0].file_path == "src/f.py"
        assert ac.realized_in[0].lines == "10"


class TestCheckOffAcs:
    def test_checks_off_matching_ac(self):
        raw = "## 1. Section\n\n- [ ] Feature A\n- [ ] Feature B\n"
        result = check_off_acs(raw, ["Feature A"])
        assert "- [x] Feature A" in result
        assert "- [ ] Feature B" in result

    def test_case_insensitive_match(self):
        raw = "- [ ] OAuth Support\n"
        result = check_off_acs(raw, ["oauth support"])
        assert "- [x] OAuth Support" in result

    def test_idempotent_already_checked(self):
        raw = "- [x] Already done\n"
        result = check_off_acs(raw, ["Already done"])
        assert result == raw

    def test_preserves_indentation(self):
        raw = "  - [ ] Indented AC\n"
        result = check_off_acs(raw, ["Indented AC"])
        assert "  - [x] Indented AC" in result

    def test_no_change_on_empty_list(self):
        raw = "- [ ] Keep this\n"
        assert check_off_acs(raw, []) == raw

    def test_no_change_on_no_match(self):
        raw = "- [ ] Existing AC\n"
        assert check_off_acs(raw, ["Nonexistent"]) == raw

    def test_multiple_acs(self):
        raw = "- [ ] First\n- [ ] Second\n- [ ] Third\n"
        result = check_off_acs(raw, ["First", "Third"])
        assert "- [x] First" in result
        assert "- [ ] Second" in result
        assert "- [x] Third" in result
