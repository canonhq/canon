"""Synchronous HTTP client for CLI ↔ Canon platform communication."""

from __future__ import annotations

import os
import time

import httpx

from ._credentials import is_token_expired, load_credentials, save_credentials

_DEFAULT_URL = "https://canonhq.co"


class AuthRequiredError(Exception):
    """Raised when no valid credentials are available."""


class PlatformClient:
    """Thin wrapper around ``httpx.Client`` that injects auth headers.

    Token refresh is attempted pre-emptively (if expired) and reactively
    (on 401 response).
    """

    def __init__(self, base_url: str | None = None) -> None:
        if base_url is None:
            base_url = os.environ.get("CANON_URL")
            if base_url is None:
                legacy = os.environ.get("SPECWRIGHT_URL")
                if legacy:
                    import logging

                    logging.getLogger(__name__).warning(
                        "SPECWRIGHT_URL is deprecated, use CANON_URL instead"
                    )
                    base_url = legacy
        self.base_url = base_url or _DEFAULT_URL
        self._http = httpx.Client(base_url=self.base_url, timeout=30)

    # ── public helpers ──────────────────────────────────

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        cred = load_credentials()
        if cred is None:
            raise AuthRequiredError("Not logged in. Run `canon login` first.")

        # Pre-emptive refresh if token is expired
        if cred.get("method") == "oauth" and is_token_expired(cred):
            cred = self._refresh(cred)

        headers = kwargs.pop("headers", {})
        headers.update(self._auth_header(cred))
        resp = self._http.request(method, path, headers=headers, **kwargs)

        # Reactive refresh on 401 or 307 redirect to login
        is_auth_failure = resp.status_code == 401 or (
            resp.status_code == 307 and "/auth/login" in resp.headers.get("location", "")
        )
        if is_auth_failure and cred.get("method") == "oauth":
            cred = self._refresh(cred)
            headers.update(self._auth_header(cred))
            resp = self._http.request(method, path, headers=headers, **kwargs)

        return resp

    def raw_get(self, path: str, **kwargs) -> httpx.Response:
        """Send a GET request without auth injection."""
        return self._http.get(path, **kwargs)

    def raw_post(self, path: str, **kwargs) -> httpx.Response:
        """Send a POST request without auth injection."""
        return self._http.post(path, **kwargs)

    def close(self) -> None:
        self._http.close()

    # ── internals ───────────────────────────────────────

    @staticmethod
    def _auth_header(cred: dict) -> dict[str, str]:
        if cred.get("method") == "api_key":
            return {"Authorization": f"Bearer {cred['api_key']}"}
        return {"Authorization": f"Bearer {cred.get('access_token', '')}"}

    def _refresh(self, cred: dict) -> dict:
        """Call the platform refresh endpoint and update saved credentials."""
        refresh_token = cred.get("refresh_token", "")
        if not refresh_token:
            raise AuthRequiredError("No refresh token. Run `canon login` again.")

        resp = self._http.post(
            "/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        if resp.status_code != 200:
            raise AuthRequiredError("Token refresh failed. Run `canon login` again.")

        data = resp.json()
        cred["access_token"] = data["access_token"]
        cred["expires_at"] = time.time() + data.get("expires_in", 86400)
        if "refresh_token" in data:
            cred["refresh_token"] = data["refresh_token"]
        save_credentials(cred)
        return cred
