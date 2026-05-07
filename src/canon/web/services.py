"""High-level data access for the Spec Explorer web app."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass

from ..config.parse import CanonConfig, parse_canon_yaml
from ..github.client import FileChange, GitHubClient
from ..github.spec_utils import load_repo_specs
from ..parser.classify import classify_doc_type
from ..parser.models import SpecDocument, SpecSection, flatten_sections
from .cache import TTLCache
from .models import (
    BrokenRef,
    CoverageApiResponse,
    CoverageSummary,
    CoverageTrendPoint,
    DocDetail,
    DocFile,
    FacetCounts,
    OrgOverview,
    RepoSummary,
    SpecDetail,
    SpecSearchResult,
    SpecSummary,
    TaskItem,
    TasksApiResponse,
)
from .render import render_markdown_html, render_spec_html

logger = logging.getLogger(__name__)

# Request coalescing: prevent thundering-herd when cache expires and
# multiple requests hit get_org_overview simultaneously.
_inflight: dict[str, asyncio.Task] = {}

# Longer TTL for data that changes infrequently.
_REPO_LIST_TTL = 900  # 15 min — repos rarely added/removed
_ORG_OVERVIEW_TTL = 600  # 10 min — spec content changes occasionally

_VALID_ERROR_KINDS: frozenset[str] = frozenset({"not_found", "forbidden", "unauthorized"})


def _coerce_error_kind(raw: object) -> str:
    """Coerce a raw DB error_kind into the BrokenRef.Literal set.

    Defensively handles legacy or unexpected values (e.g. if the
    classifier expands and we deploy the read path before the model
    update lands) by falling back to 'not_found'. Prevents a single
    bad row from 500-ing the whole list endpoint.
    """
    if isinstance(raw, str) and raw in _VALID_ERROR_KINDS:
        return raw
    return "not_found"


def _section_heading(section: SpecSection) -> str:
    """Build a display heading for a section, matching the search UI format."""
    if section.section_number:
        return f"{section.section_number}. {section.title}"
    return section.title


def _summarize_spec(doc: SpecDocument) -> SpecSummary:
    """Build a SpecSummary from a parsed SpecDocument."""

    def _count_sections(sections: list) -> tuple[int, int]:
        total = 0
        done = 0
        for s in sections:
            total += 1
            if s.status.state == "done":
                done += 1
            ct, cd = _count_sections(s.children)
            total += ct
            done += cd
        return total, done

    def _count_ac(sections: list) -> tuple[int, int]:
        total = 0
        done = 0
        for s in sections:
            total += len(s.acceptance_criteria)
            done += sum(1 for ac in s.acceptance_criteria if ac.checked)
            ct, cd = _count_ac(s.children)
            total += ct
            done += cd
        return total, done

    total_sections, done_sections = _count_sections(doc.sections)
    total_ac, done_ac = _count_ac(doc.sections)

    return SpecSummary(
        file_path=doc.file_path,
        title=doc.frontmatter.title,
        status=doc.frontmatter.status,
        owner=doc.frontmatter.owner,
        team=doc.frontmatter.team,
        tags=doc.frontmatter.tags,
        total_sections=total_sections,
        done_sections=done_sections,
        total_ac=total_ac,
        done_ac=done_ac,
        review_status=doc.frontmatter.review_status,
    )


async def _load_config(
    client: GitHubClient,
    owner: str,
    repo: str,
    cache: TTLCache,
    *,
    content_cache_store: object | None = None,
) -> CanonConfig | None:
    """Load CANON.yaml (or legacy SPECWRIGHT.yaml) for a repo, using cache.

    When ``content_cache_store`` is provided, the persisted config is read
    from Postgres before falling back to GitHub. A cache read or parse
    failure logs at WARNING (a corrupt cached row is a real defect, not
    debug noise) and falls through to the GitHub path so dashboards still
    load.
    """
    cache_key = f"config:{owner}/{repo}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if content_cache_store is not None:
        try:
            row = await content_cache_store.get_config(owner, repo)
        except Exception:
            row = None
            logger.warning(
                "Content cache config read failed for %s/%s — falling back to GitHub",
                owner,
                repo,
                exc_info=True,
            )
        if row and row.get("config_yaml"):
            try:
                config = parse_canon_yaml(row["config_yaml"]).config
                cache.set(cache_key, config)
                return config
            except Exception:
                logger.warning(
                    "Cached CANON.yaml failed to parse for %s/%s — falling back to GitHub",
                    owner,
                    repo,
                    exc_info=True,
                )

    try:
        try:
            content, _ = await client.get_file_content(owner, repo, "CANON.yaml")
        except Exception:
            content, _ = await client.get_file_content(owner, repo, "SPECWRIGHT.yaml")
        result = parse_canon_yaml(content)
        cache.set(cache_key, result.config)
        return result.config
    except Exception:
        cache.set(cache_key, None)
        return None


def _classify_doc_type(path: str) -> str:
    """Classify a document type from its file path.

    Delegates to shared classifier.
    """
    return classify_doc_type(path)


async def _list_indexed_docs(
    client: GitHubClient,
    owner: str,
    repo: str,
    *,
    search_index: object | None = None,
    indexed_paths: dict[str, dict] | None = None,
    spec_patterns: list[str] | None = None,
) -> list[DocFile]:
    """List non-spec docs — from search index when available, else GitHub API.

    Contract on ``indexed_paths``:
      * dict (possibly empty) — search index answered authoritatively;
        trust it and skip the GitHub fallback.
      * ``None`` — search index errored or wasn't queried; fall back to the
        per-repo directory listing so users still see docs even when the
        index is degraded.
    """
    from ..github.spec_utils import matches_doc_patterns

    full_name = f"{owner}/{repo}"
    docs: list[DocFile] = []

    def _is_spec(path: str) -> bool:
        if spec_patterns is not None:
            return matches_doc_patterns(path, spec_patterns)
        return classify_doc_type(path) == "spec"

    if indexed_paths is not None:
        prefix = f"{full_name}/"
        for key in indexed_paths:
            if not key.startswith(prefix):
                continue
            file_path = key[len(prefix) :]
            if _is_spec(file_path):
                continue  # Specs are listed separately
            doc_type = _classify_doc_type(file_path)
            name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
            docs.append(
                DocFile(
                    path=file_path,
                    name=name,
                    github_url=f"https://github.com/{owner}/{repo}/blob/main/{file_path}",
                    doc_type=doc_type,
                    is_indexed=True,
                )
            )
        return docs

    # Fallback: check root and docs/ via GitHub API
    try:
        entries = await client.list_directory(owner, repo, "")
        for e in entries:
            name = e.get("name", "")
            if (
                name.lower() in ("readme.md", "changelog.md", "contributing.md")
                and e.get("type") == "file"
            ):
                docs.append(
                    DocFile(
                        path=e["path"],
                        name=name,
                        github_url=e.get(
                            "html_url", f"https://github.com/{owner}/{repo}/blob/main/{e['path']}"
                        ),
                        doc_type=_classify_doc_type(e["path"]),
                    )
                )
    except Exception:
        logger.debug("Failed to list root directory for %s/%s", owner, repo, exc_info=True)

    try:
        entries = await client.list_directory(owner, repo, "docs")
        for e in entries:
            name = e.get("name", "")
            if e.get("type") == "file" and name.endswith(".md") and not _is_spec(e.get("path", "")):
                docs.append(
                    DocFile(
                        path=e["path"],
                        name=name,
                        github_url=e.get(
                            "html_url", f"https://github.com/{owner}/{repo}/blob/main/{e['path']}"
                        ),
                        doc_type=_classify_doc_type(e["path"]),
                    )
                )
    except Exception:
        logger.debug("Failed to list docs directory for %s/%s", owner, repo, exc_info=True)

    return docs


async def get_org_overview(
    client: GitHubClient,
    org: str,
    cache: TTLCache,
    *,
    search_index: object | None = None,
    content_cache_store: object | None = None,
    ref_store: object | None = None,
    installation_id: int | None = None,
) -> OrgOverview:
    """Get the full org dashboard overview.

    Uses request coalescing so concurrent callers share a single in-flight
    fetch instead of each hitting the GitHub API independently.

    When content_cache_store is provided, loads specs from Postgres instead
    of GitHub, eliminating API rate-limit pressure.
    """
    cache_key = f"org_overview:{org}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Coalesce: if another request is already fetching this overview, wait
    # for it instead of issuing duplicate GitHub API calls.
    inflight = _inflight.get(cache_key)
    if inflight is not None and not inflight.done():
        return await inflight

    task = asyncio.create_task(
        _fetch_org_overview(
            client,
            org,
            cache,
            cache_key=cache_key,
            search_index=search_index,
            content_cache_store=content_cache_store,
            ref_store=ref_store,
            installation_id=installation_id,
        )
    )
    _inflight[cache_key] = task
    try:
        return await task
    finally:
        # Only remove our own task — a successor may have replaced it.
        if _inflight.get(cache_key) is task:
            del _inflight[cache_key]


async def _fetch_org_overview(
    client: GitHubClient,
    org: str,
    cache: TTLCache,
    *,
    cache_key: str,
    search_index: object | None = None,
    content_cache_store: object | None = None,
    ref_store: object | None = None,
    installation_id: int | None = None,
) -> OrgOverview:
    """Internal: actually fetch the org overview.

    When content_cache_store is provided, loads specs from Postgres
    (parsing cached raw_markdown) instead of fetching from GitHub.
    """
    # Cache repo list separately with a longer TTL — repos rarely change.
    repo_cache_key = f"repo_list:{org}"
    repos = cache.get(repo_cache_key)
    if repos is None:
        repos = await client.list_installation_repos()
        cache.set_with_ttl(repo_cache_key, repos, _REPO_LIST_TTL)

    repos_with_specs: list[RepoSummary] = []
    repos_without_specs: list[RepoSummary] = []
    total_specs = 0
    total_docs = 0

    # Query indexed paths once if search_index is available. Stays None on
    # error so _list_indexed_docs can distinguish "index returned empty"
    # (authoritative) from "index unreachable" (fall back to GitHub).
    indexed_paths: dict[str, dict] | None = None
    if search_index is not None:
        try:
            indexed_paths = await search_index.get_indexed_paths()
        except Exception:
            logger.warning("Failed to query indexed paths", exc_info=True)

    # Pre-fetch broken refs for this installation in one query, then
    # bucket by repo using the ticket_ref's leading prefix. Refs with
    # status='dismissed' are excluded — the dashboard "needs attention"
    # count should reflect actionable breakage only.
    broken_by_repo: dict[str, int] = {}
    total_broken: int = 0
    if ref_store is not None and installation_id is not None:
        try:
            broken_rows = await ref_store.list_broken(installation_id=installation_id)
        except Exception:
            logger.warning(
                "list_broken failed during org overview — broken-ref counts default to 0",
                exc_info=True,
            )
            broken_rows = []
        for row in broken_rows:
            ref = row.get("ticket_ref", "")
            # github refs are 'org/repo#N'; jira/linear refs aren't
            # repo-scoped so they bucket under '' and are counted only
            # in total_broken
            repo_prefix = ref.rsplit("#", 1)[0] if "#" in ref else ""
            if repo_prefix:
                broken_by_repo[repo_prefix] = broken_by_repo.get(repo_prefix, 0) + 1
            total_broken += 1

    for repo_data in repos:
        owner = repo_data["owner"]["login"]
        repo_name = repo_data["name"]
        full_name = repo_data["full_name"]
        description = repo_data.get("description") or ""
        default_branch = repo_data.get("default_branch", "main")

        config = await _load_config(
            client, owner, repo_name, cache, content_cache_store=content_cache_store
        )
        doc_paths = config.specs.doc_paths if config else None

        # Try content cache first, fall back to GitHub
        specs_data = None
        if content_cache_store is not None:
            specs_data = await _load_specs_from_cache(
                content_cache_store, owner, repo_name, doc_paths
            )

        if specs_data is None:
            specs_data = await load_repo_specs(client, owner, repo_name, patterns=doc_paths)

        # Cache full documents for section-level search
        for sd in specs_data:
            doc_cache_key = f"spec_doc:{full_name}/{sd['document'].file_path}"
            cache.set(doc_cache_key, sd["document"])
        docs = await _list_indexed_docs(
            client,
            owner,
            repo_name,
            search_index=search_index,
            indexed_paths=indexed_paths,
            spec_patterns=doc_paths,
        )

        spec_summaries = [_summarize_spec(s["document"]) for s in specs_data]

        # Mark indexed specs
        if indexed_paths:
            for spec in spec_summaries:
                key = f"{full_name}/{spec.file_path}"
                if key in indexed_paths:
                    spec.is_indexed = True

        summary = RepoSummary(
            owner=owner,
            repo=repo_name,
            full_name=full_name,
            description=description,
            default_branch=default_branch,
            has_specs=len(spec_summaries) > 0,
            spec_count=len(spec_summaries),
            specs=spec_summaries,
            config=config,
            docs=docs,
            broken_refs_count=broken_by_repo.get(full_name, 0),
        )

        if spec_summaries:
            repos_with_specs.append(summary)
            total_specs += len(spec_summaries)
        else:
            repos_without_specs.append(summary)
        total_docs += len(docs)

    overview = OrgOverview(
        org=org,
        repos_with_specs=repos_with_specs,
        repos_without_specs=repos_without_specs,
        total_specs=total_specs,
        total_repos=len(repos),
        total_docs=total_docs,
        total_broken_refs=total_broken,
    )
    cache.set_with_ttl(cache_key, overview, _ORG_OVERVIEW_TTL)
    return overview


async def _load_specs_from_cache(
    content_cache_store: object,
    owner: str,
    repo: str,
    doc_paths: list[str] | None,
) -> list[dict] | None:
    """Load specs from Postgres content cache.

    Returns list of dicts matching the shape of load_repo_specs() output:
    [{"file_path": str, "document": SpecDocument, "raw": str, "sha": str}]

    Returns None if no cached specs found (triggers GitHub fallback).
    """
    from ..parser.models import ParseOptions
    from ..parser.parse import parse_spec

    try:
        from ..github.spec_utils import filter_spec_files

        full_repo = f"{owner}/{repo}"
        # Single query includes raw_markdown — no N+1 round trips
        cached_specs = await content_cache_store.list_specs_with_content(full_repo)

        if not cached_specs:
            return None  # No cached data — fall back to GitHub

        # Apply doc_paths filter to match the GitHub read path behaviour.
        # Without this, repos with custom doc_paths patterns would show
        # extra specs from the cache that load_repo_specs() would filter out.
        if doc_paths is not None:
            allowed_paths = set(
                filter_spec_files([s["path"] for s in cached_specs], patterns=doc_paths)
            )
            cached_specs = [s for s in cached_specs if s["path"] in allowed_paths]

        results = []
        for spec_meta in cached_specs:
            raw = spec_meta.get("raw_markdown")
            if not raw:
                continue
            result = parse_spec(raw, ParseOptions(file_path=spec_meta["path"]))
            results.append(
                {
                    "file_path": spec_meta["path"],
                    "document": result.document,
                    "raw": raw,
                    "sha": spec_meta.get("github_sha", ""),
                }
            )
        return results or None  # Empty list triggers GitHub fallback
    except Exception:
        logger.debug(
            "Failed to load specs from content cache for %s/%s", owner, repo, exc_info=True
        )
        return None


async def get_repo_detail(
    client: GitHubClient,
    owner: str,
    repo: str,
    cache: TTLCache,
    *,
    search_index: object | None = None,
    content_cache_store: object | None = None,
) -> RepoSummary | None:
    """Get detailed view of a single repo's specs."""
    cache_key = f"repo:{owner}/{repo}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        repo_data = await client._get(f"/repos/{owner}/{repo}")
    except Exception:
        return None

    # Query indexed paths for this repo if search index available
    indexed_paths: dict[str, dict] | None = None
    if search_index is not None:
        try:
            indexed_paths = await search_index.get_indexed_paths()
        except Exception:
            logger.warning("Failed to query indexed paths for repo detail", exc_info=True)

    config = await _load_config(client, owner, repo, cache, content_cache_store=content_cache_store)
    doc_paths = config.specs.doc_paths if config else None
    # Try content cache first, fall back to GitHub
    specs_data = None
    if content_cache_store is not None:
        specs_data = await _load_specs_from_cache(content_cache_store, owner, repo, doc_paths)
    if specs_data is None:
        specs_data = await load_repo_specs(client, owner, repo, patterns=doc_paths)
    docs = await _list_indexed_docs(
        client,
        owner,
        repo,
        search_index=search_index,
        indexed_paths=indexed_paths,
        spec_patterns=doc_paths,
    )

    spec_summaries = [_summarize_spec(s["document"]) for s in specs_data]

    summary = RepoSummary(
        owner=owner,
        repo=repo,
        full_name=repo_data["full_name"],
        description=repo_data.get("description") or "",
        default_branch=repo_data.get("default_branch", "main"),
        has_specs=len(spec_summaries) > 0,
        spec_count=len(spec_summaries),
        specs=spec_summaries,
        config=config,
        docs=docs,
    )

    cache.set(cache_key, summary)
    return summary


