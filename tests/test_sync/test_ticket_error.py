"""Tests for canon.sync.ticket_error.classify_error."""

from __future__ import annotations

import httpx

from canon.sync.ticket_error import classify_error


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.com/x")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"{status_code}", request=request, response=response)


class TestClassifyError:
    def test_404_is_not_found(self):
        assert classify_error(_http_error(404)) == "not_found"

    def test_401_is_unauthorized(self):
        assert classify_error(_http_error(401)) == "unauthorized"

    def test_403_is_forbidden(self):
        assert classify_error(_http_error(403)) == "forbidden"

    def test_500_is_transient(self):
        assert classify_error(_http_error(500)) == "transient"

    def test_503_is_transient(self):
        assert classify_error(_http_error(503)) == "transient"

    def test_429_is_transient(self):
        # Rate-limited is recoverable on retry, not durable broken
        assert classify_error(_http_error(429)) == "transient"

    def test_timeout_is_transient(self):
        request = httpx.Request("GET", "https://example.com/x")
        assert classify_error(httpx.ReadTimeout("timed out", request=request)) == "transient"

    def test_generic_exception_is_transient(self):
        assert classify_error(RuntimeError("something else")) == "transient"

    def test_value_error_is_transient(self):
        # Programming bugs surface as transient — engine still appends
        # them to result.errors so they're not silently lost
        assert classify_error(ValueError("boom")) == "transient"
