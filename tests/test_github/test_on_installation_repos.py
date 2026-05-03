"""Tests for installation_repositories event handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from canon.github.handlers.on_installation_repos import on_installation_repositories


def _make_payload(
    added: list[dict] | None = None,
    removed: list[dict] | None = None,
) -> dict:
    return {
        "action": "added",
        "installation": {
            "id": 12345,
            "account": {"login": "test-org", "id": 111},
        },
        "repositories_added": added or [],
        "repositories_removed": removed or [],
    }


def _make_state(**overrides):
    state = MagicMock()
    state.registry = overrides.get("registry", AsyncMock())
    state.indexer = overrides.get("indexer", MagicMock())
    state.search_index = overrides.get("search_index", MagicMock())
    state.embed_client = overrides.get("embed_client", MagicMock())
    return state


class TestOnInstallationReposOnboarding:
    async def test_fires_onboarding_for_added_repos(self):
        """Verify fire_and_forget is called with onboard_repos for added repos."""
        state = _make_state()
        client = AsyncMock()
        added = [{"full_name": "test-org/api"}, {"full_name": "test-org/web"}]
        payload = _make_payload(added=added)

        with patch("canon.github.handlers.on_installation_repos.fire_and_forget") as mock_ff:
            await on_installation_repositories(client, payload, _app_state=state)

        mock_ff.assert_called_once()

    async def test_no_onboarding_without_added_repos(self):
        """No fire_and_forget call when no repos were added."""
        state = _make_state()
        client = AsyncMock()
        payload = _make_payload(added=[], removed=[{"full_name": "test-org/old"}])

        with patch("canon.github.handlers.on_installation_repos.fire_and_forget") as mock_ff:
            await on_installation_repositories(client, payload, _app_state=state)

        mock_ff.assert_not_called()

    async def test_opensearch_repo_cleanup_runs_after_postgres_succeeds(self):
        """OpenSearch delete_repo must run regardless of whether the
        Postgres search_index.delete_repo raised — both stores need to be
        cleaned up on uninstall to avoid stale spec content remaining
        searchable."""
        search_index = MagicMock()
        search_index.delete_repo = AsyncMock(return_value=None)  # PG succeeds
        opensearch = MagicMock()
        opensearch.delete_repo = AsyncMock()
        state = _make_state(search_index=search_index)
        state.opensearch_client = opensearch

        client = AsyncMock()
        payload = _make_payload(removed=[{"full_name": "test-org/old"}])

        await on_installation_repositories(client, payload, _app_state=state)

        opensearch.delete_repo.assert_awaited_once_with("test-org/old")

    async def test_opensearch_repo_cleanup_still_runs_when_postgres_fails(self):
        """If the Postgres delete raises, OpenSearch cleanup must still
        fire — they're independent stores."""
        search_index = MagicMock()
        search_index.delete_repo = AsyncMock(side_effect=RuntimeError("PG down"))
        opensearch = MagicMock()
        opensearch.delete_repo = AsyncMock()
        state = _make_state(search_index=search_index)
        state.opensearch_client = opensearch

        client = AsyncMock()
        payload = _make_payload(removed=[{"full_name": "test-org/old"}])

        await on_installation_repositories(client, payload, _app_state=state)

        opensearch.delete_repo.assert_awaited_once_with("test-org/old")
