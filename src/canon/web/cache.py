"""In-memory TTL cache with per-key expiration."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Entry:
    value: Any
    expires_at: float


@dataclass
class TTLCache:
    """Simple in-memory cache with per-key TTL expiration."""

    ttl_seconds: int = 300
    _store: dict[str, _Entry] = field(default_factory=dict)

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            return None
        return entry.value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = _Entry(
            value=value,
            expires_at=time.monotonic() + self.ttl_seconds,
        )

    def set_with_ttl(self, key: str, value: Any, ttl: int) -> None:
        """Set a value with a specific TTL, without mutating shared ttl_seconds."""
        self._store[key] = _Entry(value=value, expires_at=time.monotonic() + ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        """Remove all keys starting with a prefix."""
        to_remove = [k for k in self._store if k.startswith(prefix)]
        for k in to_remove:
            del self._store[k]

    def clear(self) -> None:
        self._store.clear()
