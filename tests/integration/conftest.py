"""Shared fixtures for integration tests."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport

from canon.main import app
from canon.settings import Settings

TEST_WEBHOOK_SECRET = "test-webhook-secret-for-integration"


@pytest.fixture
def webhook_secret() -> str:
    return TEST_WEBHOOK_SECRET


def sign_payload(payload: bytes, secret: str) -> str:
    """Compute a real HMAC-SHA256 signature matching GitHub's format."""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def webhook_headers(event: str, signature: str, delivery: str | None = None) -> dict[str, str]:
    """Build realistic GitHub webhook headers."""
    return {
        "x-github-event": event,
        "x-hub-signature-256": signature,
        "x-github-delivery": delivery or uuid.uuid4().hex,
        "content-type": "application/json",
    }


def make_payload(event: str, **overrides: Any) -> dict:
    """Build a minimal valid webhook payload for the given event type."""
    base: dict[str, Any] = {
        "repository": {"full_name": "test-org/test-repo"},
        "installation": {"id": 12345},
    }

    if event == "push":
        base.update({"ref": "refs/heads/main", "commits": []})
    elif event == "pull_request":
        base.update(
            {
                "action": overrides.pop("action", "opened"),
                "pull_request": {
                    "number": 42,
                    "head": {"sha": "abc123", "ref": "feature"},
                    "base": {"ref": "main"},
                    "merged": overrides.pop("merged", False),
                },
            }
        )
    elif event == "issue_comment":
        base.update(
            {
                "action": overrides.pop("action", "created"),
                "issue": {"number": 10, "pull_request": {"url": "..."}},
                "comment": {"body": "test comment", "user": {"login": "tester"}},
            }
        )
    elif event == "issues":
        base.update(
            {
                "action": overrides.pop("action", "opened"),
                "issue": {"number": 5, "title": "test issue"},
            }
        )
    elif event == "installation":
        base.update({"action": overrides.pop("action", "created")})
    elif event == "installation_repositories":
        base.update(
            {
                "action": overrides.pop("action", "added"),
                "repositories_added": [],
            }
        )

    base.update(overrides)
    return base


@pytest.fixture
def mock_github_client() -> MagicMock:
    """A mock GitHubClient that supports for_installation."""
    client = MagicMock()
    client.installation_id = "99999"
    child = MagicMock()
    child.installation_id = "12345"
    client.for_installation.return_value = child
    return client


@pytest.fixture
async def app_client(mock_github_client: MagicMock) -> httpx.AsyncClient:
    """httpx.AsyncClient wired to the FastAPI app with test settings.

    Patches:
    - canon.main.settings with a test Settings instance
    - canon.main._get_client to return a mock GitHubClient
    - canon.main.analytics to no-op
    """
    test_settings = Settings(
        gh_webhook_secret=TEST_WEBHOOK_SECRET,
        gh_app_id="test-app-id",
        gh_private_key="test-key",
        gh_installation_id="99999",
    )

    # Set app.state attributes that middleware and handlers expect
    # (normally set during lifespan, which doesn't run in transport-only tests)
    state_attrs = (
        "settings",
        "db_pool",
        "registry",
        "user_store",
        "session_store",
        "agent_store",
        "github_client",
    )
    originals = {attr: getattr(app.state, attr, None) for attr in state_attrs}

    app.state.settings = test_settings
    app.state.db_pool = None
    app.state.registry = None
    app.state.user_store = None
    app.state.session_store = None
    app.state.agent_store = None
    app.state.github_client = mock_github_client

    with (
        patch("canon.main.settings", test_settings),
        patch("canon.main._get_client", return_value=mock_github_client),
        patch("canon.main.analytics"),
    ):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    # Restore original app.state to avoid leaking between test modules
    for attr, value in originals.items():
        setattr(app.state, attr, value)
