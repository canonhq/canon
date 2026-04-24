"""Data access layer for sync run history and events."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class SyncHistoryStore:
    """CRUD for the sync_runs and sync_events tables."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── Sync runs ────────────────────────────────────────────

    async def create_run(
        self,
        *,
        org_login: str,
        repo: str,
        spec_path: str | None = None,
        system: str,
        direction: str,
        trigger: str = "manual",
        triggered_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a new sync run record. Returns the run ID (UUID string)."""
        run_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sync_runs
                    (id, org_login, repo, spec_path, system, direction,
                     trigger, triggered_by, metadata)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                """,
                run_id,
                org_login,
                repo,
                spec_path,
                system,
                direction,
                trigger,
                triggered_by,
                _json_str(metadata),
            )
        return run_id

    async def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        created_count: int = 0,
        updated_count: int = 0,
        closed_count: int = 0,
        reopened_count: int = 0,
        skipped_count: int = 0,
        error_count: int = 0,
    ) -> bool:
        """Mark a run as completed with final counts. Returns True if updated."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE sync_runs
                SET status = $2, ended_at = now(),
                    created_count = $3, updated_count = $4,
                    closed_count = $5, reopened_count = $6,
                    skipped_count = $7, error_count = $8
                WHERE id = $1::uuid
                """,
                run_id,
                status,
                created_count,
                updated_count,
                closed_count,
                reopened_count,
                skipped_count,
                error_count,
            )
        return result == "UPDATE 1"

    async def get_run(self, run_id: str) -> dict | None:
        """Get a single sync run by ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sync_runs WHERE id = $1::uuid",
                run_id,
            )
        return dict(row) if row else None

    async def list_runs(
        self,
        org_login: str,
        *,
        repo: str | None = None,
        system: str | None = None,
        direction: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: datetime | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List sync runs with filtering and cursor-based pagination."""
        conditions = ["org_login = $1"]
        params: list[Any] = [org_login]
        idx = 2

        if repo:
            conditions.append(f"repo = ${idx}")
            params.append(repo)
            idx += 1
        if system:
            conditions.append(f"system = ${idx}")
            params.append(system)
            idx += 1
        if direction:
            conditions.append(f"direction = ${idx}")
            params.append(direction)
            idx += 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if since:
            conditions.append(f"started_at >= ${idx}")
            params.append(since)
            idx += 1
        if until:
            conditions.append(f"started_at <= ${idx}")
            params.append(until)
            idx += 1
        if cursor:
            conditions.append(f"started_at < ${idx}")
            params.append(cursor)
            idx += 1

        params.append(limit)
        where = " AND ".join(conditions)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM sync_runs
                WHERE {where}
                ORDER BY started_at DESC
                LIMIT ${idx}
                """,
                *params,
            )
        return [dict(r) for r in rows]

    # ── Sync events ──────────────────────────────────────────

    async def add_event(
        self,
        run_id: str,
        *,
        event_type: str,
        section_title: str | None = None,
        section_number: str | None = None,
        ticket_id: str | None = None,
        ticket_url: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> str:
        """Add a single sync event. Returns the event ID."""
        event_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sync_events
                    (id, run_id, event_type, section_title, section_number,
                     ticket_id, ticket_url, detail)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::jsonb)
                """,
                event_id,
                run_id,
                event_type,
                section_title,
                section_number,
                ticket_id,
                ticket_url,
                _json_str(detail),
            )
        return event_id

    async def add_events_batch(
        self,
        run_id: str,
        events: list[dict[str, Any]],
    ) -> int:
        """Batch-insert sync events. Returns the number of events inserted."""
        if not events:
            return 0
        async with self._pool.acquire() as conn:
            rows = [
                (
                    str(uuid.uuid4()),
                    run_id,
                    ev.get("event_type", ""),
                    ev.get("section_title"),
                    ev.get("section_number"),
                    ev.get("ticket_id"),
                    ev.get("ticket_url"),
                    _json_str(ev.get("detail")),
                )
                for ev in events
            ]
            await conn.executemany(
                """
                INSERT INTO sync_events
                    (id, run_id, event_type, section_title, section_number,
                     ticket_id, ticket_url, detail)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::jsonb)
                """,
                rows,
            )
        return len(rows)

    async def get_run_events(
        self,
        run_id: str,
        *,
        event_type: str | None = None,
    ) -> list[dict]:
        """Get all events for a sync run, optionally filtered by type."""
        if event_type:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM sync_events
                    WHERE run_id = $1::uuid AND event_type = $2
                    ORDER BY created_at
                    """,
                    run_id,
                    event_type,
                )
        else:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM sync_events
                    WHERE run_id = $1::uuid
                    ORDER BY created_at
                    """,
                    run_id,
                )
        return [dict(r) for r in rows]

    # ── Aggregation ──────────────────────────────────────────

    async def get_stats(self, org_login: str) -> dict:
        """Get aggregate sync stats for an org dashboard."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS total_runs,
                    COALESCE(SUM(created_count), 0) AS total_created,
                    COALESCE(SUM(updated_count), 0) AS total_updated,
                    COALESCE(SUM(closed_count), 0) AS total_closed,
                    COALESCE(SUM(error_count), 0) AS total_errors,
                    COUNT(DISTINCT repo) AS synced_repos,
                    COUNT(DISTINCT spec_path) FILTER (WHERE spec_path IS NOT NULL) AS synced_specs
                FROM sync_runs
                WHERE org_login = $1
                """,
                org_login,
            )
            # Active errors: runs that ended with errors in the last 7 days
            active_errors_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS active_errors
                FROM sync_runs
                WHERE org_login = $1
                  AND error_count > 0
                  AND started_at > now() - interval '7 days'
                """,
                org_login,
            )
        stats = dict(row) if row else {}
        stats["active_errors"] = active_errors_row["active_errors"] if active_errors_row else 0
        return stats

    async def get_spec_sync_status(
        self,
        org_login: str,
        owner: str,
        repo_name: str,
        spec_path: str,
    ) -> dict:
        """Get sync status for a specific spec file."""
        full_repo = f"{owner}/{repo_name}"
        async with self._pool.acquire() as conn:
            # Most recent run for this spec
            last_run = await conn.fetchrow(
                """
                SELECT * FROM sync_runs
                WHERE org_login = $1 AND repo = $2 AND spec_path = $3
                ORDER BY started_at DESC
                LIMIT 1
                """,
                org_login,
                full_repo,
                spec_path,
            )
            # Error count in last 7 days
            error_row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(error_count), 0) AS recent_errors
                FROM sync_runs
                WHERE org_login = $1 AND repo = $2 AND spec_path = $3
                  AND started_at > now() - interval '7 days'
                """,
                org_login,
                full_repo,
                spec_path,
            )
        return {
            "last_run": dict(last_run) if last_run else None,
            "recent_errors": error_row["recent_errors"] if error_row else 0,
        }

    # ── Cleanup ──────────────────────────────────────────────

    async def cleanup_old_runs(self, retention_days: int = 90) -> int:
        """Delete sync runs older than retention period. Returns deleted count."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM sync_runs
                WHERE started_at < now() - ($1 || ' days')::interval
                """,
                str(retention_days),
            )
        # result is like "DELETE 42"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0


def _json_str(data: dict | None) -> str:
    """Convert a dict to a JSON string for JSONB columns."""
    import json

    return json.dumps(data or {})
