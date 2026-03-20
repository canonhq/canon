"""Data access layer for agent events, realization evidence, and sync state."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """A logged agent action."""

    id: int = 0
    repo: str = ""
    event_type: str = ""
    pr_number: int | None = None
    issue_number: int | None = None
    actor: str = ""
    detail: dict = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass
class RealizationRecord:
    """Evidence that a PR realizes (or conflicts with) an acceptance criterion."""

    id: int = 0
    repo: str = ""
    spec_path: str = ""
    section_id: str = ""
    ac_text: str = ""
    status: str = "not_addressed"
    pr_number: int = 0
    pr_url: str = ""
    evidence_files: list[dict] = field(default_factory=list)
    assessed_at: datetime | None = None


@dataclass
class SyncStateRecord:
    """Last sync state for a spec section / ticket pair."""

    id: int = 0
    repo: str = ""
    spec_path: str = ""
    section_id: str = ""
    ticket_id: str = ""
    last_synced_at: datetime | None = None
    last_status: str = ""


@dataclass
class CoverageSnapshot:
    """A point-in-time coverage snapshot for a single spec."""

    id: int = 0
    snapshot_date: date | None = None
    org: str = ""
    repo: str = ""
    team: str = ""
    spec_path: str = ""
    total_sections: int = 0
    done_sections: int = 0
    total_ac: int = 0
    done_ac: int = 0
    realized_ac: int = 0
    created_at: datetime | None = None


class AgentStore:
    """Data access layer for agent_events, realization_evidence, and sync_state."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ─── Agent Events ─────────────────────────────────

    async def log_event(
        self,
        repo: str,
        event_type: str,
        *,
        pr_number: int | None = None,
        issue_number: int | None = None,
        actor: str = "",
        detail: dict | None = None,
    ) -> AgentEvent:
        """Log an agent event. Returns the created record."""
        detail_json = json.dumps(detail or {})
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO agent_events (repo, event_type, pr_number, issue_number, actor, detail)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                RETURNING *
                """,
                repo,
                event_type,
                pr_number,
                issue_number,
                actor,
                detail_json,
            )
        return _row_to_event(row)

    async def get_events(
        self,
        repo: str,
        *,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[AgentEvent]:
        """Get recent events, optionally filtered by type."""
        if event_type:
            sql = "SELECT * FROM agent_events WHERE repo = $1 AND event_type = $2 ORDER BY id DESC LIMIT $3"
            args: tuple = (repo, event_type, limit)
        else:
            sql = "SELECT * FROM agent_events WHERE repo = $1 ORDER BY id DESC LIMIT $2"
            args = (repo, limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [_row_to_event(r) for r in rows]

    # ─── Realization Evidence ─────────────────────────

    async def upsert_realization(
        self,
        repo: str,
        spec_path: str,
        section_id: str,
        ac_text: str,
        *,
        status: str,
        pr_number: int,
        pr_url: str = "",
        evidence_files: list[dict] | None = None,
    ) -> RealizationRecord:
        """Insert or update realization evidence for an AC."""
        files_json = json.dumps(evidence_files or [])
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO realization_evidence
                    (repo, spec_path, section_id, ac_text, status, pr_number, pr_url, evidence_files)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                ON CONFLICT (repo, spec_path, section_id, ac_text, pr_number)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    pr_url = EXCLUDED.pr_url,
                    evidence_files = EXCLUDED.evidence_files,
                    assessed_at = now()
                RETURNING *
                """,
                repo,
                spec_path,
                section_id,
                ac_text,
                status,
                pr_number,
                pr_url,
                files_json,
            )
        return _row_to_realization(row)

    async def get_realizations(
        self,
        repo: str,
        spec_path: str,
        *,
        section_id: str | None = None,
    ) -> list[RealizationRecord]:
        """Get realization evidence for a spec, optionally filtered by section."""
        if section_id:
            sql = """
                SELECT * FROM realization_evidence
                WHERE repo = $1 AND spec_path = $2 AND section_id = $3
                ORDER BY assessed_at DESC
            """
            args: tuple = (repo, spec_path, section_id)
        else:
            sql = """
                SELECT * FROM realization_evidence
                WHERE repo = $1 AND spec_path = $2
                ORDER BY assessed_at DESC
            """
            args = (repo, spec_path)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [_row_to_realization(r) for r in rows]

    async def get_realization_summary(
        self,
        repo: str,
        spec_path: str,
    ) -> dict[str, int]:
        """Get aggregate realization counts by status for a spec."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT status, COUNT(*) AS cnt
                FROM realization_evidence
                WHERE repo = $1 AND spec_path = $2
                GROUP BY status
                """,
                repo,
                spec_path,
            )
        return {row["status"]: row["cnt"] for row in rows}

    # ─── Sync State ───────────────────────────────────

    async def upsert_sync_state(
        self,
        repo: str,
        spec_path: str,
        section_id: str,
        ticket_id: str,
        *,
        status: str = "",
    ) -> SyncStateRecord:
        """Insert or update sync state for a spec section / ticket pair."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sync_state (repo, spec_path, section_id, ticket_id, last_status)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (repo, spec_path, section_id, ticket_id)
                DO UPDATE SET
                    last_synced_at = now(),
                    last_status = EXCLUDED.last_status
                RETURNING *
                """,
                repo,
                spec_path,
                section_id,
                ticket_id,
                status,
            )
        return _row_to_sync_state(row)

    async def get_sync_state(
        self,
        repo: str,
        spec_path: str,
    ) -> list[SyncStateRecord]:
        """Get sync state records for a spec."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM sync_state
                WHERE repo = $1 AND spec_path = $2
                ORDER BY section_id, ticket_id
                """,
                repo,
                spec_path,
            )
        return [_row_to_sync_state(r) for r in rows]

    # ─── Coverage Snapshots ────────────────────────────

    async def upsert_coverage_snapshot(
        self,
        snapshot_date: date,
        org: str,
        repo: str,
        spec_path: str,
        *,
        team: str = "",
        total_sections: int = 0,
        done_sections: int = 0,
        total_ac: int = 0,
        done_ac: int = 0,
        realized_ac: int = 0,
    ) -> CoverageSnapshot:
        """Insert or update a daily coverage snapshot for a spec."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO coverage_snapshots
                    (snapshot_date, org, repo, spec_path, team,
                     total_sections, done_sections, total_ac, done_ac, realized_ac)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (snapshot_date, org, repo, spec_path)
                DO UPDATE SET
                    team = EXCLUDED.team,
                    total_sections = EXCLUDED.total_sections,
                    done_sections = EXCLUDED.done_sections,
                    total_ac = EXCLUDED.total_ac,
                    done_ac = EXCLUDED.done_ac,
                    realized_ac = EXCLUDED.realized_ac
                RETURNING *
                """,
                snapshot_date,
                org,
                repo,
                spec_path,
                team,
                total_sections,
                done_sections,
                total_ac,
                done_ac,
                realized_ac,
            )
        return _row_to_coverage_snapshot(row)

    async def get_coverage_summary(
        self,
        org: str,
        *,
        repo: str | None = None,
        team: str | None = None,
    ) -> dict[str, int]:
        """Aggregate coverage from the most recent snapshot date.

        Returns dict with keys: total_specs, total_sections, done_sections,
        total_ac, done_ac, realized_ac.
        """
        # Build dynamic WHERE clause
        conditions = ["org = $1"]
        args: list = [org]
        idx = 2

        if repo:
            conditions.append(f"repo = ${idx}")
            args.append(repo)
            idx += 1
        if team:
            conditions.append(f"team = ${idx}")
            args.append(team)
            idx += 1

        where = " AND ".join(conditions)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT
                    COUNT(*)::int AS total_specs,
                    COALESCE(SUM(total_sections), 0)::int AS total_sections,
                    COALESCE(SUM(done_sections), 0)::int AS done_sections,
                    COALESCE(SUM(total_ac), 0)::int AS total_ac,
                    COALESCE(SUM(done_ac), 0)::int AS done_ac,
                    COALESCE(SUM(realized_ac), 0)::int AS realized_ac
                FROM coverage_snapshots
                WHERE {where}
                    AND snapshot_date = (
                        SELECT MAX(snapshot_date) FROM coverage_snapshots WHERE {where}
                    )
                """,
                *args,
            )
        if not row:
            return {
                "total_specs": 0,
                "total_sections": 0,
                "done_sections": 0,
                "total_ac": 0,
                "done_ac": 0,
                "realized_ac": 0,
            }
        return dict(row)

    async def get_coverage_trend(
        self,
        org: str,
        *,
        repo: str | None = None,
        team: str | None = None,
        days: int = 30,
    ) -> list[dict]:
        """Get coverage time-series aggregated by day.

        Returns list of dicts with: date, total_sections, done_sections,
        total_ac, done_ac, realized_ac.
        """
        conditions = ["org = $1", f"snapshot_date >= CURRENT_DATE - ${2}::int"]
        args: list = [org, days]
        idx = 3

        if repo:
            conditions.append(f"repo = ${idx}")
            args.append(repo)
            idx += 1
        if team:
            conditions.append(f"team = ${idx}")
            args.append(team)
            idx += 1

        where = " AND ".join(conditions)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    snapshot_date,
                    COALESCE(SUM(total_sections), 0)::int AS total_sections,
                    COALESCE(SUM(done_sections), 0)::int AS done_sections,
                    COALESCE(SUM(total_ac), 0)::int AS total_ac,
                    COALESCE(SUM(done_ac), 0)::int AS done_ac,
                    COALESCE(SUM(realized_ac), 0)::int AS realized_ac
                FROM coverage_snapshots
                WHERE {where}
                GROUP BY snapshot_date
                ORDER BY snapshot_date
                """,
                *args,
            )
        return [
            {
                "date": str(r["snapshot_date"]),
                "total_sections": r["total_sections"],
                "done_sections": r["done_sections"],
                "total_ac": r["total_ac"],
                "done_ac": r["done_ac"],
                "realized_ac": r["realized_ac"],
            }
            for r in rows
        ]


