"""MCP server factory — creates a FastMCP instance with spec tools."""

from __future__ import annotations

import logging
import re as _re
import time
from contextlib import asynccontextmanager
from datetime import UTC
from pathlib import Path
from typing import Any

import frontmatter as fm_lib
from mcp.server.fastmcp import Context, FastMCP

from canon import analytics
from canon.parser.models import AiExposure, resolve_ai_exposure

from .deps import McpDeps

logger = logging.getLogger(__name__)

MAX_BODY_SNIPPET = 500
MAX_RELATED_SPECS = 100

# TTL cache for ai_exposure config to avoid repeated GitHub API calls per tool invocation.
# Keyed by (owner, repo), values are (timestamp, (default, restricted_tags)).
_AI_EXPOSURE_CACHE: dict[tuple[str, str], tuple[float, tuple[str, list[str]]]] = {}
_AI_EXPOSURE_CACHE_TTL = 60  # seconds


def _get_deps(ctx: Context) -> McpDeps:
    """Extract McpDeps from the MCP context's lifespan context."""
    return ctx.request_context.lifespan_context["deps"]


def _section_to_dict(
    section: Any, include_content: bool = True, metadata_only: bool = False
) -> dict:
    """Convert a SpecSection to a plain dict for JSON serialization.

    NOTE: This manually mirrors SpecSection/Scenario/ScenarioStep/AcceptanceCriterion
    fields. If new fields are added to those models, update this function to match.

    When metadata_only=True, section content and AC text are redacted (ai_exposure: metadata).
    """
    d: dict[str, Any] = {
        "id": section.id,
        "section_number": section.section_number,
        "title": section.title,
        "depth": section.depth,
        "status": section.status.state,
    }
    if section.ticket_link:
        d["ticket_link"] = {
            "system": section.ticket_link.system,
            "ticket_id": section.ticket_link.ticket_id,
        }
    if section.delta:
        d["delta"] = section.delta
    if metadata_only:
        # Redact content for metadata-only exposure
        if section.acceptance_criteria:
            d["acceptance_criteria_count"] = len(section.acceptance_criteria)
            d["acceptance_criteria_checked"] = sum(
                1 for ac in section.acceptance_criteria if ac.checked
            )
    else:
        if include_content:
            d["content"] = section.content
        if section.acceptance_criteria:
            d["acceptance_criteria"] = [
                {
                    "text": ac.text,
                    "checked": ac.checked,
                    **({"strength": ac.strength} if ac.strength else {}),
                }
                for ac in section.acceptance_criteria
            ]
        if section.scenarios:
            d["scenarios"] = [
                {
                    "name": sc.name,
                    "steps": [
                        {
                            "keyword": step.keyword,
                            "text": step.text,
                            **({"strength": step.strength} if step.strength else {}),
                        }
                        for step in sc.steps
                    ],
                }
                for sc in section.scenarios
            ]
    if section.children:
        d["children"] = [
            _section_to_dict(child, include_content=include_content, metadata_only=metadata_only)
            for child in section.children
        ]
    return d


VALID_SECTION_STATES = {"draft", "todo", "in_progress", "done", "blocked", "deprecated"}


def _find_section(sections: list, target_id: str) -> Any | None:
    """Search all sections (including children) for matching ID."""
    for s in sections:
        if s.id == target_id:
            return s
        found = _find_section(s.children, target_id)
        if found:
            return found
    return None


async def _get_ai_exposure_config(d: McpDeps, owner: str, repo: str) -> tuple[str, list[str]]:
    """Get the ai_exposure default and restricted_tags from CANON.yaml.

    Returns (default, restricted_tags).  Fails closed to "metadata" on error
    so that a transient config-load failure never silently bypasses restrictions.
    Results are cached for 60s to avoid repeated GitHub API calls per tool invocation.
    """
    key = (owner, repo)
    cached = _AI_EXPOSURE_CACHE.get(key)
    if cached is not None:
        ts, value = cached
        if time.monotonic() - ts < _AI_EXPOSURE_CACHE_TTL:
            return value

    try:
        from ..github.spec_utils import load_repo_config

        config = await load_repo_config(d.github_client, owner, repo)
        result = config.ide.ai_exposure.default, config.ide.ai_exposure.restricted_tags
    except Exception:
        logger.warning(
            "Failed to load ai_exposure config for %s/%s, failing closed to 'metadata'",
            owner,
            repo,
            exc_info=True,
        )
        result = "metadata", []

    _AI_EXPOSURE_CACHE[key] = (time.monotonic(), result)
    return result


def _resolve_exposure(
    frontmatter: Any,
    config_default: str = "full",
    restricted_tags: list[str] | None = None,
) -> AiExposure:
    """Resolve effective ai_exposure for a spec frontmatter."""
    cd: AiExposure | None = (
        config_default if config_default in ("full", "metadata", "none") else None
    )
    return resolve_ai_exposure(frontmatter, restricted_tags, cd)


def _resolve_related_exposure(
    related: Any,
    config_default: str,
    restricted_tags: list[str],
) -> AiExposure:
    """Resolve ai_exposure for a RelatedSpec without re-parsing its frontmatter.

    Mirrors :func:`canon.parser.models.resolve_ai_exposure` on the slim
    metadata that ``RelatedSpec`` carries (``ai_exposure`` override and
    ``tags`` for restricted-tag matching). Used by ``find_related_specs``
    so a spec with ``ai_exposure: none`` in its own frontmatter can be
    filtered out of neighbour lists, even when its repo default is "full".
    """
    override = getattr(related, "ai_exposure", "")
    if override in ("full", "metadata", "none"):
        return override  # type: ignore[return-value]
    tags = getattr(related, "tags", []) or []
    if restricted_tags and any(t in restricted_tags for t in tags):
        return "metadata"
    if config_default in ("full", "metadata", "none"):
        return config_default  # type: ignore[return-value]
    return "full"