async def get_spec_detail(
    client: GitHubClient,
    owner: str,
    repo: str,
    file_path: str,
    cache: TTLCache,
    *,
    content_cache_store: object | None = None,
    ref_store: object | None = None,
    installation_id: int | None = None,
) -> SpecDetail | None:
    """Get full spec detail with rendered HTML.

    When content_cache_store is provided, reads from Postgres first
    and falls back to GitHub on cache miss.

    When ref_store and installation_id are provided, attaches a list of
    BrokenRef entries (one per section whose ticket_ref maps to a 'broken'
    row). Falls open to [] on store error or when the kwargs are omitted.
    """
    cache_key = f"spec:{owner}/{repo}/{file_path}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    content: str | None = None

    # Try Postgres content cache first
    if content_cache_store is not None:
        try:
            content = await content_cache_store.get_spec_raw(f"{owner}/{repo}", file_path)
        except Exception:
            logger.warning(
                "Content cache read failed for %s/%s/%s", owner, repo, file_path, exc_info=True
            )

    # Fall back to GitHub
    if content is None:
        try:
            content, _ = await client.get_file_content(owner, repo, file_path)
        except Exception:
            return None

        # Write-through: cache the content we just fetched from GitHub
        if content_cache_store is not None:
            try:
                from ..sync.content_sync import ContentSyncEngine

                engine = ContentSyncEngine(content_cache_store, client)
                await engine.sync_spec(owner, repo, file_path, content)
            except Exception:
                logger.debug(
                    "Write-through cache population failed for %s/%s/%s",
                    owner,
                    repo,
                    file_path,
                    exc_info=True,
                )

    from ..parser.models import ParseOptions
    from ..parser.parse import parse_spec

    result = parse_spec(content, ParseOptions(file_path=file_path))
    rendered_html = render_spec_html(result.document, repo_owner=owner, repo_name=repo)
    config = await _load_config(client, owner, repo, cache, content_cache_store=content_cache_store)

    broken_sections: list[BrokenRef] = []
    if ref_store is not None and installation_id is not None:
        try:
            broken_rows = await ref_store.list_broken(installation_id=installation_id)
        except Exception:
            logger.warning(
                "list_broken failed during spec detail — broken_sections defaults to []",
                exc_info=True,
            )
            broken_rows = []

        # Index broken rows by ticket_ref for O(1) section lookup
        broken_by_ref: dict[str, dict] = {
            row["ticket_ref"]: row for row in broken_rows if row.get("status") == "broken"
        }

        if broken_by_ref:
            from ..sync.ticket_ref import qualify

            for section in flatten_sections(result.document.sections):
                link = section.ticket_link
                if not link:
                    continue
                try:
                    section_ref = qualify(link.system, f"{owner}/{repo}", link.ticket_id)
                except Exception:
                    continue
                row = broken_by_ref.get(section_ref)
                if row is None:
                    continue
                broken_sections.append(
                    BrokenRef(
                        system=link.system,
                        ticket_ref=section_ref,
                        spec_path=f"{owner}/{repo}/{file_path}",
                        section_id=section.id,
                        section_heading=_section_heading(section),
                        error_kind=_coerce_error_kind(row.get("last_error_kind")),
                        first_failure_at=row["first_failure_at"],
                        last_check_at=row["last_check_at"],
                        dismissed=row.get("status") == "dismissed",
                        dismissed_by=row.get("dismissed_by"),
                    )
                )

    detail = SpecDetail(
        document=result.document,
        rendered_html=rendered_html,
        repo_owner=owner,
        repo_name=repo,
        github_url=f"https://github.com/{owner}/{repo}/blob/main/{file_path}",
        config=config,
        broken_sections=broken_sections,
    )

    cache.set(cache_key, detail)
    return detail


