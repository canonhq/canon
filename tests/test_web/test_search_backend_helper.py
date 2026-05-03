"""Tests for the _get_search_backend helper in web/routes.py.

The helper drives the Phase 2 read-path cutover: it picks app.state.search_backend
when wired, and falls back to the raw SearchIndex otherwise. A regression here
silently degrades every read route, so the contract gets its own test.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from canon.web.routes import _get_search_backend


def _request_with(state: dict) -> MagicMock:
    request = MagicMock()
    request.app.state = SimpleNamespace(**state)
    return request


def test_returns_search_backend_when_set():
    backend = MagicMock(name="backend")
    index = MagicMock(name="index")
    request = _request_with({"search_backend": backend, "search_index": index})
    assert _get_search_backend(request) is backend


def test_falls_back_to_search_index_when_backend_none():
    index = MagicMock(name="index")
    request = _request_with({"search_backend": None, "search_index": index})
    assert _get_search_backend(request) is index


def test_returns_none_when_neither_set():
    request = _request_with({"search_backend": None, "search_index": None})
    assert _get_search_backend(request) is None


def test_handles_missing_attributes():
    """Without either attribute on app.state, return None — don't raise."""
    request = MagicMock()
    request.app.state = SimpleNamespace()
    assert _get_search_backend(request) is None