def create_mcp_server(deps: McpDeps) -> FastMCP:
    """Create a FastMCP server with spec tools wired to the given dependencies."""

    @asynccontextmanager
    async def lifespan(server: FastMCP):
        yield {"deps": deps}

    mcp = FastMCP(
        "Canon",
        instructions=(
            "Canon gives you access to your organization's spec documents "
            "and markdown knowledge base. Use 'search' to find relevant specs, "
            "'get_spec' to read a full spec, and 'get_doc' for raw markdown."
        ),
        lifespan=lifespan,
    )

    # ─── Tool: search ────────────────────────────────────

    @mcp.tool(
        name="search",
        description=(
            "Search the spec knowledge base using hybrid search (vector + BM25). "
            "Returns matching sections with repo, path, title, heading, body snippet, "
            "status, and relevance score. Use this to find specs related to what "
            "you're working on."
        ),
    )
    async def search(
        query: str,
        repo: str | None = None,
        status: str | None = None,
        limit: int = 10,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> list[dict] | dict:
        _org = repo.split("/")[0] if repo and "/" in repo else ""
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "search", "repo": repo or ""},
            groups={"organization": _org} if _org else None,
        )
        d = _get_deps(ctx)
        backend = d.search_backend or d.search_index
        if backend is None:
            return {"error": "Search index not available"}

        # Embed query if possible
        query_embedding = None
        if d.embed_client and d.embed_client.is_available:
            try:
                query_embedding = d.embed_client.embed_query(query)
            except Exception:
                # Silent text-only mode is exactly the kind of quality
                # regression the parity tooling is meant to detect — flag it.
                logger.warning("Embedding failed, falling back to text-only search", exc_info=True)

        results = await backend.hybrid_search(
            query_embedding=query_embedding,
            query_text=query,
            repo=repo,
            status=status,
            limit=limit,
        )

        # Apply ai_exposure config-level filtering.
        # Per-spec frontmatter restrictions are enforced at get_spec/get_section
        # access time; here we apply repo-level defaults (e.g. default: "none").
        config_cache: dict[str, tuple[str, list[str]]] = {}
        filtered: list[dict] = []
        for r in results:
            owner_repo = r.repo
            if owner_repo not in config_cache:
                if d.github_client and "/" in owner_repo:
                    o, rp = owner_repo.split("/", 1)
                    config_cache[owner_repo] = await _get_ai_exposure_config(d, o, rp)
                else:
                    config_cache[owner_repo] = ("full", [])
            config_default, _restricted = config_cache[owner_repo]
            if config_default == "none":
                continue  # Repo-level default hides all specs from search
            entry: dict[str, Any] = {
                "repo": r.repo,
                "path": r.path,
                "title": r.doc_title,
                "heading": r.heading,
                "status": r.status,
                "score": round(r.rrf_score, 4),
            }
            if config_default != "metadata":
                entry["body"] = r.body[:MAX_BODY_SNIPPET] if r.body else ""
                if r.highlights:
                    entry["highlights"] = r.highlights
            filtered.append(entry)
        return filtered

    # ─── Tool: find_related_specs ──────────────────────────

    @mcp.tool(
        name="find_related_specs",
        description=(
            "Find specs semantically similar to a given spec, using kNN over "
            "spec embeddings. Returns up to ``limit`` related specs (repo, path, "
            "title) ordered most-similar first. Useful for cross-spec navigation "
            "when a single search query doesn't capture the relationship. "
            "Returns an error if the source spec doesn't exist."
        ),
    )
    async def find_related_specs(
        owner: str,
        repo: str,
        file_path: str,
        limit: int = 10,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> list[dict] | dict:
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "find_related_specs", "repo": f"{owner}/{repo}"},
            groups={"organization": owner},
        )
        d = _get_deps(ctx)
        backend = d.search_backend or d.search_index
        if backend is None or not hasattr(backend, "get_related"):
            return {"error": "Search backend does not support related specs"}
        if d.content_cache_store is None:
            # Without the cache we can't honour the documented "spec not found"
            # contract — a missing spec would silently return [] from kNN,
            # which the AI client would misread as "no related specs".
            return {"error": "Related-spec lookup unavailable: cache store not configured"}

        # Cap limit — kNN scans are far more expensive than text search; an
        # unbounded value (or one tracked back from a misbehaving caller)
        # would trigger a full pgvector scan or expensive ANN sweep.
        limit = max(1, min(limit, MAX_RELATED_SPECS))

        full_repo = f"{owner}/{repo}"

        # Distinguish "spec not found" (caller error), "lookup failed"
        # (infrastructure error), and "no neighbours" (genuine empty result)
        # so the AI client gets actionable feedback for each.
        try:
            source = await d.content_cache_store.get_spec(full_repo, file_path)
        except Exception:
            logger.warning(
                "content_cache lookup failed during find_related_specs",
                exc_info=True,
            )
            return {"error": f"Spec lookup failed: {full_repo}:{file_path}"}
        if source is None:
            return {"error": f"Spec not found: {full_repo}:{file_path}"}

        # Verify the SOURCE spec is exposed to AI tooling. Without this gate,
        # an AI client that knows the path of an `ai_exposure: none` spec
        # could still use it as a kNN pivot and learn the spec's semantic
        # neighbourhood (titles + paths) — same leak `get_spec` blocks.
        source_raw = source.get("raw_markdown")
        if not source_raw:
            return {"error": f"Spec {file_path} is not available (no content)"}
        import yaml

        from ..parser.models import ParseOptions
        from ..parser.parse import parse_spec

        try:
            source_doc = parse_spec(source_raw, ParseOptions(file_path=file_path)).document
        except (yaml.YAMLError, ValueError) as exc:
            # Narrow to parser-domain exceptions: malformed YAML / frontmatter
            # validation failures. Programming errors (TypeError, KeyError,
            # AttributeError from a refactored field) propagate so Sentry
            # surfaces them — the previous broader catch reported them as a
            # benign "parse failed" with no operator signal.
            logger.warning(
                "Failed to parse source spec for ai_exposure check: %s:%s (%s)",
                full_repo,
                file_path,
                exc,
            )
            return {"error": f"Spec {file_path} is not available (parse failed)"}
        # Guard the source-exposure loader the same way the per-result loop
        # does: when no GitHub client is wired (tests/CLI), default to "full"
        # exposure rather than firing a fail-closed-to-metadata warning per
        # call. The source spec's frontmatter `restricted_tags` are still
        # resolved against an empty restricted list — same parity with the
        # default-no-client behaviour.
        if d.github_client and "/" in full_repo:
            source_default, source_restricted = await _get_ai_exposure_config(d, owner, repo)
        else:
            source_default, source_restricted = ("full", [])
        source_exposure = _resolve_exposure(
            source_doc.frontmatter, source_default, source_restricted
        )
        if source_exposure == "none":
            return {"error": f"Spec {file_path} is not available (ai_exposure: none)"}

        related = await backend.get_related(repo=full_repo, path=file_path, limit=limit)

        # Apply ai_exposure filtering on each result, using the same
        # resolution order as `_resolve_exposure`/`get_spec`:
        # frontmatter override > restricted_tags match > repo default.
        # Without per-spec checking, a spec with `ai_exposure: none` in
        # its OWN frontmatter — in a repo whose default is "full" —
        # would leak its title and path through the neighbour list.
        config_cache: dict[str, tuple[str, list[str]]] = {}
        filtered: list[dict] = []
        for r in related:
            if r.repo not in config_cache:
                if d.github_client and "/" in r.repo:
                    o, rp = r.repo.split("/", 1)
                    config_cache[r.repo] = await _get_ai_exposure_config(d, o, rp)
                else:
                    config_cache[r.repo] = ("full", [])
            config_default, restricted = config_cache[r.repo]
            exposure = _resolve_related_exposure(r, config_default, restricted)
            if exposure == "none":
                continue
            filtered.append({"repo": r.repo, "path": r.path, "title": r.title})
        return filtered

    # ─── Tool: get_spec ──────────────────────────────────

    @mcp.tool(
        name="get_spec",
        description=(
            "Get a full parsed spec document with frontmatter, sections, "
            "acceptance criteria, and status. Returns structured data. "
            "Use summary_only=true for lightweight metadata (frontmatter + section titles/status/AC counts). "
            "Use status_filter to include only top-level sections with specific statuses "
            "(children of matching sections are always included)."
        ),
    )
    async def get_spec(
        owner: str,
        repo: str,
        file_path: str,
        summary_only: bool = False,
        status_filter: list[str] | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "get_spec", "repo": f"{owner}/{repo}"},
            groups={"organization": owner},
        )
        d = _get_deps(ctx)
        if d.github_client is None:
            return {"error": "GitHub client not available"}

        from ..parser.models import ParseOptions
        from ..parser.parse import parse_spec

        # Try content cache first, fall back to GitHub
        content: str | None = None
        if d.content_cache_store is not None:
            try:
                content = await d.content_cache_store.get_spec_raw(f"{owner}/{repo}", file_path)
            except Exception:
                logger.debug("Content cache miss for get_spec %s/%s/%s", owner, repo, file_path)

        if content is None:
            try:
                content, _sha = await d.github_client.get_file_content(owner, repo, file_path)
            except Exception:
                return {"error": f"File not found: {owner}/{repo}/{file_path}"}

        result = parse_spec(content, ParseOptions(file_path=file_path))
        doc = result.document

        # Check ai_exposure
        config_default, restricted_tags = await _get_ai_exposure_config(d, owner, repo)
        exposure = _resolve_exposure(doc.frontmatter, config_default, restricted_tags)
        if exposure == "none":
            return {"error": f"Spec {file_path} is not available (ai_exposure: none)"}

        metadata_only = exposure == "metadata"

        fm = doc.frontmatter
        fm_dict: dict[str, Any] = {
            "title": fm.title,
            "status": fm.status,
            "owner": fm.owner,
            "team": fm.team,
            "tags": fm.tags,
            "doc_type": fm.doc_type,
            "depends_on": fm.depends_on,
            "ai_exposure": exposure,
        }
        if fm.review_status:
            fm_dict["review_status"] = fm.review_status
        if fm.supersedes:
            fm_dict["supersedes"] = fm.supersedes

        # Build sections list with filtering
        use_metadata_only = metadata_only or summary_only
        sections = doc.sections
        if status_filter:
            invalid = [s for s in status_filter if s not in VALID_SECTION_STATES]
            if invalid:
                return {
                    "error": (
                        f"Invalid status_filter values: {invalid}. "
                        f"Must be one of {sorted(VALID_SECTION_STATES)}"
                    )
                }
            filter_set = set(status_filter)
            sections = [s for s in sections if s.status.state in filter_set]

        return {
            "file_path": doc.file_path,
            "frontmatter": fm_dict,
            "sections": [_section_to_dict(s, metadata_only=use_metadata_only) for s in sections],
        }

    # ─── Tool: get_section ───────────────────────────────

    @mcp.tool(
        name="get_section",
        description=(
            "Get a single section from a spec by its ID. "
            "Returns the section with content, acceptance criteria, and ticket link."
        ),
    )
    async def get_section(
        owner: str,
        repo: str,
        file_path: str,
        section_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "get_section", "repo": f"{owner}/{repo}"},
            groups={"organization": owner},
        )
        d = _get_deps(ctx)
        if d.github_client is None:
            return {"error": "GitHub client not available"}

        from ..parser.models import ParseOptions
        from ..parser.parse import parse_spec

        # Try content cache first, fall back to GitHub
        content: str | None = None
        if d.content_cache_store is not None:
            try:
                content = await d.content_cache_store.get_spec_raw(f"{owner}/{repo}", file_path)
            except Exception:
                logger.debug("Content cache miss for get_section %s/%s/%s", owner, repo, file_path)

        if content is None:
            try:
                content, _sha = await d.github_client.get_file_content(owner, repo, file_path)
            except Exception:
                return {"error": f"File not found: {owner}/{repo}/{file_path}"}

        result = parse_spec(content, ParseOptions(file_path=file_path))

        # Check ai_exposure
        config_default, restricted_tags = await _get_ai_exposure_config(d, owner, repo)
        exposure = _resolve_exposure(result.document.frontmatter, config_default, restricted_tags)
        if exposure == "none":
            return {"error": f"Spec {file_path} is not available (ai_exposure: none)"}

        section = _find_section(result.document.sections, section_id)
        if section is None:
            return {"error": f"Section not found: {section_id}"}

        return _section_to_dict(section, metadata_only=(exposure == "metadata"))

    # ─── Tool: get_doc ───────────────────────────────────

    @mcp.tool(
        name="get_doc",
        description=(
            "Get raw markdown content of any document from a repository. "
            "Use this when you need the unprocessed markdown."
        ),
    )
    async def get_doc(
        owner: str,
        repo: str,
        file_path: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "get_doc", "repo": f"{owner}/{repo}"},
            groups={"organization": owner},
        )
        d = _get_deps(ctx)
        if d.github_client is None:
            return {"error": "GitHub client not available"}

        # Try content cache first, fall back to GitHub
        content: str | None = None
        if d.content_cache_store is not None:
            try:
                content = await d.content_cache_store.get_spec_raw(f"{owner}/{repo}", file_path)
            except Exception:
                logger.debug("Content cache miss for get_doc %s/%s/%s", owner, repo, file_path)

        if content is None:
            try:
                content, _sha = await d.github_client.get_file_content(owner, repo, file_path)
            except Exception:
                return {"error": f"File not found: {owner}/{repo}/{file_path}"}

        # Check ai_exposure for spec files — parse errors are caught narrowly,
        # but security checks must not be swallowed by a catch-all.
        if file_path.endswith(".md"):
            parsed_frontmatter = None
            try:
                from ..parser.models import ParseOptions
                from ..parser.parse import parse_spec

                result = parse_spec(content, ParseOptions(file_path=file_path))
                parsed_frontmatter = result.document.frontmatter
            except Exception:
                pass  # Not a valid spec file — serve raw content

            if parsed_frontmatter is not None:
                config_default, restricted_tags = await _get_ai_exposure_config(d, owner, repo)
                exposure = _resolve_exposure(parsed_frontmatter, config_default, restricted_tags)
                if exposure == "none":
                    return {"error": f"Document {file_path} is not available (ai_exposure: none)"}
                if exposure == "metadata":
                    return {
                        "error": (
                            f"Document {file_path} content is restricted "
                            f"(ai_exposure: metadata). Use get_spec for metadata."
                        )
                    }

        return {"owner": owner, "repo": repo, "path": file_path, "content": content}

    # ─── Tool: list_specs ────────────────────────────────

    @mcp.tool(
        name="list_specs",
        description=(
            "List all spec documents in a repository (using configured doc_paths). "
            "Returns metadata (title, status, owner) without full content. "
            "Supports pagination with page and per_page parameters."
        ),
    )
    async def list_specs(
        owner: str,
        repo: str,
        page: int = 1,
        per_page: int = 50,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "list_specs", "repo": f"{owner}/{repo}"},
            groups={"organization": owner},
        )
        d = _get_deps(ctx)
        if d.github_client is None:
            return {"error": "GitHub client not available"}

        if page < 1:
            return {"error": "page must be >= 1"}
        if per_page < 1 or per_page > 200:
            return {"error": "per_page must be between 1 and 200"}

        from ..github.spec_utils import load_repo_config, load_repo_specs
        from ..parser.models import ParseOptions
        from ..parser.parse import parse_spec

        config = await load_repo_config(d.github_client, owner, repo)
        config_default = config.ide.ai_exposure.default
        restricted_tags = config.ide.ai_exposure.restricted_tags

        # Try content cache first, fall back to GitHub
        specs: list[dict] | None = None
        if d.content_cache_store is not None:
            try:
                full_repo = f"{owner}/{repo}"
                cached_list = await d.content_cache_store.list_specs_with_content(full_repo)
                if cached_list:
                    specs = []
                    for spec_meta in cached_list:
                        raw = spec_meta.get("raw_markdown")
                        if raw is None:
                            continue
                        result = parse_spec(raw, ParseOptions(file_path=spec_meta["path"]))
                        specs.append({"file_path": spec_meta["path"], "document": result.document})
            except Exception:
                logger.debug("Content cache miss for list_specs %s/%s", owner, repo)
                specs = None

        if specs is None:
            specs = await load_repo_specs(
                d.github_client, owner, repo, patterns=config.specs.doc_paths
            )

        result_list: list[dict] = []
        for s in specs:
            fm = s["document"].frontmatter
            exposure = _resolve_exposure(fm, config_default, restricted_tags)
            if exposure == "none":
                continue  # Omit none specs entirely
            entry: dict[str, Any] = {
                "file_path": s["file_path"],
                "title": fm.title,
                "status": fm.status,
                "owner": fm.owner,
                "team": fm.team,
                "tags": fm.tags,
                "section_count": len(s["document"].sections),
                "ai_exposure": exposure,
            }
            result_list.append(entry)

        # Paginate — note: all specs are loaded before slicing.
        # Fine for typical repo sizes; consider server-side pagination for 100+ specs.
        total = len(result_list)
        start = (page - 1) * per_page
        end = start + per_page
        paginated = result_list[start:end]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "specs": paginated,
        }

    # ─── Tool: list_docs ─────────────────────────────────

    @mcp.tool(
        name="list_docs",
        description=(
            "List all indexed document paths in the knowledge base. "
            "Optionally filter by repository (e.g. 'owner/repo')."
        ),
    )
    async def list_docs(
        repo: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> list[dict] | dict:
        _org = repo.split("/")[0] if repo and "/" in repo else ""
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "list_docs", "repo": repo or ""},
            groups={"organization": _org} if _org else None,
        )
        d = _get_deps(ctx)
        backend = d.search_backend or d.search_index
        if backend is None:
            return {"error": "Search index not available"}

        paths = await backend.get_indexed_paths(repo=repo)

        return [
            {
                "key": key,
                "indexed_at": str(info["indexed_at"]),
                "has_embedding": info["has_embedding"],
            }
            for key, info in paths.items()
        ]

    # ─── Tool: get_coverage ────────────────────────────

    @mcp.tool(
        name="get_coverage",
        description=(
            "Get spec coverage metrics for the organization. Returns aggregate "
            "coverage summary (total specs, sections, ACs, realization rate, "
            "health score) and a time-series trend. Optionally filter by "
            "repository or team."
        ),
    )
    async def get_coverage_tool(
        repo: str | None = None,
        team: str | None = None,
        days: int = 30,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        _org = repo.split("/")[0] if repo and "/" in repo else ""
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "get_coverage", "repo": repo or ""},
            groups={"organization": _org} if _org else None,
        )
        d = _get_deps(ctx)

        if d.github_client is None and d.agent_store is None:
            return {"error": "Coverage data not available (no GitHub client or database)"}

        try:
            from ..web.cache import TTLCache
            from ..web.services import get_coverage
        except ImportError:
            return {"error": "Coverage tools not available (cloud dependencies not installed)"}

        cache = d.cache or TTLCache(ttl_seconds=300)
        result = await get_coverage(
            d.github_client,
            d.settings.web_org if d.settings else "",
            cache,
            repo=repo or "",
            team=team or "",
            days=days,
            agent_store=d.agent_store,
        )
        return result.model_dump()

    # ─── Tool: create_spec ────────────────────────────────

    @mcp.tool(
        name="create_spec",
        description=(
            "Create a new spec document in a repository from a template. "
            "Commits the file directly to the default branch."
        ),
    )
    async def create_spec(
        owner: str,
        repo: str,
        title: str,
        doc_type: str = "spec",
        team: str = "",
        owner_name: str = "",
        tags: list[str] | None = None,
        file_name: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "create_spec", "repo": f"{owner}/{repo}"},
            groups={"organization": owner},
        )
        d = _get_deps(ctx)
        if d.github_client is None:
            return {"error": "GitHub client not available"}

        from ..parser.templates import get_template

        try:
            template = get_template(doc_type)
        except ValueError as e:
            return {"error": str(e)}

        post = fm_lib.loads(template)
        post.metadata["title"] = title
        if team:
            post.metadata["team"] = team
        if owner_name:
            post.metadata["owner"] = owner_name
        if tags:
            post.metadata["tags"] = tags

        # Replace the placeholder heading with the actual title
        content = fm_lib.dumps(post)
        # Templates use "# Untitled <Type>" headings — replace generically
        content = _re.sub(r"^# Untitled \w+", f"# {title}", content, count=1, flags=_re.MULTILINE)

        # Build file path — sanitize both caller-provided and derived slugs
        def _sanitize_slug(raw: str) -> str:
            s = raw.lower().replace(" ", "-")
            s = "".join(c for c in s if c.isalnum() or c == "-")
            return _re.sub(r"-+", "-", s).strip("-")

        slug = _sanitize_slug(file_name) if file_name else _sanitize_slug(title)
        if not slug:
            return {"error": f"Cannot derive a valid filename from title: {title!r}"}

        # Use configurable spec directory from CANON.yaml
        from ..github.spec_utils import extract_directories
        from ..github.spec_utils import load_repo_config as _load_cfg

        cfg = await _load_cfg(d.github_client, owner, repo)
        dirs = extract_directories(cfg.specs.doc_paths)
        spec_dir = dirs[0][0] if dirs else "docs/specs"
        path = f"{spec_dir}/{slug}.md"

        try:
            result = await d.github_client.create_or_update_file(
                owner,
                repo,
                path,
                content,
                f"docs: create spec — {title}",
            )

            # Write-through: update content cache (parses sections properly)
            if d.content_cache_store is not None:
                try:
                    from ..sync.content_sync import ContentSyncEngine

                    engine = ContentSyncEngine(d.content_cache_store, d.github_client)
                    await engine.sync_spec(
                        owner,
                        repo,
                        path,
                        content,
                        commit_sha=result.get("content", {}).get("sha", ""),
                    )
                except Exception:
                    logger.debug("Failed to update content cache for create_spec %s", path)

            return {
                "path": path,
                "sha": result.get("content", {}).get("sha", ""),
                "message": f"Created spec: {path}",
            }
        except Exception as e:
            return {"error": f"Failed to create spec: {e}"}

    # ─── Tool: update_section_status ──────────────────────

    @mcp.tool(
        name="update_section_status",
        description=(
            "Update the status of a spec section. Modifies the status comment "
            "in-place or inserts one if missing, then commits the change."
        ),
    )
    async def update_section_status(
        owner: str,
        repo: str,
        file_path: str,
        section_id: str,
        new_state: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "update_section_status", "repo": f"{owner}/{repo}"},
            groups={"organization": owner},
        )
        d = _get_deps(ctx)
        if d.github_client is None:
            return {"error": "GitHub client not available"}

        if new_state not in VALID_SECTION_STATES:
            return {
                "error": f"Invalid state: {new_state}. Must be one of {sorted(VALID_SECTION_STATES)}"
            }

        from ..parser.models import ParseOptions
        from ..parser.parse import parse_spec
        from ..parser.writer import (
            StatusUpdate,
            insert_status_comment,
            update_status_comments,
        )

        try:
            content, sha = await d.github_client.get_file_content(owner, repo, file_path)
        except Exception:
            return {"error": f"File not found: {owner}/{repo}/{file_path}"}

        result = parse_spec(content, ParseOptions(file_path=file_path))
        section = _find_section(result.document.sections, section_id)
        if section is None:
            return {"error": f"Section not found: {section_id}"}

        # Try in-place update first
        updated = update_status_comments(
            result.document,
            [StatusUpdate(section_number=section.section_number, new_state=new_state)],
        )

        # If nothing changed, insert a new status comment
        if updated == content:
            updated = insert_status_comment(
                content, section.start_line, section.section_number, new_state
            )

        try:
            commit_result = await d.github_client.create_or_update_file(
                owner,
                repo,
                file_path,
                updated,
                f"docs: update {section.title} status to {new_state}",
                sha=sha,
            )

            # Write-through: update content cache (parses sections properly)
            if d.content_cache_store is not None:
                try:
                    from ..sync.content_sync import ContentSyncEngine

                    engine = ContentSyncEngine(d.content_cache_store, d.github_client)
                    await engine.sync_spec(
                        owner,
                        repo,
                        file_path,
                        updated,
                        commit_sha=commit_result.get("content", {}).get("sha", ""),
                    )
                except Exception:
                    logger.debug(
                        "Failed to update content cache for update_section_status %s",
                        file_path,
                    )

            return {
                "section_id": section_id,
                "new_state": new_state,
                "message": f"Updated section '{section.title}' to {new_state}",
            }
        except Exception as e:
            return {"error": f"Failed to commit: {e}"}

    # ─── Tool: add_realization ───────────────────────────

    @mcp.tool(
        name="add_realization",
        description=(
            "Add realization evidence to a spec section's acceptance criterion. "
            "Links a PR and code location to an AC checkbox."
        ),
    )
    async def add_realization(
        owner: str,
        repo: str,
        file_path: str,
        section_id: str,
        ac_text: str,
        pr_number: int,
        code_file: str,
        lines: str = "",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "add_realization", "repo": f"{owner}/{repo}"},
            groups={"organization": owner},
        )
        d = _get_deps(ctx)
        if d.github_client is None:
            return {"error": "GitHub client not available"}

        from ..parser.models import ParseOptions
        from ..parser.parse import parse_spec
        from ..parser.writer import RealizationInsertion, insert_realization_comments

        try:
            content, sha = await d.github_client.get_file_content(owner, repo, file_path)
        except Exception:
            return {"error": f"File not found: {owner}/{repo}/{file_path}"}

        result = parse_spec(content, ParseOptions(file_path=file_path))
        section = _find_section(result.document.sections, section_id)
        if section is None:
            return {"error": f"Section not found: {section_id}"}

        insertion = RealizationInsertion(
            ac_text=ac_text,
            pr_number=pr_number,
            file_path=code_file,
            lines=lines,
        )

        updated = insert_realization_comments(result.document, [insertion])

        if updated == content:
            return {"error": f"AC not found in section: {ac_text}"}

        try:
            commit_result = await d.github_client.create_or_update_file(
                owner,
                repo,
                file_path,
                updated,
                f"docs: add realization for PR#{pr_number} in {section.title}",
                sha=sha,
            )

            # Write-through: update content cache (parses sections properly)
            if d.content_cache_store is not None:
                try:
                    from ..sync.content_sync import ContentSyncEngine

                    engine = ContentSyncEngine(d.content_cache_store, d.github_client)
                    await engine.sync_spec(
                        owner,
                        repo,
                        file_path,
                        updated,
                        commit_sha=commit_result.get("content", {}).get("sha", ""),
                    )
                except Exception:
                    logger.debug(
                        "Failed to update content cache for add_realization %s",
                        file_path,
                    )

            return {
                "section_id": section_id,
                "ac_text": ac_text,
                "pr_number": pr_number,
                "message": f"Added realization evidence for PR#{pr_number}",
            }
        except Exception as e:
            return {"error": f"Failed to commit: {e}"}

    # ─── Tool: sync_spec_status ──────────────────────────

    @mcp.tool(
        name="sync_spec_status",
        description=(
            "Bulk update a spec: apply multiple status updates and realizations "
            "in a single commit. More efficient than individual calls."
        ),
    )
    async def sync_spec_status(
        owner: str,
        repo: str,
        file_path: str,
        status_updates: list[dict] | None = None,
        realizations: list[dict] | None = None,
        commit_message: str = "",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        analytics.track(
            "mcp_tool_called",
            properties={"tool": "sync_spec_status", "repo": f"{owner}/{repo}"},
            groups={"organization": owner},
        )
        d = _get_deps(ctx)
        if d.github_client is None:
            return {"error": "GitHub client not available"}

        from ..parser.models import ParseOptions
        from ..parser.parse import parse_spec
        from ..parser.writer import (
            RealizationInsertion,
            StatusUpdate,
            insert_realization_comments,
            insert_status_comment,
            update_status_comments,
        )

        if not status_updates and not realizations:
            return {"error": "No updates provided"}

        # Validate states upfront
        if status_updates:
            for su in status_updates:
                if su["new_state"] not in VALID_SECTION_STATES:
                    return {
                        "error": f"Invalid state: {su['new_state']}. "
                        f"Must be one of {sorted(VALID_SECTION_STATES)}"
                    }

        try:
            content, sha = await d.github_client.get_file_content(owner, repo, file_path)
        except Exception:
            return {"error": f"File not found: {owner}/{repo}/{file_path}"}

        result = parse_spec(content, ParseOptions(file_path=file_path))
        updated = content
        applied_statuses = 0
        applied_realizations = 0

        # Apply status updates: first try in-place replacement for existing comments
        if status_updates:
            su_list = [
                StatusUpdate(section_number=su["section_number"], new_state=su["new_state"])
                for su in status_updates
            ]
            updated = update_status_comments(result.document, su_list)

            # For sections that didn't have existing status comments,
            # insert new ones. Requires section_id to locate the heading.
            # Re-parse after each insertion so start_line values stay correct.
            for su in status_updates:
                # Already present (either pre-existing or just updated)?
                if f"canon:system:{su['section_number']} status:{su['new_state']}" in updated:
                    continue
                section_id = su.get("section_id", "")
                if not section_id:
                    return {
                        "error": f"section_id required for section {su['section_number']} "
                        f"(no existing status comment to update in-place)"
                    }
                # Re-parse to get accurate line numbers
                fresh = parse_spec(updated, ParseOptions(file_path=file_path))
                section = _find_section(fresh.document.sections, section_id)
                if section:
                    updated = insert_status_comment(
                        updated, section.start_line, su["section_number"], su["new_state"]
                    )

            applied_statuses = len(status_updates)

        # Re-parse after status updates for realization insertion
        if realizations:
            re_result = parse_spec(updated, ParseOptions(file_path=file_path))
            r_list = [
                RealizationInsertion(
                    ac_text=r["ac_text"],
                    pr_number=r["pr_number"],
                    file_path=r["code_file"],
                    lines=r.get("lines", ""),
                )
                for r in realizations
            ]
            updated = insert_realization_comments(re_result.document, r_list)
            applied_realizations = len(r_list)

        if updated == content:
            return {"message": "No changes applied — spec already up to date"}

        msg = commit_message or f"docs: sync spec status for {file_path}"
        try:
            commit_result = await d.github_client.create_or_update_file(
                owner, repo, file_path, updated, msg, sha=sha
            )

            # Write-through: update content cache (parses sections properly)
            if d.content_cache_store is not None:
                try:
                    from ..sync.content_sync import ContentSyncEngine

                    engine = ContentSyncEngine(d.content_cache_store, d.github_client)
                    await engine.sync_spec(
                        owner,
                        repo,
                        file_path,
                        updated,
                        commit_sha=commit_result.get("content", {}).get("sha", ""),
                    )
                except Exception:
                    logger.debug(
                        "Failed to update content cache for sync_spec_status %s",
                        file_path,
                    )

            return {
                "applied_statuses": applied_statuses,
                "applied_realizations": applied_realizations,
                "message": f"Synced {file_path}",
            }
        except Exception as e:
            return {"error": f"Failed to commit: {e}"}

    # ─── Tool: record_session_evidence ───────────────────

    @mcp.tool(
        name="record_session_evidence",
        description=(
            "Record dev-session evidence captured by the Canon plugin. "
            "Stores a SessionRecord (spec sections touched, ACs addressed, "
            "files modified, verify gate runs) to the Canon backend so the "
            "GitHub App's PR analyzer can use it as hint input at PR-open time. "
            "See plugin-evidence-pipeline.md §6 for the schema."
        ),
    )
    async def record_session_evidence(
        repo: str,
        branch: str,
        session: dict,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        d = _get_deps(ctx)
        return await _record_session_evidence_impl(d, repo, branch, session)

    # Register extension-provided MCP tools
    _register_extension_tools(mcp)

    return mcp


# ─── Extension tool registration ────────────────────────────────────────


def _register_extension_tools(mcp: FastMCP) -> None:
    """Register MCP tools from installed extensions.

    Discovers extensions with ``provides.mcp_tools`` in their manifests,
    dynamically imports their handlers, and registers them on the MCP server.
    Tool names are namespaced: ``{ext_id}_{tool_name}``.
    """
    import importlib

    from canon.extensions.registry import load_registry

    # Find project root by walking up from this file
    project_root = _find_project_root()
    if project_root is None:
        logger.info("Could not find project root — extension MCP tools will not be registered")
        return

    try:
        registry = load_registry(project_root)
    except (ValueError, OSError) as exc:
        logger.warning("Could not load extension registry for MCP tool discovery: %s", exc)
        return

    for ext_id, entry in registry.extensions.items():
        if not entry.enabled:
            continue

        ext_dir = project_root / ".canon" / "extensions" / ext_id
        try:
            from canon.extensions.manifest import load_manifest

            manifest = load_manifest(ext_dir)
        except Exception:
            logger.warning("Could not load manifest for extension %s", ext_id, exc_info=True)
            continue

        for tool_spec in manifest.provides.mcp_tools:
            tool_name = f"{ext_id}_{tool_spec.name}"
            handler_path = tool_spec.handler
            if not handler_path:
                continue

            try:
                module_path, _, attr_name = handler_path.rpartition(":")
                if not module_path or not attr_name:
                    logger.warning(
                        "Invalid handler path %r for tool %s — expected 'module:callable'",
                        handler_path,
                        tool_name,
                    )
                    continue
                module = importlib.import_module(module_path)
                handler = getattr(module, attr_name)
                if not callable(handler):
                    logger.warning(
                        "Handler %r for tool %s is not callable", handler_path, tool_name
                    )
                    continue
                # Validate handler is async (MCP tools must be async)
                import asyncio

                if not asyncio.iscoroutinefunction(handler):
                    logger.warning(
                        "Handler %r for tool %s is not async — MCP tools must be async functions",
                        handler_path,
                        tool_name,
                    )
                    continue

                mcp.tool(name=tool_name, description=tool_spec.description or "")(handler)
                logger.info("Registered extension MCP tool: %s", tool_name)
            except (ImportError, AttributeError) as exc:
                logger.warning("Failed to register MCP tool %s: %s", tool_name, exc)


def _find_project_root() -> Path | None:
    """Walk up from cwd to find a directory with CANON.yaml."""
    current = Path.cwd()
    for _ in range(10):
        if (current / "CANON.yaml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


# ─── Standalone helpers for testability ──────────────────────────────────


async def _record_session_evidence_impl(
    deps: McpDeps,
    repo: str,
    branch: str,
    session: dict,
) -> dict:
    """Core logic for the record_session_evidence MCP tool.

    Extracted as a standalone helper so tests can call it directly without
    constructing a full MCP Context.

    Security posture (plugin-evidence-pipeline §6 + PR #501 review):
    - Repo-level `ai_exposure: "none"` rejects the insert. The check fails
      CLOSED — a lookup error returns an error to the caller rather than
      silently bypassing the privacy gate.
    - Rate limit (60/hour/repo) fails CLOSED — a counter error returns an
      error rather than silently disabling the limiter.
    - Caller authentication is enforced upstream by the MCP middleware (see
      `src/canon/mcp/auth.py`); this helper trusts the resolved repo string.
    - Repo access is implicitly verified by the CANON.yaml fetch via the
      GitHub App installation (get_file_content will 404 for repos where
      Canon is not installed).
    - KNOWN LIMITATION: per-user repo authorization is not enforced — any
      holder of a valid Canon API key can write evidence for any repo where
      the Canon app is installed. Requires threading org_login from the API
      key record through the MCP auth context. See PR #501 review comment.
    """
    analytics.track(
        "mcp_tool_called",
        properties={"tool": "record_session_evidence", "repo": repo},
        groups={"organization": repo.split("/")[0] if "/" in repo else ""},
    )

    if deps.session_evidence_store is None:
        return {"error": "Session evidence store not available"}

    # Validate the SessionRecord shape via the canonical Pydantic model
    try:
        from ..evidence.models import SessionRecord

        record = SessionRecord.model_validate(session)
    except Exception as err:
        return {"error": f"Invalid session record: {err}"}

    # Respect ai_exposure: if the repo's default is "none", reject.
    # Fail-closed: a lookup failure returns an error rather than silently
    # bypassing the privacy gate. We bypass both `_get_ai_exposure_config`
    # AND `load_repo_config` here because they both fail CLOSED *to a default*
    # (one to "metadata", one to DEFAULT_CONFIG) — which is the right call for
    # the search/read path (worst case: leak metadata for a repo whose config
    # we can't read) but the wrong call for this write path. For evidence
    # ingestion we need to distinguish "config read OK and not none" from
    # "config read failed", so we call the underlying GitHub primitive
    # directly and parse the result ourselves.
    if "/" not in repo:
        return {"error": "Invalid repo format — must be 'owner/repo'"}
    if deps.github_client is None:
        # Can't verify ai_exposure without a GitHub client — fail closed
        return {
            "error": "Evidence rejected: GitHub client not available (cannot verify ai_exposure)"
        }
    owner, repo_name = repo.split("/", 1)
    try:
        from ..config.parse import parse_canon_yaml

        content, _sha = await deps.github_client.get_file_content(owner, repo_name, "CANON.yaml")
        repo_config = parse_canon_yaml(content).config
    except Exception as err:
        logger.warning(
            "ai_exposure lookup failed for %s; rejecting insert: %s",
            repo,
            err,
        )
        return {"error": "Evidence rejected: ai_exposure config unavailable"}
    if repo_config.ide.ai_exposure.default == "none":
        return {"error": "Evidence rejected: repo ai_exposure is 'none'"}

    # Rate limit: max 60 records per hour per repo. Fail-closed: a counter
    # error returns an error rather than silently disabling the limiter.
    from datetime import datetime, timedelta

    try:
        window_start = datetime.now(UTC) - timedelta(hours=1)
        count = await deps.session_evidence_store.count_in_window(repo, since=window_start)
    except Exception as err:
        logger.warning(
            "rate limit check failed for %s; rejecting insert: %s",
            repo,
            err,
        )
        return {"error": "Rate limit check unavailable; try again later"}
    if count >= 60:
        return {"error": "Rate limit exceeded: max 60 records per hour per repo"}

    try:
        row_id = await deps.session_evidence_store.insert(
            repo=repo,
            branch=branch,
            session_id=record.session_id,
            payload=record.model_dump(),
            schema_version=1,
        )
    except Exception as err:
        return {"error": f"Failed to insert session evidence: {err}"}

    return {
        "recorded": row_id is not None,
        "session_id": record.session_id,
        "id": row_id,
    }