async def list_broken_refs(
    ref_store: object,
    installation_id: int,
    cache: TTLCache,
    *,
    org: str,
    status: str = "broken",
    system: str | None = None,
    repo: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[BrokenRef], int]:
    """Return (items, total) for the paginated dashboard list.

    Filtering by repo / system happens here in Python after a single
    list_broken query — the row volume is small enough (broken-ref
    population is bounded by total spec count x ~1) that paging in SQL
    isn't worth the complexity in v1.
    """
    rows = await ref_store.list_broken(installation_id=installation_id, status=status)

    def matches(row: dict) -> bool:
        if system and row.get("system") != system:
            return False
        if repo:
            ref = row.get("ticket_ref", "")
            if "#" in ref and ref.rsplit("#", 1)[0] != repo:
                return False
            if "#" not in ref:
                # jira/linear rows aren't repo-scoped → only surface
                # them when repo filter is empty
                return False
        return True

    filtered = [r for r in rows if matches(r)]
    total = len(filtered)
    items = [_row_to_broken_ref(r) for r in filtered[offset : offset + limit]]
    return items, total


def _row_to_broken_ref(row: dict) -> BrokenRef:
    """Convert a ticket_ref_status row dict into the API-facing model.

    spec_path / section_id / section_heading are left empty here —
    the dashboard list endpoint elides per-row spec lookup. The user
    clicks through to the spec view where get_spec_detail provides
    section-level context.
    """
    return BrokenRef(
        system=row["system"],
        ticket_ref=row["ticket_ref"],
        spec_path="",
        section_id="",
        section_heading="",
        error_kind=_coerce_error_kind(row.get("last_error_kind")),
        first_failure_at=row["first_failure_at"],
        last_check_at=row["last_check_at"],
        dismissed=row.get("status") == "dismissed",
        dismissed_by=row.get("dismissed_by"),
    )


