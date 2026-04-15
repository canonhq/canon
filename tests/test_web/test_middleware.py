"""Tests for production hardening middleware."""

import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from canon.web.middleware import (
    CacheControlMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
)


def _make_app(middleware_cls, middleware_kwargs=None, routes=None):
    """Create a minimal Starlette app with the given middleware."""

    async def ok(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    if routes is None:
        routes = [Route("/{path:path}", ok)]
    app = Starlette(routes=routes)
    app.add_middleware(middleware_cls, **(middleware_kwargs or {}))
    return app


# --- CacheControlMiddleware ---


class TestCacheControlMiddleware:
    def test_hashed_assets_get_immutable_cache(self):
        client = TestClient(_make_app(CacheControlMiddleware))
        resp = client.get("/static/app/assets/index-abc123.js")
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"

    def test_static_files_get_1h_cache(self):
        client = TestClient(_make_app(CacheControlMiddleware))
        resp = client.get("/static/style.css")
        assert resp.headers["cache-control"] == "public, max-age=3600"

    def test_docs_get_1h_cache(self):
        client = TestClient(_make_app(CacheControlMiddleware))
        resp = client.get("/docs/getting-started")
        assert resp.headers["cache-control"] == "public, max-age=3600"

    def test_non_static_paths_have_no_cache_header(self):
        client = TestClient(_make_app(CacheControlMiddleware))
        resp = client.get("/app/org/dashboard")
        assert "cache-control" not in resp.headers


# --- RequestLoggingMiddleware ---


class TestRequestLoggingMiddleware:
    def test_logs_non_static_request(self, caplog):
        client = TestClient(_make_app(RequestLoggingMiddleware))
        with caplog.at_level("INFO", logger="canon.web.middleware"):
            client.get("/app/org/dashboard")
        assert any("http_request" in r.message for r in caplog.records)
        log_record = next(r for r in caplog.records if "http_request" in r.message)
        assert log_record.method == "GET"
        assert log_record.path == "/app/org/dashboard"
        assert log_record.status_code == 200

    def test_skips_healthz(self, caplog):
        client = TestClient(_make_app(RequestLoggingMiddleware))
        with caplog.at_level("INFO", logger="canon.web.middleware"):
            client.get("/healthz")
        assert not any("http_request" in r.message for r in caplog.records)

    def test_skips_static(self, caplog):
        client = TestClient(_make_app(RequestLoggingMiddleware))
        with caplog.at_level("INFO", logger="canon.web.middleware"):
            client.get("/static/style.css")
        assert not any("http_request" in r.message for r in caplog.records)


# --- RateLimitMiddleware ---


class TestRateLimitMiddleware:
    def test_allows_requests_under_limit(self):
        client = TestClient(
            _make_app(
                RateLimitMiddleware,
                {"path_prefix": "/api/search", "max_requests": 5, "window_seconds": 60},
            )
        )
        for _ in range(5):
            resp = client.get("/api/search")
            assert resp.status_code == 200

    def test_blocks_requests_over_limit(self):
        client = TestClient(
            _make_app(
                RateLimitMiddleware,
                {"path_prefix": "/api/search", "max_requests": 3, "window_seconds": 60},
            )
        )
        for _ in range(3):
            client.get("/api/search")
        resp = client.get("/api/search")
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "60"
        assert resp.json()["error"] == "Rate limit exceeded"

    def test_does_not_limit_other_paths(self):
        client = TestClient(
            _make_app(
                RateLimitMiddleware,
                {"path_prefix": "/api/search", "max_requests": 1, "window_seconds": 60},
            )
        )
        client.get("/api/search")  # exhaust limit
        resp = client.get("/app/dashboard")
        assert resp.status_code == 200

    def test_does_not_match_substring_paths(self):
        client = TestClient(
            _make_app(
                RateLimitMiddleware,
                {"path_prefix": "/api/search", "max_requests": 1, "window_seconds": 60},
            )
        )
        client.get("/api/search")  # exhaust limit
        # /api/search-results should NOT be rate-limited
        resp = client.get("/api/search-results")
        assert resp.status_code == 200

    def test_uses_last_xff_entry(self):
        """Last X-Forwarded-For entry (from trusted proxy) should be used."""
        app = _make_app(
            RateLimitMiddleware,
            {"path_prefix": "/api/search", "max_requests": 1, "window_seconds": 60},
        )
        client = TestClient(app)
        # Spoofed first entry, real last entry
        headers = {"x-forwarded-for": "1.2.3.4, 10.0.0.1"}
        client.get("/api/search", headers=headers)
        # Same spoofed first entry, different real last entry → fresh bucket
        headers2 = {"x-forwarded-for": "1.2.3.4, 10.0.0.2"}
        resp = client.get("/api/search", headers=headers2)
        assert resp.status_code == 200

    def test_expired_entries_are_cleaned(self, monkeypatch):
        app = _make_app(
            RateLimitMiddleware,
            {"path_prefix": "/api/search", "max_requests": 2, "window_seconds": 1},
        )
        client = TestClient(app)
        client.get("/api/search")
        client.get("/api/search")
        # Should be at limit
        resp = client.get("/api/search")
        assert resp.status_code == 429

        # Fast-forward time past the window
        real_monotonic = time.monotonic
        monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 2)
        resp = client.get("/api/search")
        assert resp.status_code == 200
