"""Data access layer for refresh-token sessions."""

from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)


class SessionStore:
    """CRUD for the ``sessions`` table (refresh-token rotation)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_session(
        self,
        *,
        session_id: str,
        user_id: int,
        org_login: str,
        device_label: str,
        refresh_hash: str,
        expires_at,
    ) -> dict:
        """Insert a new session row and return it as a dict."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sessions (id, user_id, org_login, device_label, refresh_hash, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                session_id,
                user_id,
                org_login,
                device_label,
                refresh_hash,
                expires_at,
            )
        return dict(row)

    async def get_session_by_refresh_hash(self, refresh_hash: str) -> dict | None:
        """Look up a valid (non-revoked, non-expired) session by refresh hash.

        Joins the users table so callers get user info in one query.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    s.*,
                    u.oidc_sub AS user_sub,
                    u.email     AS user_email,
                    u.name      AS user_name
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.refresh_hash = $1
                  AND s.revoked_at IS NULL
                  AND s.expires_at > now()
                """,
                refresh_hash,
            )
        return dict(row) if row else None

    async def rotate_refresh(self, *, session_id: str, old_hash: str, new_hash: str) -> bool:
        """Atomically swap the refresh hash.  Returns True on success."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE sessions
                SET refresh_hash = $1, last_used_at = now()
                WHERE id = $2 AND refresh_hash = $3 AND revoked_at IS NULL
                """,
                new_hash,
                session_id,
                old_hash,
            )
        return result == "UPDATE 1"

    async def revoke_session(self, *, session_id: str, user_id: int) -> bool:
        """Revoke a single session.  Returns True if found and revoked."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE sessions
                SET revoked_at = now()
                WHERE id = $1 AND user_id = $2 AND revoked_at IS NULL
                """,
                session_id,
                user_id,
            )
        return result == "UPDATE 1"

    async def revoke_all_sessions(
        self, *, user_id: int, except_session_id: str | None = None
    ) -> int:
        """Revoke all sessions for a user, optionally keeping one."""
        async with self._pool.acquire() as conn:
            if except_session_id:
                result = await conn.execute(
                    """
                    UPDATE sessions
                    SET revoked_at = now()
                    WHERE user_id = $1 AND id != $2 AND revoked_at IS NULL
                    """,
                    user_id,
                    except_session_id,
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE sessions
                    SET revoked_at = now()
                    WHERE user_id = $1 AND revoked_at IS NULL
                    """,
                    user_id,
                )
        # asyncpg returns status strings like "UPDATE 3" or "DELETE 5"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def list_sessions(self, *, user_id: int, org_login: str) -> list[dict]:
        """List active sessions for a user in an org."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, device_label, created_at, last_used_at, expires_at
                FROM sessions
                WHERE user_id = $1 AND org_login = $2 AND revoked_at IS NULL AND expires_at > now()
                ORDER BY last_used_at DESC
                """,
                user_id,
                org_login,
            )
        return [dict(r) for r in rows]

    async def delete_expired_sessions(self) -> int:
        """Delete sessions that expired more than 30 days ago.

        A 30-day retention window is kept after expiry for audit purposes.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM sessions WHERE expires_at < now() - INTERVAL '30 days'",
            )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0