async def count_broken_refs(
    ref_store: object,
    installation_id: int,
) -> int:
    """Return the count of broken (not dismissed) refs for an installation."""
    rows = await ref_store.list_broken(installation_id=installation_id, status="broken")
    return len(rows)


async def get_doc_detail(
    client: GitHubClient,
    owner: str,
    repo: str,
    file_path: str,
    cache: TTLCache,
) -> DocDetail | None:
    """Get full doc detail with rendered HTML."""
    cache_key = f"doc:{owner}/{repo}/{file_path}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        content, _ = await client.get_file_content(owner, repo, file_path)
    except Exception:
        return None

    rendered_html = render_markdown_html(content)

    # Extract title from first heading or filename
    title = file_path.rsplit("/", 1)[-1]
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break

    detail = DocDetail(
        path=file_path,
        title=title,
        rendered_html=rendered_html,
        repo_owner=owner,
        repo_name=repo,
        github_url=f"https://github.com/{owner}/{repo}/blob/main/{file_path}",
        doc_type=_classify_doc_type(file_path),
    )

    cache.set(cache_key, detail)
    return detail


def _search_cache_key(
    org: str, query: str, team: str, status: str, tag: str, repo: str, review_status: str = ""
) -> str:
    """Build a normalized cache key for search results."""
    return f"search:{org}:{query}:{team}:{status}:{tag}:{repo}:{review_status}"


