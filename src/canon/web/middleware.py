"""Production hardening middleware for the web app."""

from __future__ import annotations

import json
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from canon import analytics

logger = logging.getLogger(__name__)


class CacheControlMiddleware(BaseHTTPMiddleware):
    """Set Cache-Control headers on static asset responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        path = request.url.path

        if path.startswith("/static/"):
            # Hashed assets (Vite build output) get long cache
            if "/assets/" in path:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "public, max-age=3600"
        elif path.startswith("/docs/"):
            response.headers["Cache-Control"] = "public, max-age=3600"

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured JSON logging for web requests."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)

        path = request.url.path

        # Skip health checks and static assets from both logging and analytics
        if path in ("/healthz", "/readyz") or path.startswith("/static/"):
            return response

        logger.info(
            "http_request",
            extra={
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "user_agent": request.headers.get("user-agent", ""),
            },
        )
        analytics.track(
            "request_completed",
            properties={
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "user_agent": request.headers.get("user-agent", ""),
            },
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding-window rate limiter for the search endpoint.

    Limits each authenticated user (or IP for unauthenticated) to
    ``max_requests`` per ``window_seconds`` on matching paths.
    """

    def __init__(
        self,
        app: object,
        *,
        path_prefix: str = "/api/search",
        max_requests: int = 60,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.path_prefix = path_prefix
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def _client_key(self, request: Request) -> str:
        try:
            session = request.session
        except AssertionError:
            session = None
        if session:
            user = session.get("user")
            if user and user.get("sub"):
                return f"user:{user['sub']}"
        # Use the last X-Forwarded-For entry (appended by the trusted proxy)
        # rather than the first (client-controlled and spoofable).
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return f"ip:{forwarded.split(',')[-1].strip()}"
        client = request.client
        return f"ip:{client.host}" if client else "ip:unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.endswith(self.path_prefix):
            return await call_next(request)

        now = time.monotonic()
        key = self._client_key(request)
        window_start = now - self.window_seconds

        # Trim expired entries and clean up empty keys
        hits = [t for t in self._hits.get(key, []) if t > window_start]
        if not hits:
            self._hits.pop(key, None)
        else:
            self._hits[key] = hits

        if len(hits) >= self.max_requests:
            # Log key type (user/ip) but not the value to avoid credential exposure
            key_type = key.split(":")[0] if ":" in key else "unknown"
            analytics.track(
                "rate_limit_hit",
                properties={
                    "path": request.url.path,
                    "client_type": key_type,
                    "limit": self.max_requests,
                    "window": self.window_seconds,
                },
            )
            return Response(
                content=json.dumps(
                    {"error": "Rate limit exceeded", "retry_after": self.window_seconds}
                ),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(self.window_seconds)},
            )

        hits.append(now)
        self._hits[key] = hits
        return await call_next(request)
