"""Tests for installation event handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from canon.db.registry import Installation
from canon.github.handlers.on_installation import on_installation


def _make_payload(action: str, installation_id: int = 12345, org: str = "test-org") -> dict:
    return {
        "action": action,
        "installation": {
            "id": installation_id,
            "app_id": 3012101,
            "account": {
                "login": org,
                "id": 111,
            },
        },
    }


def _make_state(**overrides):
    state = MagicMock()
    state.registry = overrides.get("registry", AsyncMock())
    state.indexer = overrides.get("indexer", MagicMock())
    state.search_index = overrides.get("search_index", MagicMock())
    state.embed_client = overrides.get("embed_client", MagicMock())
    state.oidc_provider = overrides.get("oidc_provider")
    return state


class TestOnInstallationCreated:
    async def test_upserts_and_schedules_indexing(self):
        state = _make_state()
        client = AsyncMock()

        await on_installation(client, _make_payload("created"), _app_state=state)

        state.registry.upsert_installation.assert_awaited_once()
        state.indexer.schedule_org_index.assert_called_once()

    async def test_skips_indexing_without_search_index(self):
        state = _make_state(search_index=None)
        client = AsyncMock()

        await on_installation(client, _make_payload("created"), _app_state=state)

        state.registry.upsert_installation.assert_awaited_once()
        state.indexer.schedule_org_index.assert_not_called()


class TestOnInstallationDeleted:
    async def test_marks_removed(self):
        state = _make_state()
        client = AsyncMock()

        await on_installation(client, _make_payload("deleted"), _app_state=state)
        state.registry.mark_removed.assert_awaited_once_with(12345)


class TestOnInstallationSuspend:
    async def test_marks_suspended(self):
        state = _make_state()
        client = AsyncMock()

        await on_installation(client, _make_payload("suspend"), _app_state=state)
        state.registry.mark_suspended.assert_awaited_once_with(12345)


class TestOnInstallationUnsuspend:
    async def test_marks_unsuspended(self):
        state = _make_state()
        client = AsyncMock()

        await on_installation(client, _make_payload("unsuspend"), _app_state=state)
        state.registry.mark_unsuspended.assert_awaited_once_with(12345)


class TestNoRegistry:
    async def test_skips_when_no_registry(self):
        state = _make_state(registry=None)
        client = AsyncMock()

        # Should not raise
        await on_installation(client, _make_payload("created"), _app_state=state)

    async def test_skips_when_no_state(self):
        client = AsyncMock()

        # Should not raise — no state at all
        await on_installation(client, _make_payload("created"), _app_state=None)


class TestOnInstallationOnboarding:
    async def test_fires_onboarding_for_created_with_repos(self):
        """Verify fire_and_forget is called with onboard_repos on 'created'."""
        state = _make_state()
        client = AsyncMock()
        repos = [{"full_name": "test-org/api"}, {"full_name": "test-org/web"}]
        payload = _make_payload("created")
        payload["repositories"] = repos

        with patch("canon.github.handlers.on_installation.fire_and_forget") as mock_ff:
            await on_installation(client, payload, _app_state=state)

        mock_ff.assert_called_once()

    async def test_no_onboarding_without_repos(self):
        """No fire_and_forget call when payload has no repositories."""
        state = _make_state()
        client = AsyncMock()
        payload = _make_payload("created")
        # No "repositories" key in payload

        with patch("canon.github.handlers.on_installation.fire_and_forget") as mock_ff:
            await on_installation(client, payload, _app_state=state)

        mock_ff.assert_not_called()


class TestAuth0Provisioning:
    async def test_provisions_auth0_org_on_created(self):
        """Verify fire_and_forget is called for Auth0 provisioning when provider exists."""
        state = _make_state()
        provider = AsyncMock()
        provider.create_organization = AsyncMock()
        state.oidc_provider = provider
        client = AsyncMock()
        payload = _make_payload("created")

        with patch("canon.github.handlers.on_installation.fire_and_forget") as mock_ff:
            await on_installation(client, payload, _app_state=state)

        # fire_and_forget called for Auth0 provisioning (no repos = only auth0 call)
        assert mock_ff.call_count == 1

    async def test_skips_auth0_without_provider(self):
        """No error when oidc_provider is not on state."""
        state = _make_state()
        # No oidc_provider attribute — delattr to ensure getattr returns None
        if hasattr(state, "oidc_provider"):
            del state.oidc_provider
        client = AsyncMock()
        payload = _make_payload("created")

        # Should not raise
        await on_installation(client, payload, _app_state=state)

    async def test_disables_auth0_org_on_deleted(self):
        """Verify disable_org_connections is called on uninstall."""
        state = _make_state()
        provider = AsyncMock()
        provider.disable_org_connections = AsyncMock()
        state.oidc_provider = provider
        state.registry.get_installation_by_id = AsyncMock(
            return_value=Installation(
                installation_id=12345, org_login="test-org", oidc_org_id="org_abc"
            )
        )
        client = AsyncMock()
        payload = _make_payload("deleted")

        with patch("canon.github.handlers.on_installation.fire_and_forget") as mock_ff:
            await on_installation(client, payload, _app_state=state)

        mock_ff.assert_called_once()

    async def test_skips_disable_without_oidc_org_id(self):
        """No disable call when installation has no oidc_org_id."""
        state = _make_state()
        provider = AsyncMock()
        provider.disable_org_connections = AsyncMock()
        state.oidc_provider = provider
        state.registry.get_installation_by_id = AsyncMock(
            return_value=Installation(installation_id=12345, org_login="test-org", oidc_org_id="")
        )
        client = AsyncMock()
        payload = _make_payload("deleted")

        with patch("canon.github.handlers.on_installation.fire_and_forget") as mock_ff:
            await on_installation(client, payload, _app_state=state)

        mock_ff.assert_not_called()


class TestProvisionAuth0Org:
    """Strict provisioning helper used by the admin repair endpoint."""

    async def _make_provider(self, *, existing_org: str | None = None) -> AsyncMock:
        provider = AsyncMock()
        provider.get_organization_by_name = AsyncMock(return_value=existing_org)
        provider.create_organization = AsyncMock(return_value="org_new")
        provider.get_connection_by_name = AsyncMock(side_effect=["conn_github", "conn_db"])
        provider.enable_org_connections = AsyncMock()
        return provider

    async def test_already_provisioned_short_circuits(self):
        from canon.github.handlers.on_installation import provision_auth0_org

        provider = await self._make_provider()
        registry = AsyncMock()
        registry.get_installation_by_id = AsyncMock(
            return_value=Installation(
                installation_id=12345, org_login="acme", oidc_org_id="org_existing"
            )
        )

        result = await provision_auth0_org(
            provider, registry, installation_id=12345, org_login="acme"
        )

        assert result.status == "already_provisioned"
        assert result.oidc_org_id == "org_existing"
        provider.get_organization_by_name.assert_not_called()
        provider.create_organization.assert_not_called()
        registry.set_oidc_org_id.assert_not_called()

    async def test_provisions_when_no_oidc_org_id(self):
        from canon.github.handlers.on_installation import provision_auth0_org

        provider = await self._make_provider(existing_org=None)
        registry = AsyncMock()
        registry.get_installation_by_id = AsyncMock(
            return_value=Installation(installation_id=12345, org_login="acme", oidc_org_id="")
        )

        result = await provision_auth0_org(
            provider, registry, installation_id=12345, org_login="acme"
        )

        assert result.status == "provisioned"
        assert result.oidc_org_id == "org_new"
        provider.create_organization.assert_awaited_once_with(name="acme", display_name="acme")
        provider.enable_org_connections.assert_awaited_once_with(
            "org_new", "conn_github", "conn_db"
        )
        registry.set_oidc_org_id.assert_awaited_once_with(12345, "org_new")

    async def test_reuses_existing_auth0_org(self):
        from canon.github.handlers.on_installation import provision_auth0_org

        provider = await self._make_provider(existing_org="org_was_orphaned")
        registry = AsyncMock()
        registry.get_installation_by_id = AsyncMock(
            return_value=Installation(installation_id=12345, org_login="acme", oidc_org_id="")
        )

        result = await provision_auth0_org(
            provider, registry, installation_id=12345, org_login="acme"
        )

        assert result.status == "reused"
        assert result.oidc_org_id == "org_was_orphaned"
        provider.create_organization.assert_not_called()
        # Connections still re-enabled to repair the partial-failure case
        provider.enable_org_connections.assert_awaited_once()
        registry.set_oidc_org_id.assert_awaited_once_with(12345, "org_was_orphaned")

    async def test_skip_if_set_false_runs_full_path(self):
        """Webhook path uses skip_if_set=False so reinstalls always rerun."""
        from canon.github.handlers.on_installation import provision_auth0_org

        provider = await self._make_provider(existing_org="org_existing")
        registry = AsyncMock()
        registry.get_installation_by_id = AsyncMock()  # not called

        result = await provision_auth0_org(
            provider,
            registry,
            installation_id=12345,
            org_login="acme",
            skip_if_set=False,
        )

        assert result.status == "reused"
        registry.get_installation_by_id.assert_not_called()
        provider.enable_org_connections.assert_awaited_once()

    async def test_raises_on_auth0_failure(self):
        """Strict variant must propagate so the admin endpoint can return 422."""
        from canon.github.handlers.on_installation import provision_auth0_org

        provider = await self._make_provider(existing_org=None)
        provider.create_organization = AsyncMock(side_effect=RuntimeError("auth0 down"))
        registry = AsyncMock()
        registry.get_installation_by_id = AsyncMock(
            return_value=Installation(installation_id=12345, org_login="acme", oidc_org_id="")
        )

        import pytest

        with pytest.raises(RuntimeError, match="auth0 down"):
            await provision_auth0_org(provider, registry, installation_id=12345, org_login="acme")
        registry.set_oidc_org_id.assert_not_called()