def invalidate_search_cache(cache: TTLCache, org: str) -> None:
    """Invalidate all search and facet caches for an org."""
    cache.invalidate_prefix(f"search:{org}:")
    cache.invalidate_prefix(f"facets:{org}:")


async def search_specs(
    client: GitHubClient,
    org: str,
    cache: TTLCache,
    *,
    query: str = "",
    team: str = "",
    status: str = "",
    tag: str = "",
    repo: str = "",
    review_status: str = "",
    search_index=None,
    embed_client=None,
) -> list[SpecSearchResult]:
    """Search across specs — uses DB hybrid search when available, falls back to in-memory."""
    # Try DB search when available and we have a query or status filter
    if (query or status) and search_index is not None:
        cache_key = _search_cache_key(org, query, team, status, tag, repo, review_status)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            db_results = await _db_search(
                search_index,
                embed_client,
                query=query,
                repo=repo or None,
                status=status or None,
                limit=30,
            )
            if db_results is not None:
                # Apply team/tag/review_status filters in-memory (DB doesn't support these yet)
                if team:
                    db_results = [r for r in db_results if r.team.lower() == team.lower()]
                if tag:
                    db_results = [
                        r for r in db_results if tag.lower() in [t.lower() for t in r.tags]
                    ]
                if review_status:
                    db_results = [
                        r for r in db_results if getattr(r, "review_status", None) == review_status
                    ]
                results = _deduplicate_results(db_results)
                cache.set(cache_key, results)
                return results
        except Exception:
            logger.warning("DB search failed, falling back to in-memory", exc_info=True)

    # In-memory search with section-level matching
    overview = await get_org_overview(client, org, cache)
    results: list[SpecSearchResult] = []
    query_lower = query.lower()
    query_words = query_lower.split() if query_lower else []

    for r in overview.repos_with_specs:
        if repo and r.full_name.lower() != repo.lower():
            continue
        for spec in r.specs:
            # Apply filters
            if team and spec.team.lower() != team.lower():
                continue
            if status and spec.status.lower() != status.lower():
                continue
            if tag and tag.lower() not in [t.lower() for t in spec.tags]:
                continue
            if review_status and getattr(spec, "review_status", None) != review_status:
                continue

            if not query_lower:
                # No query — return all specs matching filters
                results.append(
                    SpecSearchResult(
                        file_path=spec.file_path,
                        title=spec.title,
                        status=spec.status,
                        owner=spec.owner,
                        team=spec.team,
                        repo_full_name=r.full_name,
                        repo_owner=r.owner,
                        repo_name=r.repo,
                        tags=spec.tags,
                        review_status=getattr(spec, "review_status", None),
                    )
                )
                continue

            # Section-level search: try to find matches in sections/ACs
            doc_cache_key = f"spec_doc:{r.full_name}/{spec.file_path}"
            doc: SpecDocument | None = cache.get(doc_cache_key)

            if doc is not None:
                section_results = _search_document_sections(
                    doc, query_lower, query_words, spec, r.full_name, r.owner, r.repo
                )
                results.extend(section_results)
            elif query_lower in spec.title.lower():
                # Fallback: title-only match if doc not cached
                results.append(
                    SpecSearchResult(
                        file_path=spec.file_path,
                        title=spec.title,
                        status=spec.status,
                        owner=spec.owner,
                        team=spec.team,
                        repo_full_name=r.full_name,
                        repo_owner=r.owner,
                        repo_name=r.repo,
                        tags=spec.tags,
                        review_status=getattr(spec, "review_status", None),
                        score=1.0,
                    )
                )

    # Sort by score descending
    if query_lower:
        results.sort(key=lambda r: r.score, reverse=True)

    return results


def _search_document_sections(
    doc: SpecDocument,
    query_lower: str,
    query_words: list[str],
    spec: SpecSummary,
    repo_full_name: str,
    repo_owner: str,
    repo_name: str,
) -> list[SpecSearchResult]:
    """Search within a parsed spec document at section and AC level.

    Returns one result per matching section (or a spec-level result if only title matches).
    """
    results: list[SpecSearchResult] = []
    seen_spec = False

    all_sections = _flatten_all_sections(doc.sections)
    for section in all_sections:
        heading = (
            f"{section.section_number}. {section.title}"
            if section.section_number
            else section.title
        )
        heading_lower = heading.lower()
        content_lower = (section.content or "").lower()
        ac_texts = [ac.text.lower() for ac in section.acceptance_criteria]
        ac_joined = " ".join(ac_texts)

        # Score: title match (3), heading match (2), AC match (1.5), content match (1)
        score = 0.0
        snippet = ""

        if query_lower in heading_lower:
            score += 2.0
        if query_lower in content_lower:
            score += 1.0
            snippet = _extract_snippet(section.content or "", query_lower)
        if query_lower in ac_joined:
            score += 1.5
            # Find the matching AC for snippet
            for ac_text in ac_texts:
                if query_lower in ac_text:
                    snippet = snippet or _extract_snippet(
                        next(
                            ac.text
                            for ac in section.acceptance_criteria
                            if ac.text.lower() == ac_text
                        ),
                        query_lower,
                    )
                    break

        # Also try word-level matching for multi-word queries
        if score == 0 and len(query_words) > 1:
            searchable = f"{heading_lower} {content_lower} {ac_joined}"
            matched_words = sum(1 for w in query_words if w in searchable)
            if matched_words >= len(query_words) * 0.6:
                score = 0.5 * (matched_words / len(query_words))
                snippet = (
                    _extract_snippet(section.content or "", query_words[0])
                    if section.content
                    else ""
                )

        if score > 0:
            seen_spec = True
            results.append(
                SpecSearchResult(
                    file_path=spec.file_path,
                    title=spec.title,
                    status=spec.status,
                    owner=spec.owner,
                    team=spec.team,
                    repo_full_name=repo_full_name,
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    tags=spec.tags,
                    heading=heading,
                    snippet=snippet,
                    score=score,
                    review_status=getattr(spec, "review_status", None),
                )
            )

    # If no section matched, try spec title
    if not seen_spec and query_lower in spec.title.lower():
        results.append(
            SpecSearchResult(
                file_path=spec.file_path,
                title=spec.title,
                status=spec.status,
                owner=spec.owner,
                team=spec.team,
                repo_full_name=repo_full_name,
                repo_owner=repo_owner,
                repo_name=repo_name,
                tags=spec.tags,
                score=3.0,
                review_status=getattr(spec, "review_status", None),
            )
        )

    return results


