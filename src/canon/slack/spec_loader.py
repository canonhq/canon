"""Spec loader and cache for Slack command handlers."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from difflib import get_close_matches

logger = logging.getLogger(__name__)


@dataclass
class SectionInfo:
    """Summary of a spec section."""

    id: str
    title: str
    status: str
    acs_done: int
    acs_total: int


@dataclass
class SpecInfo:
    """Summary of a spec for Slack display."""

    title: str
    slug: str
    status: str
    sections_done: int
    sections_total: int
    github_url: str
    owner: str = ""
    team: str = ""
    updated: str = ""
    sections: list[SectionInfo] = field(default_factory=list)


class SpecLoader:
    """Loads and caches spec data for Slack command handlers."""

    # Cache TTL in seconds — ensures stale data self-expires across pods
    CACHE_TTL = 300  # 5 minutes

    def __init__(self, github_client: object, owner: str, repo: str) -> None:
        self._client = github_client
        self._owner = owner
        self._repo = repo
        self._cache: list[SpecInfo] = []
        self._cache_valid = False
        self._cache_time: float = 0.0
        self._load_error: str | None = None

    @property
    def has_load_error(self) -> bool:
        """True if the last load() call failed."""
        return self._load_error is not None

    @property
    def load_error(self) -> str | None:
        """Error message from the last failed load(), or None."""
        return self._load_error

    async def load(self) -> list[SpecInfo]:
        """Load all specs from the repo via the GitHub API.

        Returns cached results if still valid (within TTL). On failure,
        sets has_load_error and returns an empty list rather than raising.
        """
        if self._cache_valid and (time.monotonic() - self._cache_time) < self.CACHE_TTL:
            return self._cache

        self._load_error = None

        try:
            from canon.github.spec_utils import load_repo_specs

            raw_specs = await load_repo_specs(self._client, self._owner, self._repo)
            specs = []
            for entry in raw_specs:
                file_path = entry["file_path"]
                doc = entry["document"]
                slug = file_path.rsplit("/", 1)[-1].removesuffix(".md")
                github_url = f"https://github.com/{self._owner}/{self._repo}/blob/main/{file_path}"
                sections_done = sum(1 for s in doc.sections if s.status.state == "done")
                sections = [
                    SectionInfo(
                        id=s.id or "",
                        title=s.title,
                        status=s.status.state,
                        acs_done=sum(1 for ac in s.acceptance_criteria if ac.checked),
                        acs_total=len(s.acceptance_criteria),
                    )
                    for s in doc.sections
                ]
                specs.append(
                    SpecInfo(
                        title=doc.frontmatter.title or slug,
                        slug=slug,
                        status=doc.frontmatter.status or "draft",
                        sections_done=sections_done,
                        sections_total=len(doc.sections),
                        github_url=github_url,
                        owner=doc.frontmatter.owner or "",
                        team=doc.frontmatter.team or "",
                        updated=doc.frontmatter.updated or "",
                        sections=sections,
                    )
                )
            self._cache = specs
            self._cache_valid = True
            self._cache_time = time.monotonic()
        except Exception as exc:
            self._load_error = f"{type(exc).__name__}: {exc}"
            logger.error("Failed to load specs for %s/%s", self._owner, self._repo, exc_info=True)
            self._cache = []

        return self._cache

    @property
    def specs(self) -> list[SpecInfo]:
        """Return all cached specs."""
        return list(self._cache)

    def invalidate(self) -> None:
        """Clear the cache, forcing a reload on next access."""
        self._cache_valid = False

    def filter_by_status(self, status: str) -> list[SpecInfo]:
        """Filter cached specs by status."""
        return [s for s in self._cache if s.status == status]

    def search(self, query: str) -> list[SpecInfo]:
        """Search cached specs by keyword in title or slug."""
        q = query.lower()
        return [s for s in self._cache if q in s.title.lower() or q in s.slug.lower()]

    def get_by_slug(self, slug: str) -> SpecInfo | None:
        """Find a spec by its slug."""
        for s in self._cache:
            if s.slug == slug:
                return s
        return None

    def suggest_similar(self, query: str, n: int = 3) -> list[str]:
        """Suggest similar spec names via fuzzy matching."""
        slugs = [s.slug for s in self._cache]
        return get_close_matches(query, slugs, n=n, cutoff=0.4)

    def coverage_stats(self, team: str = "") -> dict:
        """Compute coverage statistics, optionally filtered by team."""
        specs = self._cache
        if team:
            specs = [s for s in specs if s.team == team]
        total = len(specs)
        done = sum(1 for s in specs if s.status in ("done", "approved"))
        in_progress = sum(1 for s in specs if s.status in ("in_progress", "active"))
        return {
            "total": total,
            "done": done,
            "in_progress": in_progress,
            "pct_done": round(done / total * 100) if total else 0,
            "pct_in_progress": round(in_progress / total * 100) if total else 0,
            "teams": sorted({s.team for s in self._cache if s.team}),
        }
