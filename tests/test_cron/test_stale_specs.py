"""Tests for the stale spec warning cron job."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from canon.cron.stale_specs import DEFAULT_STALE_DAYS, run_stale_check


def _make_settings(**overrides):
    defaults = {
        "slack_bot_token": "xoxb-test",
        "github_app_id": "123",
        "github_private_key": "key",
        "github_installation_id": "456",
        "github_owner": "acme",
        "github_repo": "widgets",
    }
    defaults.update(overrides)
    return type("S", (), defaults)()


def _make_spec(
    *,
    title="Feature A",
    slug="feature-a",
    status="in-progress",
    updated=None,
    github_url="https://github.com/acme/widgets/blob/main/docs/specs/feature-a.md",
):
    spec = MagicMock()
    spec.title = title
    spec.slug = slug
    spec.status = status
    spec.updated = updated
    spec.github_url = github_url
    return spec


class TestRunStaleCheck:
    async def test_skips_when_no_slack_token(self):
        with patch(
            "canon.cron.stale_specs.Settings",
            return_value=_make_settings(slack_bot_token=""),
        ):
            result = await run_stale_check()

        assert result == {"skipped": True}

    async def test_skips_when_slack_extension_unavailable(self):
        with (
            patch(
                "canon.cron.stale_specs.Settings",
                return_value=_make_settings(),
            ),
            patch.dict("sys.modules", {"canon.slack": MagicMock(SLACK_AVAILABLE=False)}),
            patch("canon.cron.stale_specs.Settings", return_value=_make_settings()),
        ):
            # Re-import to pick up the mock
            result = await run_stale_check()

        assert result.get("skipped") is True

    async def test_returns_error_on_load_failure(self):
        mock_loader = MagicMock()
        mock_loader.has_load_error = True
        mock_loader.load_error = "GitHub API error"
        mock_loader.load = AsyncMock()

        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = True
        mock_slack_mod.SpecLoader = MagicMock(return_value=mock_loader)

        with (
            patch(
                "canon.cron.stale_specs.Settings",
                return_value=_make_settings(),
            ),
            patch.dict("sys.modules", {"canon.slack": mock_slack_mod}),
            patch("canon.github.client.GitHubClient"),
        ):
            result = await run_stale_check()

        assert result == {"error": "GitHub API error"}

    async def test_no_stale_specs_returns_zero(self):
        recent = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        spec = _make_spec(updated=recent)

        mock_loader = MagicMock()
        mock_loader.has_load_error = False
        mock_loader.specs = [spec]
        mock_loader.load = AsyncMock()

        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = True
        mock_slack_mod.SpecLoader = MagicMock(return_value=mock_loader)

        with (
            patch(
                "canon.cron.stale_specs.Settings",
                return_value=_make_settings(),
            ),
            patch.dict("sys.modules", {"canon.slack": mock_slack_mod}),
            patch("canon.github.client.GitHubClient"),
        ):
            result = await run_stale_check()

        assert result == {"stale_count": 0}

    async def test_detects_stale_specs_and_sends_notifications(self):
        old_date = (datetime.now(UTC) - timedelta(days=DEFAULT_STALE_DAYS + 10)).isoformat()
        stale_spec = _make_spec(title="Old Feature", slug="old-feature", updated=old_date)
        recent_spec = _make_spec(
            title="New Feature",
            slug="new-feature",
            updated=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )

        mock_loader = MagicMock()
        mock_loader.has_load_error = False
        mock_loader.specs = [stale_spec, recent_spec]
        mock_loader.load = AsyncMock()

        mock_dispatcher = AsyncMock()
        mock_dispatcher.send_stale_spec_warning = AsyncMock()

        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = True
        mock_slack_mod.SpecLoader = MagicMock(return_value=mock_loader)
        mock_slack_mod.NotificationConfig = MagicMock
        mock_slack_mod.NotificationDispatcher = MagicMock(return_value=mock_dispatcher)

        mock_client = AsyncMock()
        mock_client.get_file_content = AsyncMock(side_effect=FileNotFoundError("no config"))

        with (
            patch(
                "canon.cron.stale_specs.Settings",
                return_value=_make_settings(),
            ),
            patch.dict(
                "sys.modules",
                {
                    "canon.slack": mock_slack_mod,
                    "slack_sdk.web.async_client": MagicMock(),
                },
            ),
            patch("canon.github.client.GitHubClient", return_value=mock_client),
            patch("canon.cron.stale_specs.analytics"),
        ):
            result = await run_stale_check()

        assert result["stale_count"] == 1
        assert result["sent"] == 1
        mock_dispatcher.send_stale_spec_warning.assert_awaited_once()

    async def test_skips_done_and_archived_specs(self):
        old_date = (datetime.now(UTC) - timedelta(days=DEFAULT_STALE_DAYS + 10)).isoformat()
        done_spec = _make_spec(status="done", updated=old_date)
        archived_spec = _make_spec(status="archived", updated=old_date)

        mock_loader = MagicMock()
        mock_loader.has_load_error = False
        mock_loader.specs = [done_spec, archived_spec]
        mock_loader.load = AsyncMock()

        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = True
        mock_slack_mod.SpecLoader = MagicMock(return_value=mock_loader)

        with (
            patch(
                "canon.cron.stale_specs.Settings",
                return_value=_make_settings(),
            ),
            patch.dict("sys.modules", {"canon.slack": mock_slack_mod}),
            patch("canon.github.client.GitHubClient"),
        ):
            result = await run_stale_check()

        assert result == {"stale_count": 0}

    async def test_skips_spec_without_updated_date(self):
        spec = _make_spec(updated=None)

        mock_loader = MagicMock()
        mock_loader.has_load_error = False
        mock_loader.specs = [spec]
        mock_loader.load = AsyncMock()

        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = True
        mock_slack_mod.SpecLoader = MagicMock(return_value=mock_loader)

        with (
            patch(
                "canon.cron.stale_specs.Settings",
                return_value=_make_settings(),
            ),
            patch.dict("sys.modules", {"canon.slack": mock_slack_mod}),
            patch("canon.github.client.GitHubClient"),
        ):
            result = await run_stale_check()

        assert result == {"stale_count": 0}
