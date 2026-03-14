"""Integration tests for health check endpoints.

These tests exercise /healthz and /readyz through the full FastAPI pipeline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from canon.main import app

pytestmark = pytest.mark.integration


class TestHealthz:
    """Liveness probe must always return 200."""

    async def test_healthz_returns_ok(self, app_client):
        resp = await app_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestReadyz:
    """Readiness probe checks DB health when pool is configured."""

    async def test_readyz_ok_without_db_pool(self, app_client):
        """When no DB pool is configured, readyz should return 200."""
        resp = await app_client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_readyz_ok_with_healthy_pool(self, app_client):
        """When the DB pool is healthy, readyz should return 200."""
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        # Inject the mock pool into app state
        app.state.db_pool = mock_pool
        try:
            resp = await app_client.get("/readyz")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
        finally:
            app.state.db_pool = None

    async def test_readyz_503_with_unhealthy_pool(self, app_client):
        """When the DB pool raises, readyz should return 503."""
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(side_effect=RuntimeError("connection lost"))

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        app.state.db_pool = mock_pool
        try:
            resp = await app_client.get("/readyz")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "error"
            assert "database unhealthy" in data["detail"]
        finally:
            app.state.db_pool = None
