"""Session evidence store — backs the plugin → GitHub App evidence pipeline.

Stores `SessionRecord` payloads recorded by the canon plugin via the
`record_session_evidence` MCP tool. The PR analyzer queries this table at
PR-open time as hint input.

See: docs/specs/plugin-evidence-pipeline.md §6.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionEvidenceRow:
    """One row from the session_evidence table."""

    id: int
    repo: str
    branch: str
    session_id: str
    schema_version: int
    payload: dict[str, Any]
    recorded_at: datetime


class SessionEvidenceStore:
    """Data access layer for session_evidence."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def insert(
        self,
        *,
        repo: str,
        branch: str,
        session_id: str,
        payload: dict[str, Any],
        schema_version: int = 1,
    ) -> int | None:
        """Insert a new session evidence record. Returns id, or None on conflict.

        ON CONFLICT (repo, session_id) DO NOTHING — duplicate ingestion is
        silently ignored so plugin retries are safe.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO session_evidence
                    (repo, branch, session_id, schema_version, payload)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                ON CONFLICT (repo, session_id) DO NOTHING
                RETURNING id
                """,
                repo,
                branch,
                session_id,
                schema_version,
                json.dumps(payload),
            )
            return row["id"] if row else None

    async def list_for_branch(
        self,
        repo: str,
        branch: str,
        *,
        limit: int = 20,
    ) -> list[SessionEvidenceRow]:
        """Fetch session records for a (repo, branch), most recent first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, repo, branch, session_id, schema_version, payload, recorded_at
                FROM session_evidence
                WHERE repo = $1 AND branch = $2
                ORDER BY recorded_at DESC
                LIMIT $3
                """,
                repo,
                branch,
                limit,
            )
            return [
                SessionEvidenceRow(
                    id=row["id"],
                    repo=row["repo"],
                    branch=row["branch"],
                    session_id=row["session_id"],
                    schema_version=row["schema_version"],
                    payload=json.loads(row["payload"])
                    if isinstance(row["payload"], str)
                    else row["payload"],
                    recorded_at=row["recorded_at"],
                )
                for row in rows
            ]

    async def count_in_window(self, repo: str, *, since: datetime) -> int:
        """Count records inserted at or after `since`. Used for rate limiting."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS n
                FROM session_evidence
                WHERE repo = $1 AND recorded_at >= $2
                """,
                repo,
                since,
            )
            return int(row["n"]) if row else 0
