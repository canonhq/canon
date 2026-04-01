"""Data access layer for user VCS connections (e.g. GitHub OAuth tokens)."""

from __future__ import annotations

import logging
from datetime import datetime

import asyncpg

from canon.billing.encryption import decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)


class UserConnectionStore:
    """CRUD for the user_connections table (user-level VCS OAuth tokens)."""

    def __init__(self, pool: asyncpg.Pool, encryption_key: str) -> None:
        self._pool = pool
        self._encryption_key = encryption_key

    async def upsert_connection(
        self,
        *,
        user_id: int,
        provider: str,
        provider_user_id: str,
        provider_login: str,
        access_token: str,
        refresh_token: str | None = None,
        scopes: list[str] | None = None,
        token_expires_at: datetime | None = None,
    ) -> dict:
        """Insert or update a user connection, encrypting tokens at rest."""
        encrypted_token = encrypt_api_key(access_token, self._encryption_key)
        encrypted_refresh = (
            encrypt_api_key(refresh_token, self._encryption_key) if refresh_token else None
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO user_connections
                    (user_id, provider, provider_user_id, provider_login,
                     encrypted_token, refresh_token, scopes, token_expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (user_id, provider)
                DO UPDATE SET
                    provider_user_id = EXCLUDED.provider_user_id,
                    provider_login = EXCLUDED.provider_login,
                    encrypted_token = EXCLUDED.encrypted_token,
                    refresh_token = EXCLUDED.refresh_token,
                    scopes = EXCLUDED.scopes,
                    token_expires_at = EXCLUDED.token_expires_at,
                    updated_at = now()
                RETURNING id, user_id, provider, provider_user_id, provider_login,
                          scopes, token_expires_at, connected_at, updated_at
                """,
                user_id,
                provider,
                provider_user_id,
                provider_login,
                encrypted_token,
                encrypted_refresh,
                scopes or [],
                token_expires_at,
            )
        return dict(row)

    async def get_connection(self, user_id: int, provider: str) -> dict | None:
        """Get a user connection (without decrypted token — use get_token for that)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, provider, provider_user_id, provider_login,
                       scopes, token_expires_at, connected_at, updated_at
                FROM user_connections
                WHERE user_id = $1 AND provider = $2
                """,
                user_id,
                provider,
            )
        return dict(row) if row else None

    async def get_token(self, user_id: int, provider: str) -> str | None:
        """Decrypt and return the access token for a user connection."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT encrypted_token FROM user_connections WHERE user_id = $1 AND provider = $2",
                user_id,
                provider,
            )
        if not row:
            return None
        return decrypt_api_key(row["encrypted_token"], self._encryption_key)

    async def get_refresh_token(self, user_id: int, provider: str) -> str | None:
        """Decrypt and return the refresh token for a user connection."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT refresh_token FROM user_connections WHERE user_id = $1 AND provider = $2",
                user_id,
                provider,
            )
        if not row or not row["refresh_token"]:
            return None
        return decrypt_api_key(row["refresh_token"], self._encryption_key)

    async def list_connections(self, user_id: int) -> list[dict]:
        """List all connections for a user (no tokens returned)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, provider, provider_user_id, provider_login,
                       scopes, token_expires_at, connected_at, updated_at
                FROM user_connections
                WHERE user_id = $1
                ORDER BY connected_at DESC
                """,
                user_id,
            )
        return [dict(r) for r in rows]

    async def delete_connection(self, user_id: int, provider: str) -> bool:
        """Delete a user connection. Returns True if a row was deleted."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM user_connections WHERE user_id = $1 AND provider = $2",
                user_id,
                provider,
            )
        return result == "DELETE 1"

    async def update_token(
        self,
        user_id: int,
        provider: str,
        *,
        access_token: str,
        refresh_token: str | None = None,
        token_expires_at: datetime | None = None,
    ) -> bool:
        """Update tokens after a refresh. Returns True if updated."""
        encrypted_token = encrypt_api_key(access_token, self._encryption_key)
        encrypted_refresh = (
            encrypt_api_key(refresh_token, self._encryption_key) if refresh_token else None
        )
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE user_connections
                SET encrypted_token = $3,
                    refresh_token = COALESCE($4, refresh_token),
                    token_expires_at = $5,
                    updated_at = now()
                WHERE user_id = $1 AND provider = $2
                """,
                user_id,
                provider,
                encrypted_token,
                encrypted_refresh,
                token_expires_at,
            )
        return result == "UPDATE 1"

    async def mark_needs_reauth(self, user_id: int, provider: str) -> bool:
        """Flag a connection as needing re-authorization (e.g. refresh failed).

        Note: user_connections doesn't have a status column currently,
        so we set token_expires_at to the past as a signal. The UI checks
        token_expires_at to determine if reauth is needed.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE user_connections
                SET token_expires_at = '1970-01-01T00:00:00Z', updated_at = now()
                WHERE user_id = $1 AND provider = $2
                """,
                user_id,
                provider,
            )
        return result == "UPDATE 1"
