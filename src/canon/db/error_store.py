"""Error fingerprint → GitHub issue mapping store."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class ErrorIssueMapping:
    """Maps an error fingerprint to a GitHub issue for deduplication."""

    id: int
    fingerprint: str
    repo: str
    issue_number: int
    issue_url: str = ""
    severity: str = "medium"
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    occurrence_count: int = 1
    resolved_at: datetime | None = None


class ErrorStore:
    """Data access layer for error_issue_map table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_by_fingerprint(self, fingerprint: str, repo: str) -> ErrorIssueMapping | None:
        """Get an error mapping by fingerprint and repo. Returns None if not found."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, fingerprint, repo, issue_number, issue_url,
                       severity, first_seen_at, last_seen_at, occurrence_count, resolved_at
                FROM error_issue_map
                WHERE fingerprint = $1 AND repo = $2
                """,
                fingerprint,
                repo,
            )
            if row is None:
                return None
            return ErrorIssueMapping(**dict(row))

    async def create(
        self,
        *,
        fingerprint: str,
        repo: str,
        issue_number: int,
        issue_url: str = "",
        severity: str = "medium",
    ) -> ErrorIssueMapping | None:
        """Create a new error mapping. Returns the created record, or None on conflict."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO error_issue_map
                    (fingerprint, repo, issue_number, issue_url, severity)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (fingerprint, repo) DO NOTHING
                RETURNING id
                """,
                fingerprint,
                repo,
                issue_number,
                issue_url,
                severity,
            )
            if row is None:
                return None
            return ErrorIssueMapping(
                id=row["id"],
                fingerprint=fingerprint,
                repo=repo,
                issue_number=issue_number,
                issue_url=issue_url,
                severity=severity,
            )

    async def increment_occurrence(self, fingerprint: str, repo: str) -> None:
        """Increment the occurrence count and update last_seen_at."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE error_issue_map
                SET occurrence_count = occurrence_count + 1,
                    last_seen_at = now()
                WHERE fingerprint = $1 AND repo = $2
                """,
                fingerprint,
                repo,
            )

    async def mark_resolved(self, fingerprint: str, repo: str) -> None:
        """Mark an error as resolved."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE error_issue_map
                SET resolved_at = now()
                WHERE fingerprint = $1 AND repo = $2
                """,
                fingerprint,
                repo,
            )

    async def clear_resolved(self, fingerprint: str, repo: str) -> None:
        """Clear the resolved flag (e.g., if the error re-occurs)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE error_issue_map
                SET resolved_at = NULL
                WHERE fingerprint = $1 AND repo = $2
                """,
                fingerprint,
                repo,
            )
