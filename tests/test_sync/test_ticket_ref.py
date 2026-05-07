"""Tests for canon.sync.ticket_ref helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from canon.sync.ticket_ref import due_for_recheck, qualify


class TestQualify:
    def test_github_prefixes_repo(self):
        assert qualify("github", "canonhq/canon", "123") == "canonhq/canon#123"

    def test_github_strips_leading_hash(self):
        assert qualify("github", "canonhq/canon", "#123") == "canonhq/canon#123"

    def test_jira_returns_id_unchanged(self):
        assert qualify("jira", "canonhq/canon", "PROJ-7") == "PROJ-7"

    def test_linear_returns_id_unchanged(self):
        assert qualify("linear", "any/repo", "TEAM-9") == "TEAM-9"

    def test_jira_ignores_repo(self):
        assert qualify("jira", "", "PROJ-7") == "PROJ-7"

    def test_github_requires_repo(self):
        with pytest.raises(ValueError, match="repo is required"):
            qualify("github", "", "123")

    def test_github_requires_repo_when_none(self):
        with pytest.raises(ValueError, match="repo is required"):
            qualify("github", None, "123")


class TestDueForRecheck:
    def _row(self, status: str, last_recheck_at: datetime | None) -> SimpleNamespace:
        return SimpleNamespace(status=status, last_recheck_at=last_recheck_at)

    def test_ok_status_never_due(self):
        assert due_for_recheck(self._row("ok", None)) is False

    def test_dismissed_never_due(self):
        assert due_for_recheck(self._row("dismissed", None)) is False
        old = datetime.now(UTC) - timedelta(days=30)
        assert due_for_recheck(self._row("dismissed", old)) is False

    def test_broken_never_rechecked_is_due(self):
        assert due_for_recheck(self._row("broken", None)) is True

    def test_broken_recently_rechecked_not_due(self):
        recent = datetime.now(UTC) - timedelta(hours=23)
        assert due_for_recheck(self._row("broken", recent)) is False

    def test_broken_24h_old_recheck_is_due(self):
        old = datetime.now(UTC) - timedelta(hours=24, minutes=1)
        assert due_for_recheck(self._row("broken", old)) is True
