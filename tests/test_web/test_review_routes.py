"""Tests for PR review API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from canon.auth.models import CurrentUser
from canon.auth.permissions import Permission
from canon.web.review_routes import router


def _fake_user():
    """Create a minimal CurrentUser for auth bypass."""
    return CurrentUser(
        sub="test-user",
        email="test@example.com",
        name="Test User",
        picture="",
        org_login="test-org",
        permissions=frozenset({Permission.SPECS_READ}),
    )


@pytest.fixture(autouse=True)
def _bypass_auth():
    """Patch get_current_user so require_permission passes."""
    user = _fake_user()

    async def _fake(request):
        return user

    with patch("canon.auth.deps.get_current_user", _fake):
        yield


@pytest.fixture
def app():
    """Create a test FastAPI app with review routes."""
    app = FastAPI()
    app.include_router(router)

    # Default: no store available
    app.state.pr_review_store = None
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _make_review_row(
    id: int = 1,
    pr_number: int = 42,
    head_sha: str = "abc1234",
    **overrides,
) -> dict:
    defaults = {
        "id": id,
        "org": "test-org",
        "repo": "test-org/test-repo",
        "pr_number": pr_number,
        "pr_url": f"https://github.com/test-org/test-repo/pull/{pr_number}",
        "pr_title": "Test PR",
        "pr_author": "alice",
        "head_sha": head_sha,
        "base_ref": "main",
        "analysis": {
            "summary": "Test",
            "spec_references": [{"spec_file": "docs/specs/a.md"}],
            "discrepancies": [],
            "realizations": [
                {"status": "realized", "ac_text": "AC1"},
                {"status": "not_addressed", "ac_text": "AC2"},
            ],
        },
        "model": "claude-sonnet-4-6",
        "tokens_in": 1000,
        "tokens_out": 200,
        "cost_estimate": 0.006,
        "review_kind": "full",
        "created_at": datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return defaults


class TestListRepoReviews:
    def test_returns_empty_when_no_store(self, client):
        resp = client.get("/app/test-org/api/reviews/test-org/test-repo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reviews"] == []
        assert data["total"] == 0

    def test_returns_reviews_from_store(self, app, client):
        mock_store = AsyncMock()
        mock_store.list_reviews_for_repo.return_value = [
            _make_review_row(id=1, pr_number=42),
            _make_review_row(id=2, pr_number=43),
        ]
        mock_store.count_reviews_for_repo.return_value = 2
        app.state.pr_review_store = mock_store

        resp = client.get("/app/test-org/api/reviews/test-org/test-repo")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reviews"]) == 2
        assert data["total"] == 2

        # Verify summary counts are computed
        review = data["reviews"][0]
        assert review["spec_reference_count"] == 1
        assert review["realization_count"] == 2
        assert review["realized_count"] == 1

    def test_pagination_params_passed(self, app, client):
        mock_store = AsyncMock()
        mock_store.list_reviews_for_repo.return_value = []
        mock_store.count_reviews_for_repo.return_value = 0
        app.state.pr_review_store = mock_store

        client.get("/app/test-org/api/reviews/test-org/test-repo?limit=5&offset=10")
        mock_store.list_reviews_for_repo.assert_called_once_with(
            "test-org/test-repo", limit=5, offset=10
        )


class TestGetPRReview:
    def test_returns_empty_when_no_store(self, client):
        resp = client.get("/app/test-org/api/reviews/test-org/test-repo/42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["review"] is None
        assert data["history"] == []

    def test_returns_empty_when_no_review_found(self, app, client):
        mock_store = AsyncMock()
        mock_store.get_latest_review.return_value = None
        app.state.pr_review_store = mock_store

        resp = client.get("/app/test-org/api/reviews/test-org/test-repo/999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["review"] is None

    def test_returns_review_with_history(self, app, client):
        mock_store = AsyncMock()
        latest = _make_review_row(id=2, head_sha="sha2")
        history = [
            _make_review_row(id=2, head_sha="sha2"),
            _make_review_row(id=1, head_sha="sha1"),
        ]
        mock_store.get_latest_review.return_value = latest
        mock_store.list_reviews_for_pr.return_value = history
        app.state.pr_review_store = mock_store

        resp = client.get("/app/test-org/api/reviews/test-org/test-repo/42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["review"] is not None
        assert data["review"]["head_sha"] == "sha2"
        assert "analysis" in data["review"]
        assert len(data["history"]) == 2
