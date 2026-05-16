"""Tests for PRReviewStore — CRUD operations against the pr_reviews table.

These tests use a real asyncpg connection to a Postgres instance when
DATABASE_URL is set, otherwise they are skipped.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set — skipping DB tests",
    ),
]


@pytest.fixture
async def store():
    """Create a PRReviewStore connected to a test database."""
    from canon.db.pool import create_pool
    from canon.db.pr_review_store import PRReviewStore

    dsn = os.environ["DATABASE_URL"]
    # Use the project's pool factory so the JSONB codec is registered —
    # otherwise asyncpg returns `analysis` as a raw string and the tests
    # pass for the wrong reason (production hits the dict path).
    pool = await create_pool(dsn, min_size=1, max_size=2)

    # Ensure the table exists (run migration or create manually)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pr_reviews (
                id              SERIAL PRIMARY KEY,
                org             TEXT NOT NULL,
                repo            TEXT NOT NULL,
                pr_number       INTEGER NOT NULL,
                pr_url          TEXT NOT NULL,
                pr_title        TEXT NOT NULL,
                pr_author       TEXT NOT NULL,
                head_sha        TEXT NOT NULL,
                base_ref        TEXT NOT NULL,
                analysis        JSONB NOT NULL DEFAULT '{}'::jsonb,
                model           TEXT NOT NULL DEFAULT '',
                tokens_in       INTEGER NOT NULL DEFAULT 0,
                tokens_out      INTEGER NOT NULL DEFAULT 0,
                cost_estimate   NUMERIC(10,6) DEFAULT 0,
                review_kind     TEXT NOT NULL DEFAULT 'full',
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (repo, pr_number, head_sha)
            )
        """)

    s = PRReviewStore(pool)
    yield s

    # Cleanup
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM pr_reviews WHERE org = 'test-org'")
    await pool.close()


_REVIEW_DEFAULTS = {
    "org": "test-org",
    "repo": "test-org/test-repo",
    "pr_number": 42,
    "pr_url": "https://github.com/test-org/test-repo/pull/42",
    "pr_title": "Add feature X",
    "pr_author": "alice",
    "head_sha": "abc1234",
    "base_ref": "main",
    "analysis": {"summary": "Test analysis", "spec_references": [], "discrepancies": []},
    "model": "claude-sonnet-4-6",
    "tokens_in": 1000,
    "tokens_out": 200,
    "cost_estimate": 0.0048,
}


class TestUpsertReview:
    async def test_creates_review(self, store):
        review_id = await store.upsert_review(**_REVIEW_DEFAULTS)
        assert isinstance(review_id, int)
        assert review_id > 0

    async def test_upsert_on_conflict_updates(self, store):
        id1 = await store.upsert_review(**_REVIEW_DEFAULTS)
        updated = {**_REVIEW_DEFAULTS, "pr_title": "Updated title", "tokens_in": 2000}
        id2 = await store.upsert_review(**updated)
        assert id1 == id2

        review = await store.get_review_by_id(id1)
        assert review["pr_title"] == "Updated title"
        assert review["tokens_in"] == 2000

    async def test_different_sha_creates_new_row(self, store):
        id1 = await store.upsert_review(**_REVIEW_DEFAULTS)
        id2 = await store.upsert_review(**{**_REVIEW_DEFAULTS, "head_sha": "def5678"})
        assert id1 != id2


class TestGetLatestReview:
    async def test_returns_most_recent(self, store):
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "head_sha": "sha_old"})
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "head_sha": "sha_new"})
        latest = await store.get_latest_review("test-org/test-repo", 42)
        assert latest is not None
        assert latest["head_sha"] == "sha_new"

    async def test_returns_none_when_no_reviews(self, store):
        result = await store.get_latest_review("test-org/no-repo", 999)
        assert result is None

    async def test_analysis_round_trips_as_dict(self, store):
        # Regression: pre-codec, asyncpg returned `analysis` as a raw JSON
        # string and every API consumer crashed on `analysis.get(...)`.
        await store.upsert_review(**_REVIEW_DEFAULTS)
        latest = await store.get_latest_review("test-org/test-repo", 42)
        assert isinstance(latest["analysis"], dict)
        assert latest["analysis"]["summary"] == "Test analysis"


class TestGetReviewBySha:
    async def test_returns_specific_review(self, store):
        await store.upsert_review(**_REVIEW_DEFAULTS)
        review = await store.get_review_by_sha("test-org/test-repo", 42, "abc1234")
        assert review is not None
        assert review["head_sha"] == "abc1234"

    async def test_returns_none_for_unknown_sha(self, store):
        await store.upsert_review(**_REVIEW_DEFAULTS)
        review = await store.get_review_by_sha("test-org/test-repo", 42, "unknown")
        assert review is None


class TestListReviewsForPr:
    async def test_returns_all_reviews_newest_first(self, store):
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "head_sha": "sha1"})
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "head_sha": "sha2"})
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "head_sha": "sha3"})
        reviews = await store.list_reviews_for_pr("test-org/test-repo", 42)
        assert len(reviews) == 3
        # Newest first
        assert reviews[0]["head_sha"] == "sha3"


class TestListReviewsForRepo:
    async def test_returns_latest_per_pr(self, store):
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "pr_number": 1, "head_sha": "s1"})
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "pr_number": 1, "head_sha": "s2"})
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "pr_number": 2, "head_sha": "s3"})
        reviews = await store.list_reviews_for_repo("test-org/test-repo")
        assert len(reviews) == 2

    async def test_pagination(self, store):
        for i in range(5):
            await store.upsert_review(
                **{**_REVIEW_DEFAULTS, "pr_number": 100 + i, "head_sha": f"psha{i}"}
            )
        page1 = await store.list_reviews_for_repo("test-org/test-repo", limit=2, offset=0)
        page2 = await store.list_reviews_for_repo("test-org/test-repo", limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2


class TestCountReviewsForRepo:
    async def test_counts_distinct_prs(self, store):
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "pr_number": 10, "head_sha": "c1"})
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "pr_number": 10, "head_sha": "c2"})
        await store.upsert_review(**{**_REVIEW_DEFAULTS, "pr_number": 11, "head_sha": "c3"})
        count = await store.count_reviews_for_repo("test-org/test-repo")
        assert count == 2
