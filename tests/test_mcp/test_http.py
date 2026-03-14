"""Integration test verifying MCP endpoint responds via HTTP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from canon.mcp.auth import McpAuthMiddleware
from canon.mcp.deps import McpDeps
from canon.mcp.server import create_mcp_server


@pytest.fixture
def mcp_app():
    """Create a minimal FastAPI app with MCP mounted at /mcp."""
    deps = McpDeps(
        search_index=None,
        embed_client=MagicMock(is_available=False),
        github_client=AsyncMock(),
    )
    mcp_server = create_mcp_server(deps)
    mcp_http_app = mcp_server.streamable_http_app()

    test_app = FastAPI()
    test_app.mount("/mcp", mcp_http_app)
    return test_app


@pytest.fixture
def client(mcp_app):
    return AsyncClient(
        transport=ASGITransport(app=mcp_app),
        base_url="http://test",
    )


class TestMcpEndpoint:
    async def test_mcp_endpoint_not_404(self, client: AsyncClient):
        """Verify /mcp is mounted and responds (not a 404)."""
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
            headers={"Content-Type": "application/json"},
        )
        # The MCP endpoint should respond — NOT 404
        assert resp.status_code != 404

    async def test_mcp_get_returns_method_not_allowed_or_ok(self, client: AsyncClient):
        """MCP endpoint handles GET requests (used for SSE)."""
        resp = await client.get("/mcp")
        # Should not be 404; will be 405 (method not allowed) or some valid response
        assert resp.status_code != 404


class TestMcpAuthMiddleware:
    """Tests for the MCP auth middleware (sw_ key validation)."""

    def _make_authed_app(self, *, user_store=None, api_key=None):
        """Create a minimal FastAPI app with MCP + auth middleware."""
        deps = McpDeps(
            search_index=None,
            embed_client=MagicMock(is_available=False),
            github_client=AsyncMock(),
        )
        mcp_server = create_mcp_server(deps)
        mcp_http_app = mcp_server.streamable_http_app()
        mcp_http_app.add_middleware(
            McpAuthMiddleware,
            api_key=api_key,
            user_store=user_store,
        )
        test_app = FastAPI()
        test_app.mount("/mcp", mcp_http_app)
        return test_app

    async def test_expired_sw_key_rejected(self):
        """An expired sw_ API key should be rejected with 401."""
        key = "sw_expiredtestkey"
        mock_user_store = AsyncMock()
        mock_user_store.get_api_key_by_hash = AsyncMock(
            return_value={
                "revoked_at": None,
                "expires_at": datetime.now(UTC) - timedelta(days=1),
                "org_login": "test-org",
                "scopes": ["specs:read"],
            }
        )

        test_app = self._make_authed_app(user_store=mock_user_store)
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/mcp/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
            )
        assert resp.status_code == 401
        assert "expired" in resp.json()["error"]

    async def test_valid_sw_key_accepted(self):
        """A valid, non-expired sw_ API key should pass through."""
        key = "sw_validtestkey"
        mock_user_store = AsyncMock()
        mock_user_store.get_api_key_by_hash = AsyncMock(
            return_value={
                "revoked_at": None,
                "expires_at": datetime.now(UTC) + timedelta(days=30),
                "org_login": "test-org",
                "scopes": ["specs:read"],
            }
        )

        test_app = self._make_authed_app(user_store=mock_user_store)
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/mcp/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
            )
        # Should not be 401 — the key is valid
        assert resp.status_code != 401

    async def test_revoked_sw_key_rejected(self):
        """A revoked sw_ API key should be rejected."""
        key = "sw_revokedtestkey"
        mock_user_store = AsyncMock()
        mock_user_store.get_api_key_by_hash = AsyncMock(
            return_value={
                "revoked_at": datetime.now(UTC),
                "expires_at": None,
                "org_login": "test-org",
                "scopes": ["specs:read"],
            }
        )

        test_app = self._make_authed_app(user_store=mock_user_store)
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/mcp/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
            )
        assert resp.status_code == 401

    async def test_no_auth_with_store_configured_rejects(self):
        """When user_store is set, requests without Bearer are rejected."""
        mock_user_store = AsyncMock()
        test_app = self._make_authed_app(user_store=mock_user_store, api_key="legacy-key")
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/mcp/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 401