def _extract_snippet(text: str, query: str, max_length: int = 160) -> str:
    """Extract a snippet around the first occurrence of the query in text."""
    lower = text.lower()
    idx = lower.find(query)
    if idx == -1:
        return text[:max_length].strip()

    # Expand to include surrounding context
    start = max(0, idx - 40)
    end = min(len(text), idx + len(query) + 120)

    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


async def get_facet_counts(
    client: GitHubClient,
    org: str,
    cache: TTLCache,
    *,
    search_index=None,
    repo: str = "",
) -> FacetCounts:
    """Get aggregate facet counts for filtering UI.

    Uses DB aggregation when search_index is available, falls back to in-memory counting.
    """
    if search_index is not None:
        facet_cache_key = f"facets:{org}:{repo}"
        cached = cache.get(facet_cache_key)
        if cached is not None:
            return cached

        try:
            raw = await search_index.get_facet_counts(repo=repo or None)
            result = FacetCounts(
                status=raw.get("status", {}),
                repo=raw.get("repo", {}),
                team=raw.get("team", {}),
                tag=raw.get("tag", {}),
            )
            cache.set(facet_cache_key, result)
            return result
        except Exception:
            logger.warning("DB facet counts failed, falling back to in-memory", exc_info=True)

    # In-memory fallback: count from org overview
    overview = await get_org_overview(client, org, cache)
    status_counts: dict[str, int] = {}
    repo_counts: dict[str, int] = {}
    team_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    for r in overview.repos_with_specs:
        if repo and r.full_name.lower() != repo.lower():
            continue
        for spec in r.specs:
            s = spec.status or "unknown"
            status_counts[s] = status_counts.get(s, 0) + 1
            if spec.team:
                team_counts[spec.team] = team_counts.get(spec.team, 0) + 1
            for t in spec.tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        repo_counts[r.full_name] = r.spec_count

    return FacetCounts(status=status_counts, repo=repo_counts, team=team_counts, tag=tag_counts)


async def get_indexing_overview(registry, indexer) -> dict:
    """Get indexing status across all installations for the admin page."""
    installations = []
    recent_jobs = []
    active_tasks = []

    if registry is not None:
        try:
            installations = await registry.get_all_installations()
        except Exception:
            logger.warning("Failed to load installations", exc_info=True)

        try:
            jobs = await registry.get_index_jobs(limit=50)
            recent_jobs = jobs
        except Exception:
            logger.warning("Failed to load index jobs", exc_info=True)

    if indexer is not None:
        active_tasks = indexer.get_tasks()

    return {
        "installations": installations,
        "recent_jobs": recent_jobs,
        "active_tasks": active_tasks,
    }


def compute_coverage_summary(
    *,
    total_specs: int = 0,
    total_sections: int = 0,
    done_sections: int = 0,
    total_ac: int = 0,
    done_ac: int = 0,
    realized_ac: int = 0,
) -> CoverageSummary:
    """Compute coverage percentages and health score from raw counts."""
    section_pct = (done_sections / total_sections * 100) if total_sections else 0.0
    ac_pct = (done_ac / total_ac * 100) if total_ac else 0.0
    realization_pct = (realized_ac / total_ac * 100) if total_ac else 0.0
    health = section_pct * 0.3 + ac_pct * 0.3 + realization_pct * 0.4

    return CoverageSummary(
        total_specs=total_specs,
        total_sections=total_sections,
        done_sections=done_sections,
        total_ac=total_ac,
        done_ac=done_ac,
        realized_ac=realized_ac,
        section_coverage_pct=round(section_pct, 1),
        ac_coverage_pct=round(ac_pct, 1),
        realization_rate_pct=round(realization_pct, 1),
        health_score=round(health, 1),
    )


