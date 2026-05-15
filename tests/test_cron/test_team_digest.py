"""Tests for the team digest delivery cron job."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from canon.cron.team_digest import run_team_digest


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


class TestRunTeamDigest:
    async def test_skips_when_no_slack_token(self):
        with patch(
            "canon.cron.team_digest.Settings",
            return_value=_make_settings(slack_bot_token=""),
        ):
            result = await run_team_digest()

        assert result == {"skipped": True}

    async def test_skips_when_slack_extension_unavailable(self):
        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = False

        with (
            patch(
                "canon.cron.team_digest.Settings",
                return_value=_make_settings(),
            ),
            patch.dict("sys.modules", {"canon.slack": mock_slack_mod}),
        ):
            result = await run_team_digest()

        assert result.get("skipped") is True

    async def test_skips_when_no_team_digests_configured(self):
        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = True

        mock_client = AsyncMock()
        mock_client.get_file_content = AsyncMock(side_effect=FileNotFoundError)

        mock_parse_result = MagicMock()
        mock_parse_result.config = None

        with (
            patch(
                "canon.cron.team_digest.Settings",
                return_value=_make_settings(),
            ),
            patch.dict("sys.modules", {"canon.slack": mock_slack_mod}),
            patch("canon.github.client.GitHubClient", return_value=mock_client),
            patch.dict(
                "sys.modules",
                {
                    "canon.config.parse": MagicMock(
                        parse_canon_yaml=MagicMock(return_value=mock_parse_result)
                    ),
                },
            ),
        ):
            result = await run_team_digest()

        assert result.get("skipped") is True

    async def test_sends_digests_to_configured_teams(self):
        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = True
        mock_slack_mod.SpecLoader = MagicMock()
        mock_slack_mod.build_digest_blocks = MagicMock(return_value=[{"type": "section"}])

        mock_loader = MagicMock()
        mock_loader.has_load_error = False
        mock_loader.specs = []
        mock_loader.load = AsyncMock()
        mock_loader.coverage_stats = MagicMock(return_value={"pct_done": 75.0})
        mock_slack_mod.SpecLoader.return_value = mock_loader

        # Team config
        team_config = MagicMock()
        team_config.channel = "#team-backend"

        # CANON.yaml parse result
        mock_config = MagicMock()
        mock_config.config.slack.digest.team_digests = {"backend": team_config}

        mock_client = AsyncMock()
        mock_client.get_file_content = AsyncMock(return_value=("yaml-content", "sha"))

        mock_slack_client = AsyncMock()
        mock_slack_client.chat_postMessage = AsyncMock()

        with (
            patch(
                "canon.cron.team_digest.Settings",
                return_value=_make_settings(),
            ),
            patch.dict(
                "sys.modules",
                {
                    "canon.slack": mock_slack_mod,
                    "slack_sdk.web.async_client": MagicMock(
                        AsyncWebClient=MagicMock(return_value=mock_slack_client)
                    ),
                },
            ),
            patch("canon.github.client.GitHubClient", return_value=mock_client),
            patch("canon.config.parse.parse_canon_yaml", return_value=mock_config),
            patch("canon.cron.team_digest.analytics"),
        ):
            result = await run_team_digest()

        assert result["sent"] == 1
        assert result["errors"] == 0
        mock_slack_client.chat_postMessage.assert_awaited_once()

    async def test_counts_send_failures_as_errors(self):
        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = True
        mock_slack_mod.SpecLoader = MagicMock()
        mock_slack_mod.build_digest_blocks = MagicMock(return_value=[])

        mock_loader = MagicMock()
        mock_loader.has_load_error = False
        mock_loader.specs = []
        mock_loader.load = AsyncMock()
        mock_loader.coverage_stats = MagicMock(return_value={"pct_done": 50.0})
        mock_slack_mod.SpecLoader.return_value = mock_loader

        team_config = MagicMock()
        team_config.channel = "#team-frontend"

        mock_config = MagicMock()
        mock_config.config.slack.digest.team_digests = {"frontend": team_config}

        mock_client = AsyncMock()
        mock_client.get_file_content = AsyncMock(return_value=("yaml", "sha"))

        mock_slack_client = AsyncMock()
        mock_slack_client.chat_postMessage = AsyncMock(
            side_effect=RuntimeError("channel_not_found")
        )

        with (
            patch(
                "canon.cron.team_digest.Settings",
                return_value=_make_settings(),
            ),
            patch.dict(
                "sys.modules",
                {
                    "canon.slack": mock_slack_mod,
                    "slack_sdk.web.async_client": MagicMock(
                        AsyncWebClient=MagicMock(return_value=mock_slack_client)
                    ),
                },
            ),
            patch("canon.github.client.GitHubClient", return_value=mock_client),
            patch("canon.config.parse.parse_canon_yaml", return_value=mock_config),
            patch("canon.cron.team_digest.analytics"),
        ):
            result = await run_team_digest()

        assert result["sent"] == 0
        assert result["errors"] == 1

    async def test_returns_error_when_specs_fail_to_load(self):
        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = True
        mock_slack_mod.SpecLoader = MagicMock()

        mock_loader = MagicMock()
        mock_loader.has_load_error = True
        mock_loader.load_error = "GitHub rate limited"
        mock_loader.load = AsyncMock()
        mock_slack_mod.SpecLoader.return_value = mock_loader

        team_config = MagicMock()
        team_config.channel = "#team"

        mock_config = MagicMock()
        mock_config.config.slack.digest.team_digests = {"team": team_config}

        mock_client = AsyncMock()
        mock_client.get_file_content = AsyncMock(return_value=("yaml", "sha"))

        with (
            patch(
                "canon.cron.team_digest.Settings",
                return_value=_make_settings(),
            ),
            patch.dict(
                "sys.modules",
                {
                    "canon.slack": mock_slack_mod,
                },
            ),
            patch("canon.github.client.GitHubClient", return_value=mock_client),
            patch("canon.config.parse.parse_canon_yaml", return_value=mock_config),
        ):
            result = await run_team_digest()

        assert result == {"error": "GitHub rate limited"}

    async def test_tracks_analytics_event(self):
        mock_slack_mod = MagicMock()
        mock_slack_mod.SLACK_AVAILABLE = True
        mock_slack_mod.SpecLoader = MagicMock()
        mock_slack_mod.build_digest_blocks = MagicMock(return_value=[])

        mock_loader = MagicMock()
        mock_loader.has_load_error = False
        mock_loader.specs = []
        mock_loader.load = AsyncMock()
        mock_loader.coverage_stats = MagicMock(return_value={"pct_done": 80.0})
        mock_slack_mod.SpecLoader.return_value = mock_loader

        team_config = MagicMock()
        team_config.channel = "#ops"

        mock_config = MagicMock()
        mock_config.config.slack.digest.team_digests = {"ops": team_config}

        mock_client = AsyncMock()
        mock_client.get_file_content = AsyncMock(return_value=("yaml", "sha"))

        mock_slack_client = AsyncMock()
        mock_slack_client.chat_postMessage = AsyncMock()

        with (
            patch(
                "canon.cron.team_digest.Settings",
                return_value=_make_settings(),
            ),
            patch.dict(
                "sys.modules",
                {
                    "canon.slack": mock_slack_mod,
                    "slack_sdk.web.async_client": MagicMock(
                        AsyncWebClient=MagicMock(return_value=mock_slack_client)
                    ),
                },
            ),
            patch("canon.github.client.GitHubClient", return_value=mock_client),
            patch("canon.config.parse.parse_canon_yaml", return_value=mock_config),
            patch("canon.cron.team_digest.analytics") as mock_analytics,
        ):
            await run_team_digest()

        mock_analytics.track.assert_called_once_with(
            "team_digest_sent",
            properties={
                "teams_configured": 1,
                "sent": 1,
                "errors": 0,
            },
        )
