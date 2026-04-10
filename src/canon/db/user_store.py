"""Data access layer for users and API keys."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from base64 import urlsafe_b64encode
from datetime import datetime

import asyncpg

logger = logging.getLogger(__name__)

#: API key prefix.
API_KEY_PREFIX = "sw_"

#: Minimum interval (seconds) between last_used_at DB writes per key hash.
_LAST_USED_UPDATE_INTERVAL = 300  # 5 minutes


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key and its SHA-256 hash.

    Returns (raw_key, key_hash).  The raw key is shown once to the user;
    the hash is stored in the database.
    """
    raw_bytes = secrets.token_bytes(32)
    raw_key = API_KEY_PREFIX + urlsafe_b64encode(raw_bytes).rstrip(b"=").decode()
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, key_hash


class UserStore:
    """Data access layer for users + API keys tables."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        # Per-instance set to prevent background tasks from being GC'd
        self._background_tasks: set[asyncio.Task] = set()
        # Rate-limit last_used_at writes: key_hash → monotonic timestamp
        self._last_used_cache: dict[str, float] = {}

    # ─── Users ────────────────────────────────────────

    async def upsert_user(
        self,
        *,
        oidc_sub: str,
        email: str = "",
        name: str = "",
        picture: str = "",
    ) -> dict:
        """Insert or update a user, returning the user record as a dict."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users (oidc_sub, email, name, picture, last_login_at)
                VALUES ($1, $2, $3, $4, now())
                ON CONFLICT (oidc_sub)
                DO UPDATE SET
                    email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    picture = EXCLUDED.picture,
                    last_login_at = now()
                RETURNING *, (xmax = 0) AS is_new
                """,
                oidc_sub,
                email,
                name,
                picture,
            )
        return dict(row)

    async def get_user_by_sub(self, oidc_sub: str) -> dict | None:
        """Look up a user by OIDC subject."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE oidc_sub = $1",
                oidc_sub,
            )
        return dict(row) if row else None

    async def count_users(self) -> int:
        """Return the total number of users in the database."""
        async with self._pool.acquire() as conn:
            result = await conn.fetchval("SELECT COUNT(*) FROM users")
        return int(result)

    async def set_user_role(self, *, user_id: int, role: str) -> None:
        """Update a user's role.  Used for first-user bootstrap and admin promotion."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET role = $1 WHERE id = $2",
                role,
                user_id,
            )

    async def promote_first_user_to_admin(self, user_id: int) -> bool:
        """Atomically promote user to admin IFF no admin exists yet.

        Returns True if the user was promoted, False if an admin already exists.
        This avoids TOCTOU races when two users sign up simultaneously.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE users SET role = 'admin'
                WHERE id = $1
                  AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'admin')
                """,
                user_id,
            )
        return result == "UPDATE 1"

    # ─── API Keys ─────────────────────────────────────

    async def create_api_key(
        self,
        *,
        user_id: int,
        org_login: str,
        scopes: list[str],
        label: str = "",
        expires_at: datetime | None = None,
    ) -> tuple[str, dict]:
        """Create a new API key.

        Returns (raw_key, api_key_record).  The raw_key is only returned
        once — it cannot be retrieved later.
        """
        raw_key, key_hash = generate_api_key()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO api_keys (key_hash, label, user_id, org_login, scopes, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                key_hash,
                label,
                user_id,
                org_login,
                scopes,
                expires_at,
            )
        return raw_key, dict(row)

    async def get_api_key_by_hash(self, key_hash: str) -> dict | None:
        """Look up an API key by its SHA-256 hash, joining user info."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    ak.*,
                    u.oidc_sub AS user_sub,
                    u.email AS user_email,
                    u.name AS user_name,
                    u.status AS user_status
                FROM api_keys ak
                JOIN users u ON u.id = ak.user_id
                WHERE ak.key_hash = $1
                """,
                key_hash,
            )
        if row is None:
            return None
        # Rate-limited fire-and-forget last_used_at update
        now = time.monotonic()
        last = self._last_used_cache.get(key_hash, 0.0)
        if now - last >= _LAST_USED_UPDATE_INTERVAL:
            self._last_used_cache[key_hash] = now
            task = asyncio.create_task(self._update_last_used(key_hash))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        return dict(row)

    async def _update_last_used(self, key_hash: str) -> None:
        """Update last_used_at timestamp (best-effort, background)."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE api_keys SET last_used_at = now() WHERE key_hash = $1",
                    key_hash,
                )
        except Exception:
            logger.debug("Failed to update last_used_at for key", exc_info=True)

    async def list_api_keys(self, *, user_id: int, org_login: str) -> list[dict]:
        """List API keys for a user in an org (excludes the raw key)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, label, org_login, scopes, created_at, expires_at, revoked_at, last_used_at
                FROM api_keys
                WHERE user_id = $1 AND org_login = $2
                ORDER BY created_at DESC
                """,
                user_id,
                org_login,
            )
        return [dict(r) for r in rows]

    async def revoke_api_key(self, *, key_id: int, user_id: int, org_login: str) -> bool:
        """Revoke an API key.  Returns True if the key was found and revoked."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE api_keys
                SET revoked_at = now()
                WHERE id = $1 AND user_id = $2 AND org_login = $3 AND revoked_at IS NULL
                """,
                key_id,
                user_id,
                org_login,
            )
        return result == "UPDATE 1"

    async def revoke_all_api_keys(self, *, user_id: int) -> int:
        """Revoke all active API keys for a user.  Returns count revoked."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE api_keys
                SET revoked_at = now()
                WHERE user_id = $1 AND revoked_at IS NULL
                """,
                user_id,
            )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def delete_expired_keys(self) -> int:
        """Delete API keys that expired more than 30 days ago.  Returns count deleted."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM api_keys WHERE expires_at IS NOT NULL AND expires_at < now() - INTERVAL '30 days'",
            )
        # result is like "DELETE 5"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0
