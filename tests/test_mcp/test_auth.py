"""Unit tests for canon.mcp.auth — McpAuthMiddleware."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from canon.mcp.auth import McpAuthMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_endpoint(request: Request):
    """Trivial endpoint that returns 200."""
    return PlainTextResponse("ok")


def _build_app(*, api_key: str | None = None, user_store=None) -> Starlette:
    """Build a minimal Starlette app wrapped with McpAuthMiddleware."""
    app = Starlette(routes=[Route("/", _ok_endpoint)])
    app.add_middleware(McpAuthMiddleware, api_key=api_key, user_store=user_store)
    return app


def _sha256(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tests — open access (no auth configured)
# ---------------------------------------------------------------------------


class TestOpenAccess:
    """When neither api_key nor user_store is configured, all requests pass."""

    def test_no_auth_configured_allows_request(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.text == "ok"

    def test_no_auth_configured_ignores_bearer(self):
        """Even if a bearer token is sent, open mode does not reject."""
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/", headers={"Authorization": "Bearer anything"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests — missing / malformed Authorization header
# ---------------------------------------------------------------------------


class TestMissingAuth:
    """When auth is configured but request lacks a valid Bearer header."""

    def test_no_header_with_api_key_configured(self):
        app = _build_app(api_key="secret")
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 401

    def test_no_header_with_user_store_configured(self):
        app = _build_app(user_store=AsyncMock())
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 401

    def test_non_bearer_auth_rejected(self):
        app = _build_app(api_key="secret")
        client = TestClient(app)
        resp = client.get("/", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401

    def test_empty_authorization_header(self):
        app = _build_app(api_key="secret")
        client = TestClient(app)
        resp = client.get("/", headers={"Authorization": ""})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests — legacy MCP_API_KEY (constant-time comparison)
# ---------------------------------------------------------------------------


class TestLegacyApiKey:
    """Legacy exact-match api_key validation."""

    def test_correct_legacy_key_passes(self):
        app = _build_app(api_key="my-legacy-key")
        client = TestClient(app)
        resp = client.get("/", headers={"Authorization": "Bearer my-legacy-key"})
        assert resp.status_code == 200

    def test_wrong_legacy_key_rejected(self):
        app = _build_app(api_key="my-legacy-key")
        client = TestClient(app)
        resp = client.get("/", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401

    def test_legacy_key_error_message(self):
        app = _build_app(api_key="my-legacy-key")
        client = TestClient(app)
        resp = client.get("/", headers={"Authorization": "Bearer wrong-key"})
        assert "Invalid or missing MCP API key" in resp.json()["error"]


# ---------------------------------------------------------------------------
# Tests — Canon sw_ API key (hash-based lookup via user_store)
# ---------------------------------------------------------------------------


class TestCanonSwKey:
    """sw_-prefixed keys validated via user_store hash lookup."""

    def test_valid_sw_key_passes(self):
        key = "sw_testabc123"
        store = AsyncMock()
        store.get_api_key_by_hash = AsyncMock(
            return_value={
                "revoked_at": None,
                "expires_at": None,
            }
        )
        app = _build_app(user_store=store)
        client = TestClient(app)

        resp = client.get("/", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 200
        # Verify the store was called with the SHA-256 hash
        store.get_api_key_by_hash.assert_awaited_once_with(_sha256(key))

    def test_valid_sw_key_with_future_expiry_passes(self):
        key = "sw_notexpired"
        store = AsyncMock()
        store.get_api_key_by_hash = AsyncMock(
            return_value={
                "revoked_at": None,
                "expires_at": datetime.now(UTC) + timedelta(days=30),
            }
        )
        app = _build_app(user_store=store)
        client = TestClient(app)

        resp = client.get("/", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 200

    def test_expired_sw_key_rejected(self):
        key = "sw_expired"
        store = AsyncMock()
        store.get_api_key_by_hash = AsyncMock(
            return_value={
                "revoked_at": None,
                "expires_at": datetime.now(UTC) - timedelta(hours=1),
            }
        )
        app = _build_app(user_store=store)
        client = TestClient(app)

        resp = client.get("/", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 401
        assert "expired" in resp.json()["error"]

    def test_revoked_sw_key_rejected(self):
        key = "sw_revoked"
        store = AsyncMock()
        store.get_api_key_by_hash = AsyncMock(
            return_value={
                "revoked_at": datetime.now(UTC) - timedelta(days=1),
                "expires_at": None,
            }
        )
        app = _build_app(user_store=store)
        client = TestClient(app)

        resp = client.get("/", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 401
        assert "revoked" in resp.json()["error"].lower() or "Invalid" in resp.json()["error"]

    def test_unknown_sw_key_rejected(self):
        """Hash lookup returns None — key not found."""
        key = "sw_unknown"
        store = AsyncMock()
        store.get_api_key_by_hash = AsyncMock(return_value=None)
        app = _build_app(user_store=store)
        client = TestClient(app)

        resp = client.get("/", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 401

    def test_sw_key_without_user_store_falls_to_legacy(self):
        """If user_store is None, sw_ prefix token falls through to legacy check."""
        key = "sw_something"
        # api_key matches the token exactly — should pass via legacy path
        app = _build_app(api_key=key)
        client = TestClient(app)

        resp = client.get("/", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 200

    def test_sw_key_without_user_store_wrong_legacy_rejected(self):
        """sw_ token with no user_store and wrong legacy key is rejected."""
        app = _build_app(api_key="different-key")
        client = TestClient(app)

        resp = client.get("/", headers={"Authorization": "Bearer sw_nope"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests — combined auth (both user_store and api_key configured)
# ---------------------------------------------------------------------------


class TestCombinedAuth:
    """When both user_store and legacy api_key are configured."""

    def test_legacy_key_works_alongside_user_store(self):
        """Non-sw_ token should fall through to legacy comparison."""
        store = AsyncMock()
        app = _build_app(api_key="legacy-secret", user_store=store)
        client = TestClient(app)

        resp = client.get("/", headers={"Authorization": "Bearer legacy-secret"})
        assert resp.status_code == 200
        # user_store should NOT have been called for non-sw_ token
        store.get_api_key_by_hash.assert_not_awaited()

    def test_sw_key_checked_before_legacy(self):
        """sw_ tokens go through user_store even if legacy key is set."""
        key = "sw_test"
        store = AsyncMock()
        store.get_api_key_by_hash = AsyncMock(
            return_value={
                "revoked_at": None,
                "expires_at": None,
            }
        )
        app = _build_app(api_key="legacy-secret", user_store=store)
        client = TestClient(app)

        resp = client.get("/", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 200
        store.get_api_key_by_hash.assert_awaited_once()
