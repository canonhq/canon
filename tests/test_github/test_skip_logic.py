"""Tests for _should_skip_reanalysis() — smart re-analysis skip logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from canon.github.handlers.on_pull_request import _should_skip_reanalysis


def _make_prev_review(head_sha: str = "prev_sha", hours_ago: float = 1.0) -> dict:
    """Create a minimal previous review dict."""
    return {
        "head_sha": head_sha,
        "created_at": datetime.now(UTC) - timedelta(hours=hours_ago),
    }


def _make_pr(head_sha: str = "new_sha") -> dict:
    """Create a minimal PR payload dict."""
    return {"head": {"sha": head_sha}}


def _make_files(*filenames: str) -> list[dict]:
    """Create a minimal raw_files list."""
    return [{"filename": fn} for fn in filenames]


class TestShouldSkipReanalysis:
    def test_same_sha_returns_no_changes(self):
        prev = _make_prev_review(head_sha="same_sha")
        pr = _make_pr(head_sha="same_sha")
        files = _make_files("src/app.py")
        assert _should_skip_reanalysis(prev, files, pr) == "no_changes"

    def test_config_only_changes_returns_skip(self):
        prev = _make_prev_review()
        pr = _make_pr()
        files = _make_files(
            ".github/workflows/ci.yml",
            "package-lock.json",
            ".vscode/settings.json",
        )
        assert _should_skip_reanalysis(prev, files, pr) == "config_only_changes"

    def test_spec_files_changed_returns_none(self):
        prev = _make_prev_review()
        pr = _make_pr()
        files = _make_files("docs/specs/auth.md", "src/app.py")
        assert _should_skip_reanalysis(prev, files, pr) is None

    def test_stale_review_returns_none(self):
        prev = _make_prev_review(hours_ago=25.0)  # >24h
        pr = _make_pr()
        files = _make_files("src/app.py")
        assert _should_skip_reanalysis(prev, files, pr) is None

    def test_fresh_non_spec_change_returns_skip(self):
        prev = _make_prev_review(hours_ago=2.0)
        pr = _make_pr()
        files = _make_files("src/app.py", "src/utils.py")
        assert _should_skip_reanalysis(prev, files, pr) == "no_spec_relevant_changes"

    def test_empty_files_with_different_sha(self):
        prev = _make_prev_review()
        pr = _make_pr()
        files = []
        # No files but different SHA — falls through to "no_spec_relevant_changes"
        assert _should_skip_reanalysis(prev, files, pr) == "no_spec_relevant_changes"

    def test_mixed_config_and_code_not_skipped(self):
        prev = _make_prev_review()
        pr = _make_pr()
        files = _make_files(".github/workflows/ci.yml", "src/handler.py")
        # Not all files are config-only, but no spec files either
        result = _should_skip_reanalysis(prev, files, pr)
        assert result == "no_spec_relevant_changes"

    def test_naive_datetime_handled(self):
        """Previous review with naive (no timezone) datetime should still work."""
        prev = {
            "head_sha": "old_sha",
            "created_at": datetime.now() - timedelta(hours=2),  # naive
        }
        pr = _make_pr()
        files = _make_files("src/app.py")
        assert _should_skip_reanalysis(prev, files, pr) == "no_spec_relevant_changes"

    def test_stale_naive_datetime_forces_reanalysis(self):
        prev = {
            "head_sha": "old_sha",
            "created_at": datetime.now() - timedelta(hours=30),  # naive, >24h
        }
        pr = _make_pr()
        files = _make_files("src/app.py")
        assert _should_skip_reanalysis(prev, files, pr) is None
