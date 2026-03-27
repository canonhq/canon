"""Tests for cross-system drift detection."""

from __future__ import annotations

from canon.parser.models import SectionStatus, SpecSection, TicketLink
from canon.sync.drift import DriftEntry, DriftReport, detect_drift


class TestDetectDrift:
    def test_no_drift_when_statuses_match(self):
        section = SpecSection(
            id="1-feature",
            section_number="1",
            title="Feature",
            depth=2,
            content="",
            status=SectionStatus(state="in_progress"),
            ticket_link=TicketLink(system="linear", ticket_id="LIN-1"),
            start_line=1,
            end_line=5,
        )
        shadow_statuses = {"jira": "in_progress", "github": "in_progress"}

        report = detect_drift(
            section=section,
            primary_status="in_progress",
            shadow_statuses=shadow_statuses,
        )
        assert len(report.entries) == 0

    def test_drift_when_shadow_behind(self):
        section = SpecSection(
            id="1-feature",
            section_number="1",
            title="Feature",
            depth=2,
            content="",
            status=SectionStatus(state="done"),
            ticket_link=TicketLink(system="linear", ticket_id="LIN-1"),
            start_line=1,
            end_line=5,
        )
        shadow_statuses = {"jira": "in_progress"}

        report = detect_drift(
            section=section,
            primary_status="done",
            shadow_statuses=shadow_statuses,
        )
        assert len(report.entries) == 1
        assert report.entries[0].shadow_system == "jira"
        assert report.entries[0].divergence_type == "status_behind"

    def test_drift_when_shadow_ahead(self):
        section = SpecSection(
            id="1-feature",
            section_number="1",
            title="Feature",
            depth=2,
            content="",
            status=SectionStatus(state="todo"),
            ticket_link=TicketLink(system="linear", ticket_id="LIN-1"),
            start_line=1,
            end_line=5,
        )
        shadow_statuses = {"jira": "done"}

        report = detect_drift(
            section=section,
            primary_status="todo",
            shadow_statuses=shadow_statuses,
        )
        assert len(report.entries) == 1
        assert report.entries[0].divergence_type == "status_ahead"

    def test_drift_with_unknown_status(self):
        section = SpecSection(
            id="1-feature",
            section_number="1",
            title="Feature",
            depth=2,
            content="",
            status=SectionStatus(state="todo"),
            ticket_link=TicketLink(system="linear", ticket_id="LIN-1"),
            start_line=1,
            end_line=5,
        )
        shadow_statuses = {"jira": "custom_status"}

        report = detect_drift(
            section=section,
            primary_status="todo",
            shadow_statuses=shadow_statuses,
        )
        assert len(report.entries) == 1
        assert report.entries[0].divergence_type == "status_mismatch"

    def test_multiple_shadows_mixed_drift(self):
        section = SpecSection(
            id="1-feature",
            section_number="1",
            title="Feature",
            depth=2,
            content="",
            status=SectionStatus(state="in_progress"),
            ticket_link=TicketLink(system="linear", ticket_id="LIN-1"),
            start_line=1,
            end_line=5,
        )
        shadow_statuses = {"jira": "todo", "github": "in_progress", "asana": "done"}

        report = detect_drift(
            section=section,
            primary_status="in_progress",
            shadow_statuses=shadow_statuses,
        )
        # jira behind, github matches, asana ahead
        assert len(report.entries) == 2
        jira_entry = next(e for e in report.entries if e.shadow_system == "jira")
        asana_entry = next(e for e in report.entries if e.shadow_system == "asana")
        assert jira_entry.divergence_type == "status_behind"
        assert asana_entry.divergence_type == "status_ahead"


class TestDriftReport:
    def test_has_drift(self):
        report = DriftReport(
            entries=[
                DriftEntry(
                    section_id="1-feature",
                    primary_system="linear",
                    primary_status="done",
                    shadow_system="jira",
                    shadow_status="in_progress",
                    divergence_type="status_behind",
                )
            ]
        )
        assert report.has_drift is True

    def test_no_drift(self):
        report = DriftReport(entries=[])
        assert report.has_drift is False
