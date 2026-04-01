"""Tests for UserConnectionStore data access layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from canon.db.connection_store import UserConnectionStore


def _mock_pool_with_conn(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock pool whose acquire() returns an async context manager."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


FAKE_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # 32 bytes base64


class TestUpsertConnection:
    @patch("canon.db.connection_store.encrypt_api_key", return_value=b"encrypted")
    async def test_inserts_connection(self, mock_encrypt):
        mock_conn = AsyncMock()
        row = {
            "id": "uuid-1",
            "user_id": 1,
            "provider": "github",
            "provider_user_id": "12345",
            "provider_login": "octocat",
            "scopes": ["repo", "read:user"],
            "token_expires_at": None,
            "connected_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        result = await store.upsert_connection(
            user_id=1,
            provider="github",
            provider_user_id="12345",
            provider_login="octocat",
            access_token="gho_abc123",
            scopes=["repo", "read:user"],
        )
        assert result["provider"] == "github"
        assert result["provider_login"] == "octocat"
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO user_connections" in sql
        assert "ON CONFLICT" in sql
        mock_encrypt.assert_called_once_with("gho_abc123", FAKE_KEY)

    @patch("canon.db.connection_store.encrypt_api_key", return_value=b"encrypted")
    async def test_encrypts_refresh_token(self, mock_encrypt):
        mock_conn = AsyncMock()
        row = {
            "id": "uuid-1",
            "user_id": 1,
            "provider": "github",
            "provider_user_id": "12345",
            "provider_login": "octocat",
            "scopes": [],
            "token_expires_at": None,
            "connected_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        await store.upsert_connection(
            user_id=1,
            provider="github",
            provider_user_id="12345",
            provider_login="octocat",
            access_token="gho_abc",
            refresh_token="ghr_refresh",
        )
        assert mock_encrypt.call_count == 2
        mock_encrypt.assert_any_call("gho_abc", FAKE_KEY)
        mock_encrypt.assert_any_call("ghr_refresh", FAKE_KEY)


class TestGetConnection:
    async def test_found(self):
        mock_conn = AsyncMock()
        row = {
            "id": "uuid-1",
            "user_id": 1,
            "provider": "github",
            "provider_user_id": "12345",
            "provider_login": "octocat",
            "scopes": ["repo"],
            "token_expires_at": None,
            "connected_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        mock_conn.fetchrow = AsyncMock(return_value=row)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        result = await store.get_connection(1, "github")
        assert result is not None
        assert result["provider_login"] == "octocat"
        # Verify no encrypted_token in response
        assert "encrypted_token" not in result

    async def test_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        result = await store.get_connection(1, "gitlab")
        assert result is None


class TestGetToken:
    @patch("canon.db.connection_store.decrypt_api_key", return_value="gho_decrypted")
    async def test_decrypts_token(self, mock_decrypt):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"encrypted_token": b"encrypted"})
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        token = await store.get_token(1, "github")
        assert token == "gho_decrypted"
        mock_decrypt.assert_called_once_with(b"encrypted", FAKE_KEY)

    async def test_returns_none_when_no_connection(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        token = await store.get_token(1, "github")
        assert token is None


class TestListConnections:
    async def test_returns_list(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": "uuid-1",
                    "provider": "github",
                    "provider_user_id": "12345",
                    "provider_login": "octocat",
                    "scopes": ["repo"],
                    "token_expires_at": None,
                    "connected_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                },
            ]
        )
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        conns = await store.list_connections(1)
        assert len(conns) == 1
        assert conns[0]["provider"] == "github"


class TestDeleteConnection:
    async def test_delete_success(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        result = await store.delete_connection(1, "github")
        assert result is True

    async def test_delete_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        result = await store.delete_connection(1, "gitlab")
        assert result is False


class TestUpdateToken:
    @patch("canon.db.connection_store.encrypt_api_key", return_value=b"new_encrypted")
    async def test_updates_token(self, mock_encrypt):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        result = await store.update_token(
            1, "github", access_token="gho_new", refresh_token="ghr_new"
        )
        assert result is True
        assert mock_encrypt.call_count == 2


class TestMarkNeedsReauth:
    async def test_marks_reauth(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = _mock_pool_with_conn(mock_conn)
        store = UserConnectionStore(pool, FAKE_KEY)

        result = await store.mark_needs_reauth(1, "github")
        assert result is True
        sql = mock_conn.execute.call_args[0][0]
        assert "token_expires_at" in sql
