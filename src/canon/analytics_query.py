"""Read-only PostHog query client using HogQL."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)
_QUERY_TIMEOUT = 30.0


class PostHogQueryClient:
    """Query PostHog via HogQL API for analytics reads."""

    def __init__(self, api_key: str, project_id: str, host: str) -> None:
        self._api_key = api_key
        self._project_id = project_id
        self._host = host.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._project_id and self._host)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=_QUERY_TIMEOUT)
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def query(self, hogql: str) -> list[dict[str, Any]]:
        """Execute a HogQL query and return rows as dicts.

        Returns an empty list on timeout, HTTP error, or misconfiguration.
        Never raises — analytics reads must not break the application.
        The hogql parameter is embedded directly in the API payload;
        callers must sanitize any user-supplied values before interpolation.
        """
        if not self.configured:
            logger.debug("PostHog query skipped: client not configured")
            return []
        url = f"{self._host}/api/projects/{self._project_id}/query/"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload = {
            "query": {"kind": "HogQLQuery", "query": hogql},
        }
        try:
            resp = await self._get_client().post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            logger.warning(
                "PostHog query timed out (%.0fs)\nHogQL: %s", _QUERY_TIMEOUT, hogql[:200]
            )
            return []
        except httpx.HTTPError:
            logger.warning("PostHog query HTTP error\nHogQL: %s", hogql[:200], exc_info=True)
            return []
        except Exception:
            logger.warning("PostHog query unexpected error\nHogQL: %s", hogql[:200], exc_info=True)
            return []
        if resp.status_code != 200:
            logger.warning(
                "PostHog query %d: %s\nHogQL: %s",
                resp.status_code,
                resp.text[:500],
                hogql[:200],
            )
            return []
        try:
            data = resp.json()
        except (ValueError, UnicodeDecodeError):
            logger.warning("PostHog returned non-JSON response\nHogQL: %s", hogql[:200])
            return []
        columns = data.get("columns", [])
        results = data.get("results", [])
        return [dict(zip(columns, row, strict=False)) for row in results]
