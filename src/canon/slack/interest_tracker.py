"""Track user query patterns and suggest following frequently-queried specs."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data/slack_interests.json")
_FOLLOW_THRESHOLD = 3


class InterestTracker:
    """Tracks which specs users query and suggests following them.

    Data format: {"slack_user_id": {"spec-slug": query_count}}
    """

    def __init__(
        self, path: Path | str = _DEFAULT_PATH, threshold: int = _FOLLOW_THRESHOLD
    ) -> None:
        self._path = Path(path)
        self._threshold = threshold
        self._data: dict[str, Counter[str]] = {}
        self._suggested: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            for uid, counts in raw.get("counts", {}).items():
                self._data[uid] = Counter(counts)
            for uid, slugs in raw.get("suggested", {}).items():
                self._suggested[uid] = set(slugs)
        except Exception:
            logger.warning("Could not load interest tracker from %s", self._path, exc_info=True)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serializable = {
                "counts": {k: dict(v) for k, v in self._data.items()},
                "suggested": {k: sorted(v) for k, v in self._suggested.items()},
            }
            self._path.write_text(json.dumps(serializable, indent=2) + "\n")
        except Exception:
            logger.error("Could not save interest tracker to %s", self._path, exc_info=True)

    def record_query(self, user_id: str, spec_slug: str) -> str | None:
        """Record a query and return the spec slug if it crosses the follow threshold.

        Returns the slug if a follow suggestion should be shown (first time crossing
        threshold), None otherwise.
        """
        if user_id not in self._data:
            self._data[user_id] = Counter()
        self._data[user_id][spec_slug] += 1
        self._save()

        count = self._data[user_id][spec_slug]
        already_suggested = spec_slug in self._suggested.get(user_id, set())

        if count >= self._threshold and not already_suggested:
            if user_id not in self._suggested:
                self._suggested[user_id] = set()
            self._suggested[user_id].add(spec_slug)
            self._save()
            return spec_slug

        return None

    def get_interests(self, user_id: str, min_count: int = 1) -> list[tuple[str, int]]:
        """Return (slug, count) pairs sorted by count descending."""
        counter = self._data.get(user_id, Counter())
        return [(slug, count) for slug, count in counter.most_common() if count >= min_count]
