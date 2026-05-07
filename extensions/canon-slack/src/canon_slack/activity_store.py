"""Lightweight activity log for the Home Tab recent activity feed."""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data/slack_activity.json")
_MAX_PER_USER = 50


@dataclass
class ActivityEntry:
    """A single activity event."""

    timestamp: str
    text: str
    spec_slug: str = ""


class ActivityStore:
    """File-backed per-user activity log.

    Data format: {"slack_user_id": [{"timestamp": ..., "text": ..., "spec_slug": ...}]}
    """

    def __init__(self, path: Path | str = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._data: dict[str, deque[ActivityEntry]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            for uid, entries in raw.items():
                self._data[uid] = deque(
                    (ActivityEntry(**e) for e in entries),
                    maxlen=_MAX_PER_USER,
                )
        except Exception:
            logger.warning("Could not load activity store from %s", self._path, exc_info=True)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serializable = {k: [asdict(e) for e in v] for k, v in self._data.items() if v}
            self._path.write_text(json.dumps(serializable, indent=2) + "\n")
        except Exception:
            logger.error("Could not save activity store to %s", self._path, exc_info=True)

    def record(self, user_id: str, text: str, spec_slug: str = "") -> None:
        """Record an activity for a user."""
        if user_id not in self._data:
            self._data[user_id] = deque(maxlen=_MAX_PER_USER)
        entry = ActivityEntry(
            timestamp=datetime.now(UTC).isoformat(),
            text=text,
            spec_slug=spec_slug,
        )
        self._data[user_id].appendleft(entry)
        self._save()

    def recent(self, user_id: str, limit: int = 10) -> list[ActivityEntry]:
        """Return the most recent activity entries for a user."""
        entries = self._data.get(user_id, deque())
        return list(entries)[:limit]

    def record_for_all(
        self, text: str, spec_slug: str = "", user_ids: list[str] | None = None
    ) -> None:
        """Record an activity for multiple users (or broadcast if user_ids is None)."""
        if user_ids is None:
            user_ids = list(self._data.keys())
        for uid in user_ids:
            self.record(uid, text, spec_slug)