# ─── Row Mappers ────────────────────────────────────────


def _row_to_event(row: asyncpg.Record) -> AgentEvent:
    detail = row["detail"]
    if isinstance(detail, str):
        detail = json.loads(detail)
    return AgentEvent(
        id=row["id"],
        repo=row["repo"],
        event_type=row["event_type"],
        pr_number=row["pr_number"],
        issue_number=row["issue_number"],
        actor=row["actor"],
        detail=detail if isinstance(detail, dict) else {},
        created_at=row["created_at"],
    )


def _row_to_realization(row: asyncpg.Record) -> RealizationRecord:
    files = row["evidence_files"]
    if isinstance(files, str):
        files = json.loads(files)
    return RealizationRecord(
        id=row["id"],
        repo=row["repo"],
        spec_path=row["spec_path"],
        section_id=row["section_id"],
        ac_text=row["ac_text"],
        status=row["status"],
        pr_number=row["pr_number"],
        pr_url=row["pr_url"],
        evidence_files=files if isinstance(files, list) else [],
        assessed_at=row["assessed_at"],
    )


def _row_to_sync_state(row: asyncpg.Record) -> SyncStateRecord:
    return SyncStateRecord(
        id=row["id"],
        repo=row["repo"],
        spec_path=row["spec_path"],
        section_id=row["section_id"],
        ticket_id=row["ticket_id"],
        last_synced_at=row["last_synced_at"],
        last_status=row["last_status"],
    )


def _row_to_coverage_snapshot(row: asyncpg.Record) -> CoverageSnapshot:
    return CoverageSnapshot(
        id=row["id"],
        snapshot_date=row["snapshot_date"],
        org=row["org"],
        repo=row["repo"],
        team=row["team"],
        spec_path=row["spec_path"],
        total_sections=row["total_sections"],
        done_sections=row["done_sections"],
        total_ac=row["total_ac"],
        done_ac=row["done_ac"],
        realized_ac=row["realized_ac"],
        created_at=row["created_at"],
    )
