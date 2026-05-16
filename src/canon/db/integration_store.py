"""Data access layer for org-level integration credentials (Jira, Linear, Slack, etc.)."""

from __future__ import annotations

import json
import logging

import asyncpg

from canon.billing.encryption import decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)


class IntegrationStore:
    """CRUD for the org_integrations table (org-level OAuth/API credentials)."""

    def __init__(self, pool: asyncpg.Pool, encryption_key: str) -> None:
        self._pool = pool
        self._encryption_key = encryption_key

    def _encrypt_config(self, config: dict) -> bytes:
        """Serialize and encrypt a config dict."""
        return encrypt_api_key(json.dumps(config), self._encryption_key)

    def _decrypt_config(self, encrypted: bytes) -> dict:
        """Decrypt and deserialize a config dict."""
        return json.loads(decrypt_api_key(encrypted, self._encryption_key))

    async def upsert_integration(
        self,
        *,
        org_login: str,
        provider: str,
        display_name: str,
        config: dict,
        provider_metadata: dict | None = None,
        connected_by: int | None = None,
    ) -> dict:
        """Insert or update an org integration, encrypting config at rest."""
        encrypted_config = self._encrypt_config(config)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO org_integrations
                    (org_login, provider, display_name, encrypted_config,
                     provider_metadata, connected_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (org_login, provider)
                DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    encrypted_config = EXCLUDED.encrypted_config,
                    provider_metadata = EXCLUDED.provider_metadata,
                    connected_by = EXCLUDED.connected_by,
                    status = 'active',
                    updated_at = now()
                RETURNING id, org_login, provider, display_name, status,
                          provider_metadata, connected_by, connected_at, updated_at
                """,
                org_login,
                provider,
                display_name,
                encrypted_config,
                provider_metadata or {},
                connected_by,
            )
        return dict(row)

    async def get_integration(self, org_login: str, provider: str) -> dict | None:
        """Get an integration (without decrypted config)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, org_login, provider, display_name, status,
                       provider_metadata, connected_by, connected_at, updated_at
                FROM org_integrations
                WHERE org_login = $1 AND provider = $2
                """,
                org_login,
                provider,
            )
        return dict(row) if row else None

    async def get_integration_config(self, org_login: str, provider: str) -> dict | None:
        """Decrypt and return the full config for an integration."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT encrypted_config FROM org_integrations WHERE org_login = $1 AND provider = $2",
                org_login,
                provider,
            )
        if not row:
            return None
        return self._decrypt_config(row["encrypted_config"])

    async def get_integration_by_id(self, integration_id: str) -> dict | None:
        """Get an integration by its UUID (without decrypted config)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, org_login, provider, display_name, status,
                       provider_metadata, connected_by, connected_at, updated_at
                FROM org_integrations
                WHERE id = $1::uuid
                """,
                integration_id,
            )
        return dict(row) if row else None

    async def list_integrations(self, org_login: str) -> list[dict]:
        """List all integrations for an org (no decrypted configs)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, org_login, provider, display_name, status,
                       provider_metadata, connected_by, connected_at, updated_at
                FROM org_integrations
                WHERE org_login = $1
                ORDER BY connected_at DESC
                """,
                org_login,
            )
        return [dict(r) for r in rows]

    async def delete_integration(self, org_login: str, provider: str) -> bool:
        """Delete an integration. Returns True if a row was deleted."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM org_integrations WHERE org_login = $1 AND provider = $2",
                org_login,
                provider,
            )
        return result == "DELETE 1"

    async def update_status(
        self,
        org_login: str,
        provider: str,
        status: str,
        *,
        error: str | None = None,
    ) -> bool:
        """Update the status of an integration. Returns True if updated.

        When *error* is provided and status is ``error`` or ``needs_reauth``,
        the message is recorded in ``provider_metadata->>'error'`` so the
        admin dashboard can display it.  On recovery (status ``active``), any
        previous error is cleared.
        """
        if error and status in ("error", "needs_reauth"):
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE org_integrations
                    SET status = $3,
                        provider_metadata = jsonb_set(
                            COALESCE(provider_metadata, '{}'), '{error}', to_jsonb($4::text)
                        ),
                        updated_at = now()
                    WHERE org_login = $1 AND provider = $2
                    """,
                    org_login,
                    provider,
                    status,
                    error,
                )
        elif status == "active":
            # Clear any stale error on recovery
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE org_integrations
                    SET status = $3,
                        provider_metadata = provider_metadata - 'error',
                        updated_at = now()
                    WHERE org_login = $1 AND provider = $2
                    """,
                    org_login,
                    provider,
                    status,
                )
        else:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE org_integrations
                    SET status = $3, updated_at = now()
                    WHERE org_login = $1 AND provider = $2
                    """,
                    org_login,
                    provider,
                    status,
                )
        return result == "UPDATE 1"

    async def update_config(
        self,
        org_login: str,
        provider: str,
        *,
        config: dict,
        provider_metadata: dict | None = None,
    ) -> bool:
        """Update encrypted config (e.g. after token refresh). Returns True if updated."""
        encrypted_config = self._encrypt_config(config)
        if provider_metadata is not None:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE org_integrations
                    SET encrypted_config = $3, provider_metadata = $4, updated_at = now()
                    WHERE org_login = $1 AND provider = $2
                    """,
                    org_login,
                    provider,
                    encrypted_config,
                    provider_metadata,
                )
        else:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE org_integrations
                    SET encrypted_config = $3, updated_at = now()
                    WHERE org_login = $1 AND provider = $2
                    """,
                    org_login,
                    provider,
                    encrypted_config,
                )
        return result == "UPDATE 1"

    async def get_summary(self, org_login: str) -> dict:
        """Get integration status summary for the dashboard."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT provider, status FROM org_integrations WHERE org_login = $1",
                org_login,
            )
        integrations = [dict(r) for r in rows]
        total = len(integrations)
        active = sum(1 for i in integrations if i["status"] == "active")
        needs_attention = sum(1 for i in integrations if i["status"] in ("needs_reauth", "error"))
        return {
            "total": total,
            "connected": active,
            "needs_attention": needs_attention,
        }
