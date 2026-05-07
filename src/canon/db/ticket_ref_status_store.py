"""Data access for ticket_ref_status — durable broken-ref tracking.

A row is keyed by (installation_id, system, ticket_ref) and represents
the live broken/dismissed/ok state for a single ticket reference. The
canon-sync cron consults this store before calling each adapter and
updates it on success or classified failure.
"""

from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)

# Number of consecutive 404/401/403 responses before a ref is marked
# durably broken. Set in SQL, exposed here for tests + docs.
BROKEN_THRESHOLD = 3


class TicketRefStatusStore:
    """Async data access for ticket_ref_status."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, installation_id: int, system: str, ticket_ref: str) -> dict | None:
        """Fetch the row for a single ticket ref, or None if it has
        never failed."""
        row = await self._pool.fetchrow(
            """
            SELECT id, installation_id, system, ticket_ref, status,
                   consecutive_failures, last_error_kind, last_error_message,
                   first_failure_at, last_check_at, last_recheck_at,
                   dismissed_at, dismissed_by
            FROM ticket_ref_status
            WHERE installation_id = $1 AND system = $2 AND ticket_ref = $3
            """,
            installation_id,
            system,
            ticket_ref,
        )
        return dict(row) if row else None

    async def record_failure(
        self,
        *,
        installation_id: int,
        system: str,
        ticket_ref: str,
        error_kind: str,
        error_message: str,
    ) -> dict:
        """Record a classified failure (not_found / forbidden /
        unauthorized).

        Increments consecutive_failures atomically; once it reaches
        BROKEN_THRESHOLD the row's status flips to 'broken'. Idempotent
        on repeat calls (driven by INSERT ... ON CONFLICT). Returns the
        post-update row state.

        ``last_recheck_at`` is set to ``now()`` so a re-check that
        immediately re-fails counts as the latest re-check timestamp —
        otherwise we'd re-check the same ref every cycle until it
        finally succeeds.
        """
        row = await self._pool.fetchrow(
            """
            INSERT INTO ticket_ref_status (
                installation_id, system, ticket_ref,
                status, consecutive_failures,
                last_error_kind, last_error_message,
                first_failure_at, last_check_at, last_recheck_at
            )
            VALUES ($1, $2, $3,
                    'ok', 1,
                    $4, $5,
                    now(), now(),
                    CASE WHEN 1 >= $6 THEN now() ELSE NULL END)
            ON CONFLICT (installation_id, system, ticket_ref) DO UPDATE SET
                consecutive_failures = ticket_ref_status.consecutive_failures + 1,
                status = CASE
                    WHEN ticket_ref_status.status = 'dismissed'
                        THEN 'dismissed'
                    WHEN ticket_ref_status.consecutive_failures + 1 >= $6
                        THEN 'broken'
                    ELSE ticket_ref_status.status
                END,
                last_error_kind = EXCLUDED.last_error_kind,
                last_error_message = EXCLUDED.last_error_message,
                first_failure_at = COALESCE(ticket_ref_status.first_failure_at, now()),
                last_check_at = now(),
                last_recheck_at = CASE
                    WHEN ticket_ref_status.status = 'broken' THEN now()
                    ELSE ticket_ref_status.last_recheck_at
                END
            RETURNING status, consecutive_failures
            """,
            installation_id,
            system,
            ticket_ref,
            error_kind,
            error_message,
            BROKEN_THRESHOLD,
        )
        return dict(row) if row else {}

    async def mark_ok(self, *, installation_id: int, system: str, ticket_ref: str) -> None:
        """Clear a previously-broken ref back to 'ok'. Never touches
        dismissed rows."""
        await self._pool.execute(
            """
            INSERT INTO ticket_ref_status (
                installation_id, system, ticket_ref,
                status, consecutive_failures, last_check_at
            )
            VALUES ($1, $2, $3, 'ok', 0, now())
            ON CONFLICT (installation_id, system, ticket_ref) DO UPDATE SET
                status = 'ok',
                consecutive_failures = 0,
                last_error_kind = NULL,
                last_error_message = NULL,
                first_failure_at = NULL,
                last_recheck_at = NULL,
                last_check_at = now()
            WHERE ticket_ref_status.status <> 'dismissed'
            """,
            installation_id,
            system,
            ticket_ref,
        )

    async def dismiss(
        self,
        *,
        installation_id: int,
        system: str,
        ticket_ref: str,
        dismissed_by: str,
    ) -> None:
        """Operator-driven 'I know, leave it' state."""
        await self._pool.execute(
            """
            UPDATE ticket_ref_status
            SET status = 'dismissed',
                dismissed_at = now(),
                dismissed_by = $4
            WHERE installation_id = $1 AND system = $2 AND ticket_ref = $3
            """,
            installation_id,
            system,
            ticket_ref,
            dismissed_by,
        )

    async def force_recheck(self, *, installation_id: int, system: str, ticket_ref: str) -> None:
        """Clear last_recheck_at so the next cron cycle re-checks a
        broken ref immediately instead of waiting for the 24h window."""
        await self._pool.execute(
            """
            UPDATE ticket_ref_status
            SET last_recheck_at = NULL
            WHERE installation_id = $1 AND system = $2 AND ticket_ref = $3
            """,
            installation_id,
            system,
            ticket_ref,
        )

    async def list_broken(self, *, installation_id: int, status: str = "broken") -> list[dict]:
        """List rows for the given installation, defaulting to broken."""
        rows = await self._pool.fetch(
            """
            SELECT id, installation_id, system, ticket_ref, status,
                   consecutive_failures, last_error_kind, last_error_message,
                   first_failure_at, last_check_at, last_recheck_at,
                   dismissed_at, dismissed_by
            FROM ticket_ref_status
            WHERE installation_id = $1 AND status = $2
            ORDER BY first_failure_at DESC NULLS LAST
            """,
            installation_id,
            status,
        )
        return [dict(r) for r in rows]