async def get_coverage(
    client: GitHubClient,
    org: str,
    cache: TTLCache,
    *,
    repo: str = "",
    team: str = "",
    days: int = 30,
    agent_store=None,
) -> CoverageApiResponse:
    """Get aggregate coverage metrics with optional time-series trend.

    Uses DB snapshots when agent_store is available, falls back to in-memory
    counting from the org overview (no trend data in that case).
    """
    cache_key = f"coverage:{org}:{repo}:{team}:{days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # DB path — use coverage snapshots
    if agent_store is not None:
        try:
            raw = await agent_store.get_coverage_summary(org, repo=repo or None, team=team or None)
            summary = compute_coverage_summary(
                total_specs=raw.get("total_specs", 0),
                total_sections=raw.get("total_sections", 0),
                done_sections=raw.get("done_sections", 0),
                total_ac=raw.get("total_ac", 0),
                done_ac=raw.get("done_ac", 0),
                realized_ac=raw.get("realized_ac", 0),
            )

            trend_raw = await agent_store.get_coverage_trend(
                org, repo=repo or None, team=team or None, days=days
            )
            trend = [
                CoverageTrendPoint(
                    date=t["date"],
                    total_sections=t["total_sections"],
                    done_sections=t["done_sections"],
                    total_ac=t["total_ac"],
                    done_ac=t["done_ac"],
                    realized_ac=t["realized_ac"],
                )
                for t in trend_raw
            ]

            result = CoverageApiResponse(summary=summary, trend=trend)
            cache.set(cache_key, result)
            return result
        except Exception:
            logger.warning("DB coverage query failed, falling back to in-memory", exc_info=True)

    # In-memory fallback — aggregate from org overview
    overview = await get_org_overview(client, org, cache)
    total_sections = 0
    done_sections = 0
    total_ac = 0
    done_ac = 0
    total_specs = 0

    for r in overview.repos_with_specs:
        if repo and r.full_name.lower() != repo.lower():
            continue
        for spec in r.specs:
            if team and spec.team.lower() != team.lower():
                continue
            total_specs += 1
            total_sections += spec.total_sections
            done_sections += spec.done_sections
            total_ac += spec.total_ac
            done_ac += spec.done_ac

    summary = compute_coverage_summary(
        total_specs=total_specs,
        total_sections=total_sections,
        done_sections=done_sections,
        total_ac=total_ac,
        done_ac=done_ac,
        realized_ac=0,  # Not available without DB
    )

    result = CoverageApiResponse(summary=summary, trend=[])
    cache.set(cache_key, result)
    return result


def _highlight_terms(text: str, query: str) -> str:
    """Escape HTML in text, then wrap matching query terms in <mark> tags."""
    if not query or not text:
        return html.escape(text)

    escaped = html.escape(text)
    for term in query.split():
        if len(term) < 2:
            continue
        pattern = re.compile(re.escape(html.escape(term)), re.IGNORECASE)
        escaped = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped)
    return escaped


def _deduplicate_results(
    results: list[SpecSearchResult],
) -> list[SpecSearchResult]:
    """Group results by spec — keep the top-scoring section per spec."""
    seen: dict[str, SpecSearchResult] = {}
    counts: dict[str, int] = {}

    for r in results:
        key = f"{r.repo_full_name}/{r.file_path}"
        counts[key] = counts.get(key, 0) + 1
        if key not in seen or r.score > seen[key].score:
            seen[key] = r

    deduped: list[SpecSearchResult] = []
    for key, r in seen.items():
        extra = counts[key] - 1
        if extra > 0:
            r = r.model_copy(
                update={"heading": f"{r.heading} (+{extra} more match{'es' if extra != 1 else ''})"}
            )
        deduped.append(r)

    deduped.sort(key=lambda r: r.score, reverse=True)
    return deduped


async def _db_search(
    search_index,
    embed_client,
    query: str,
    repo: str | None = None,
    status: str | None = None,
    limit: int = 30,
) -> list[SpecSearchResult]:
    """Execute DB hybrid search and convert results to SpecSearchResult."""
    query_embedding = None
    if query and embed_client is not None and getattr(embed_client, "is_available", False):
        try:
            query_embedding = embed_client.embed_query(query)
        except Exception:
            logger.warning("Failed to embed query — searching without vector", exc_info=True)

    results = await search_index.hybrid_search(
        query_embedding=query_embedding,
        query_text=query or "",
        repo=repo,
        status=status,
        limit=limit,
    )

    search_results: list[SpecSearchResult] = []
    for r in results:
        parts = r.repo.split("/", 1)
        repo_owner = parts[0] if len(parts) == 2 else ""
        repo_name = parts[1] if len(parts) == 2 else r.repo

        # Truncate body for snippet, then highlight query terms
        snippet = r.body[:150].strip()
        if len(r.body) > 150:
            snippet += "..."
        snippet = _highlight_terms(snippet, query)

        search_results.append(
            SpecSearchResult(
                file_path=r.path,
                title=r.doc_title,
                status=r.status,
                owner="",
                team="",
                repo_full_name=r.repo,
                repo_owner=repo_owner,
                repo_name=repo_name,
                tags=[],
                heading=r.heading,
                snippet=snippet,
                score=r.rrf_score,
                doc_type=_classify_doc_type(r.path),
            )
        )

    return search_results


# ─── Tasks ───────────────────────────────────────────────


ACTIVE_STATUSES = {"todo", "in_progress", "blocked"}


def _flatten_all_sections(sections: list[SpecSection]) -> list[SpecSection]:
    result: list[SpecSection] = []
    for section in sections:
        result.append(section)
        result.extend(_flatten_all_sections(section.children))
    return result


async def get_tasks(
    client: GitHubClient,
    org: str,
    cache: TTLCache,
    *,
    status: str | None = None,
    repo_filter: str | None = None,
    search_index: object | None = None,
    expand: str | None = None,
    content_cache_store: object | None = None,
) -> TasksApiResponse:
    """Extract actionable tasks from all specs across the org."""
    overview = await get_org_overview(
        client, org, cache, search_index=search_index, content_cache_store=content_cache_store
    )
    tasks: list[TaskItem] = []

    target_statuses = {status} if status else ACTIVE_STATUSES

    for repo in overview.repos_with_specs:
        if repo_filter and repo.full_name != repo_filter:
            continue

        for spec_summary in repo.specs:
            try:
                detail = await get_spec_detail(
                    client,
                    repo.owner,
                    repo.repo,
                    spec_summary.file_path,
                    cache,
                    content_cache_store=content_cache_store,
                )
                if not detail:
                    continue

                all_sections = _flatten_all_sections(detail.document.sections)
                for section in all_sections:
                    if section.status.state not in target_statuses:
                        continue

                    total_ac = len(section.acceptance_criteria)
                    done_ac = sum(1 for ac in section.acceptance_criteria if ac.checked)

                    tasks.append(
                        TaskItem(
                            section_id=section.id,
                            section_number=section.section_number,
                            title=section.title,
                            status=section.status.state,
                            blocked_by=section.status.blocked_by,
                            total_ac=total_ac,
                            done_ac=done_ac,
                            ticket_system=section.ticket_link.system
                            if section.ticket_link
                            else None,
                            ticket_id=section.ticket_link.ticket_id
                            if section.ticket_link
                            else None,
                            spec_title=detail.document.frontmatter.title,
                            spec_file_path=detail.document.file_path,
                            repo_owner=repo.owner,
                            repo_name=repo.repo,
                            acceptance_criteria=[
                                {"text": ac.text, "checked": ac.checked}
                                for ac in section.acceptance_criteria
                            ]
                            if expand == "acs"
                            else [],
                        )
                    )
            except Exception:
                logger.warning("Failed to load spec %s for tasks", spec_summary.file_path)

    return TasksApiResponse(tasks=tasks, total=len(tasks))


