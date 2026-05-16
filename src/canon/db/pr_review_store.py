"""Data access layer for PR review persistence."""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class PRReviewStore:
    """CRUD for the pr_reviews table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── Write ────────────────────────────────────────────────

    async def upsert_review(
        self,
        *,
        org: str,
        repo: str,
        pr_number: int,
        pr_url: str,
        pr_title: str,
        pr_author: str,
        head_sha: str,
        base_ref: str,
        analysis: dict[str, Any],
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_estimate: float = 0,
        review_kind: str = "full",
    ) -> int:
        """Insert or update a PR review. Returns the review ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO pr_reviews
                    (org, repo, pr_number, pr_url, pr_title, pr_author,
                     head_sha, base_ref, analysis, model,
                     tokens_in, tokens_out, cost_estimate, review_kind)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10,
                        $11, $12, $13, $14)
                ON CONFLICT (repo, pr_number, head_sha)
                DO UPDATE SET
                    analysis = EXCLUDED.analysis,
                    model = EXCLUDED.model,
                    tokens_in = EXCLUDED.tokens_in,
                    tokens_out = EXCLUDED.tokens_out,
                    cost_estimate = EXCLUDED.cost_estimate,
                    review_kind = EXCLUDED.review_kind,
                    pr_title = EXCLUDED.pr_title,
                    created_at = now()
                RETURNING id
                """,
                org,
                repo,
                pr_number,
                pr_url,
                pr_title,
                pr_author,
                head_sha,
                base_ref,
                json.dumps(analysis),
                model,
                tokens_in,
                tokens_out,
                cost_estimate,
                review_kind,
            )
        return row["id"]

    # ── Read (single) ────────────────────────────────────────

    async def get_latest_review(self, repo: str, pr_number: int) -> dict | None:
        """Get the most recent review for a PR."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM pr_reviews
                WHERE repo = $1 AND pr_number = $2
                ORDER BY created_at DESC
                LIMIT 1
                """,
                repo,
                pr_number,
            )
        return dict(row) if row else None

    async def get_review_by_sha(self, repo: str, pr_number: int, head_sha: str) -> dict | None:
        """Get a specific review by commit SHA."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM pr_reviews
                WHERE repo = $1 AND pr_number = $2 AND head_sha = $3
                """,
                repo,
                pr_number,
                head_sha,
            )
        return dict(row) if row else None

    async def get_review_by_id(self, review_id: int) -> dict | None:
        """Get a review by primary key."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM pr_reviews WHERE id = $1",
                review_id,
            )
        return dict(row) if row else None

    # ── Read (list) ──────────────────────────────────────────

    async def list_reviews_for_pr(self, repo: str, pr_number: int) -> list[dict]:
        """All reviews for a PR, newest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM pr_reviews
                WHERE repo = $1 AND pr_number = $2
                ORDER BY created_at DESC
                """,
                repo,
                pr_number,
            )
        return [dict(r) for r in rows]

    async def list_reviews_for_repo(
        self,
        repo: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """Paginated list of latest review per PR for a repo."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM (
                    SELECT DISTINCT ON (pr_number) *
                    FROM pr_reviews
                    WHERE repo = $1
                    ORDER BY pr_number, created_at DESC
                ) sub
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                repo,
                limit,
                offset,
            )
        return [dict(r) for r in rows]

    async def list_reviews_for_org(
        self,
        org: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """Paginated list of latest review per PR across an org, newest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM (
                    SELECT DISTINCT ON (repo, pr_number) *
                    FROM pr_reviews
                    WHERE org = $1
                    ORDER BY repo, pr_number, created_at DESC
                ) sub
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                org,
                limit,
                offset,
            )
        return [dict(r) for r in rows]

    async def count_reviews_for_repo(self, repo: str) -> int:
        """Count distinct PRs with reviews for a repo."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(DISTINCT pr_number) AS cnt
                FROM pr_reviews
                WHERE repo = $1
                """,
                repo,
            )
        return row["cnt"] if row else 0

    async def count_reviews_for_org(self, org: str) -> int:
        """Count distinct PRs with reviews for an org."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS cnt FROM (
                    SELECT DISTINCT repo, pr_number
                    FROM pr_reviews
                    WHERE org = $1
                ) sub
                """,
                org,
            )
        return row["cnt"] if row else 0
