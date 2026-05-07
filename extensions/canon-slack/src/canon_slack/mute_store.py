"""Persistent per-user mute store backed by a JSON file."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data/slack_mutes.json")


class MuteStore:
    """File-backed store for per-user notification mutes.

    Data format: {"slack_user_id": ["spec-slug-1", "spec-slug-2"]}
    """

    def __init__(self, path: Path | str = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._data: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            self._data = {k: set(v) for k, v in raw.items()}
        except Exception:
            logger.warning("Could not load mute store from %s", self._path, exc_info=True)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serializable = {k: sorted(v) for k, v in self._data.items() if v}
            self._path.write_text(json.dumps(serializable, indent=2) + "\n")
        except Exception:
            logger.error("Could not save mute store to %s", self._path, exc_info=True)

    def mute(self, user_id: str, slug: str) -> None:
        """Mute a spec for a user."""
        if user_id not in self._data:
            self._data[user_id] = set()
        self._data[user_id].add(slug)
        self._save()

    def unmute(self, user_id: str, slug: str) -> None:
        """Unmute a spec for a user."""
        if user_id in self._data:
            self._data[user_id].discard(slug)
        self._save()

    def is_muted(self, user_id: str, slug: str) -> bool:
        """Check if a spec is muted for a user."""
        return slug in self._data.get(user_id, set())

    def get_muted(self, user_id: str) -> set[str]:
        """Return all muted spec slugs for a user."""
        return set(self._data.get(user_id, set()))
