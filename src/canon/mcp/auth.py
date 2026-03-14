"""Auth middleware for MCP HTTP endpoint.

Supports three modes (checked in order):
1. Canon API key (``sw_...``) — validated via UserStore hash lookup.
2. Legacy ``MCP_API_KEY`` — exact string match (backward compatible).
3. No key configured — open access (dev/STDIO mode).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class McpAuthMiddleware(BaseHTTPMiddleware):
    """API key check for the MCP HTTP endpoint."""

    def __init__(self, app, *, api_key: str | None = None, user_store=None) -> None:
        super().__init__(app)
        self._api_key = api_key
        self._user_store = user_store

    async def dispatch(self, request: Request, call_next):
        # No auth configured — open access
        if not self._api_key and self._user_store is None:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            # At least one auth mechanism is configured (checked above), so reject
            return JSONResponse({"error": "Invalid or missing MCP API key"}, status_code=401)

        token = auth[7:]

        # Canon API key (sw_ prefix) — validate via hash lookup
        if token.startswith("sw_") and self._user_store is not None:
            key_hash = hashlib.sha256(token.encode()).hexdigest()
            api_key = await self._user_store.get_api_key_by_hash(key_hash)
            if api_key is not None and api_key.get("revoked_at") is None:
                expires_at = api_key.get("expires_at")
                if expires_at is not None and expires_at < datetime.now(UTC):
                    return JSONResponse({"error": "API key has expired"}, status_code=401)
                return await call_next(request)
            return JSONResponse({"error": "Invalid or revoked API key"}, status_code=401)

        # Legacy MCP_API_KEY — constant-time comparison
        if self._api_key and hmac.compare_digest(token, self._api_key):
            return await call_next(request)

        return JSONResponse({"error": "Invalid or missing MCP API key"}, status_code=401)