class SectionNotFoundError(Exception):
    """Raised when the requested section_id doesn't exist in the spec."""


class SectionAlreadyUpdatedError(Exception):
    """Raised when the section exists but its ticket_link was already
    removed/changed since the dashboard surfaced this row."""


@dataclass
class RemoveTicketRefResult:
    pr_number: int
    pr_url: str
    already_existed: bool = False
    # Qualified ticket_ref of the comment that was (or would be) stripped.
    # Returned so the route layer can auto-dismiss the matching
    # ticket_ref_status row without re-deriving it.
    system: str = ""
    ticket_ref: str = ""


async def remove_ticket_ref(
    client,
    content_cache_store,
    *,
    owner: str,
    repo: str,
    file_path: str,
    section_id: str,
) -> RemoveTicketRefResult:
    """Open a doc PR that strips the ticket-link comment from a section.

    Reads the spec from the content cache (or GitHub if the cache is
    None/unavailable), parses it, locates the target section, drops
    the line containing `<!-- canon:ticket:... -->` within the
    section's [start_line, end_line] range, and opens (or returns the
    existing) doc PR via client.create_doc_pr.

    Branch name is deterministic per section_id so re-runs find the
    existing PR (already_existed=True) rather than duplicating.

    Raises:
      SectionNotFoundError: section_id not in the spec.
      SectionAlreadyUpdatedError: section exists but has no ticket_link
        (someone already removed it; dashboard view is stale).
    """
    from ..parser.models import ParseOptions
    from ..parser.parse import parse_spec
    from ..sync.ticket_ref import qualify

    raw = None
    if content_cache_store is not None:
        try:
            raw = await content_cache_store.get_spec_raw(f"{owner}/{repo}", file_path)
        except Exception:
            logger.warning(
                "Cache read failed for %s/%s/%s — falling back to GitHub",
                owner,
                repo,
                file_path,
                exc_info=True,
            )
    if raw is None:
        content, _ = await client.get_file_content(owner, repo, file_path)
        raw = content

    parsed = parse_spec(raw, ParseOptions(file_path=file_path))
    # Accept either the slug id (e.g. "1-has-broken-ticket") or the bare
    # section_number (e.g. "1") — different call sites use different forms.
    target = next(
        (
            s
            for s in flatten_sections(parsed.document.sections)
            if s.id == section_id or s.section_number == section_id
        ),
        None,
    )
    if target is None:
        raise SectionNotFoundError(
            f"section_id={section_id} not found in {owner}/{repo}/{file_path}"
        )
    if target.ticket_link is None:
        raise SectionAlreadyUpdatedError(
            f"section_id={section_id} no longer has a ticket_link; dashboard view is stale"
        )

    # Strip the ticket comment line within the section's range.
    # Parser uses 1-indexed inclusive [start_line, end_line].
    lines = raw.splitlines(keepends=True)
    # Match the SPECIFIC ticket_link's comment, not any canon:ticket comment
    # in the range. Sections with multiple ticket comments are rare but
    # nothing in the parser prevents them — being precise here avoids
    # silently stripping the wrong line.
    ticket_marker = f"<!-- canon:ticket:{target.ticket_link.system}:{target.ticket_link.ticket_id}"
    new_lines: list[str] = []
    removed = False
    for idx, line in enumerate(lines, start=1):
        if not removed and target.start_line <= idx <= target.end_line and ticket_marker in line:
            removed = True
            continue
        new_lines.append(line)
    if not removed:
        raise SectionAlreadyUpdatedError(
            f"section_id={section_id} ticket comment not found in section range"
        )
    new_content = "".join(new_lines)

    # Qualified ticket_ref of the line we just stripped — passed back so
    # callers (i.e. the route layer) can auto-dismiss the matching row in
    # ticket_ref_status without re-deriving it from spec metadata.
    qualified_ref = qualify(
        target.ticket_link.system,
        f"{owner}/{repo}",
        target.ticket_link.ticket_id,
    )

    # Deterministic branch name = idempotent re-runs.
    branch = f"canon-bot/remove-ref-{section_id}"
    existing = await client.find_open_doc_pr(owner, repo, branch)
    if existing is not None:
        return RemoveTicketRefResult(
            pr_number=existing.pr_number,
            pr_url=existing.pr_url,
            already_existed=True,
            system=target.ticket_link.system,
            ticket_ref=qualified_ref,
        )

    pr = await client.create_doc_pr(
        owner,
        repo,
        branch=branch,
        title=f"Remove broken ticket reference from {file_path}",
        body=(
            "The Canon dashboard flagged this ticket reference as persistently broken "
            "(404/401/403 from the ticket system on multiple consecutive sync runs). "
            "This PR removes the dead reference so the cron stops re-checking it. "
            "If the ticket should be replaced rather than removed, close this PR and "
            "edit the spec directly."
        ),
        files=[FileChange(path=file_path, content=new_content)],
        commit_message=f"chore(canon): remove broken ticket reference from {file_path}",
    )
    return RemoveTicketRefResult(
        pr_number=pr.pr_number,
        pr_url=pr.pr_url,
        system=target.ticket_link.system,
        ticket_ref=qualified_ref,
    )
