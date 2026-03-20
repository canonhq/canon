"""Tests for the TTL cache."""

from __future__ import annotations

import time
from unittest.mock import patch

from canon.web.cache import TTLCache


class TestTTLCache:
    def test_set_and_get(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing_key(self):
        cache = TTLCache(ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = TTLCache(ttl_seconds=1)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Simulate time passing beyond TTL
        with patch("canon.web.cache.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 2
            assert cache.get("key1") is None

    def test_invalidate(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("key1", "value1")
        cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_invalidate_nonexistent(self):
        cache = TTLCache(ttl_seconds=60)
        cache.invalidate("nonexistent")  # should not raise

    def test_invalidate_prefix(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("spec:org/repo/a.md", "a")
        cache.set("spec:org/repo/b.md", "b")
        cache.set("spec:org/other/c.md", "c")
        cache.set("config:org/repo", "cfg")

        cache.invalidate_prefix("spec:org/repo/")

        assert cache.get("spec:org/repo/a.md") is None
        assert cache.get("spec:org/repo/b.md") is None
        assert cache.get("spec:org/other/c.md") == "c"
        assert cache.get("config:org/repo") == "cfg"

    def test_clear(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_overwrite_key(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("key1", "old")
        cache.set("key1", "new")
        assert cache.get("key1") == "new"
