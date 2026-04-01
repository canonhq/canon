"""Tests for IntegrationStore data access layer."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from canon.db.integration_store import IntegrationStore


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock pool whose acquire() returns an async context manager."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


FAKE_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # 32 bytes base64


class TestUpsertIntegration:
    @patch("canon.db.integration_store.encrypt_api_key", return_value=b"encrypted")
    async def test_inserts_integration(self, mock_encrypt):
        mock_conn = AsyncMock()
        row = {
            "id": "uuid-1",
            "org_login": "acme",
            "provider": "jira",
            "display_name": "Acme Jira",
            "status": "active",
            "provider_metadata": json.dumps({"site_url": "https://acme.atlassian.net"}),
            "connected_by": 1,
            "connected_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        result = await store.upsert_integration(
            org_login="acme",
            provider="jira",
            display_name="Acme Jira",
            config={"access_token": "secret", "cloud_id": "abc"},
            provider_metadata={"site_url": "https://acme.atlassian.net"},
            connected_by=1,
        )
        assert result["provider"] == "jira"
        assert result["display_name"] == "Acme Jira"
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO org_integrations" in sql
        assert "ON CONFLICT" in sql
        # Verify config was serialized then encrypted
        mock_encrypt.assert_called_once()
        encrypted_input = mock_encrypt.call_args[0][0]
        parsed = json.loads(encrypted_input)
        assert parsed["access_token"] == "secret"


class TestGetIntegration:
    async def test_found(self):
        mock_conn = AsyncMock()
        row = {
            "id": "uuid-1",
            "org_login": "acme",
            "provider": "jira",
            "display_name": "Acme Jira",
            "status": "active",
            "provider_metadata": json.dumps({}),
            "connected_by": 1,
            "connected_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        result = await store.get_integration("acme", "jira")
        assert result is not None
        assert result["provider"] == "jira"
        # No encrypted_config in response
        assert "encrypted_config" not in result

    async def test_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        result = await store.get_integration("acme", "linear")
        assert result is None


class TestGetIntegrationConfig:
    @patch(
        "canon.db.integration_store.decrypt_api_key",
        return_value='{"access_token":"secret","cloud_id":"abc"}',
    )
    async def test_decrypts_config(self, mock_decrypt):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"encrypted_config": b"encrypted"})
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        config = await store.get_integration_config("acme", "jira")
        assert config is not None
        assert config["access_token"] == "secret"
        assert config["cloud_id"] == "abc"
        mock_decrypt.assert_called_once_with(b"encrypted", FAKE_KEY)

    async def test_returns_none_when_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        config = await store.get_integration_config("acme", "jira")
        assert config is None


class TestListIntegrations:
    async def test_returns_list(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": "uuid-1",
                    "org_login": "acme",
                    "provider": "jira",
                    "display_name": "Acme Jira",
                    "status": "active",
                    "provider_metadata": json.dumps({}),
                    "connected_by": 1,
                    "connected_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                },
                {
                    "id": "uuid-2",
                    "org_login": "acme",
                    "provider": "linear",
                    "display_name": "Acme Linear",
                    "status": "active",
                    "provider_metadata": json.dumps({}),
                    "connected_by": 1,
                    "connected_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                },
            ]
        )
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        integrations = await store.list_integrations("acme")
        assert len(integrations) == 2
        assert integrations[0]["provider"] == "jira"
        assert integrations[1]["provider"] == "linear"


class TestDeleteIntegration:
    async def test_delete_success(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        result = await store.delete_integration("acme", "jira")
        assert result is True

    async def test_delete_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        result = await store.delete_integration("acme", "linear")
        assert result is False


class TestUpdateStatus:
    async def test_updates_status(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        result = await store.update_status("acme", "jira", "needs_reauth")
        assert result is True
        sql = mock_conn.execute.call_args[0][0]
        assert "UPDATE org_integrations" in sql
        assert "status" in sql


class TestUpdateConfig:
    @patch("canon.db.integration_store.encrypt_api_key", return_value=b"new_encrypted")
    async def test_updates_config_with_metadata(self, mock_encrypt):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        result = await store.update_config(
            "acme",
            "jira",
            config={"access_token": "new_token"},
            provider_metadata={"refreshed": True},
        )
        assert result is True
        sql = mock_conn.execute.call_args[0][0]
        assert "provider_metadata" in sql

    @patch("canon.db.integration_store.encrypt_api_key", return_value=b"new_encrypted")
    async def test_updates_config_without_metadata(self, mock_encrypt):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        result = await store.update_config("acme", "jira", config={"access_token": "new_token"})
        assert result is True


class TestGetSummary:
    async def test_summary_counts(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {"provider": "jira", "status": "active"},
                {"provider": "linear", "status": "active"},
                {"provider": "slack", "status": "needs_reauth"},
            ]
        )
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        summary = await store.get_summary("acme")
        assert summary["total"] == 3
        assert summary["connected"] == 2
        assert summary["needs_attention"] == 1

    async def test_empty_summary(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        pool = _mock_pool_with_conn(mock_conn)
        store = IntegrationStore(pool, FAKE_KEY)

        summary = await store.get_summary("acme")
        assert summary["total"] == 0
        assert summary["connected"] == 0
        assert summary["needs_attention"] == 0
