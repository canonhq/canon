"""Editor routes for the Spec Explorer web app."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time

import httpx
import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.responses import StreamingResponse

from canon import analytics

from ..agent.client import ClaudeClient
from ..agent.spec_editor import expand_section_stream, generate_acs_stream, improve_section_stream
from ..agent.spec_generator import RepoContext, generate_spec_stream
from ..auth.deps import require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import Permission
from ..github.user_client import UserGitHubClient
from ..parser.models import ParseOptions, SpecSection
from ..parser.parse import parse_spec
from .cache import TTLCache
from .models import AiEditRequest, EditorParseRequest, EditorSavePRRequest, EditorSaveRequest
from .render import render_spec_html
from .routes import _serve_spa
from .spec_template import new_spec_template

logger = logging.getLogger(__name__)

editor_router = APIRouter(prefix="/app/{org}/editor")

# Module-level Claude client (lazy singleton — reads ANTHROPIC_API_KEY on first use)
_claude_client: ClaudeClient | None = None


def _get_claude_client() -> ClaudeClient:
    global _claude_client
    if _claude_client is None:
        _claude_client = ClaudeClient()
    return _claude_client


# Simple per-user rate limiter for the /generate endpoint.
# NOTE: This is instance-local — resets on pod restart and does not
# coordinate across K8s replicas.  Sufficient as a best-effort guard
# against accidental abuse; a proper distributed limiter (e.g. Redis)
# can be added if multi-replica coordination is needed.
_GENERATE_RATE_MAX = 10  # max requests per window
_GENERATE_RATE_WINDOW = 300  # 5-minute window
_generate_rate: dict[str, tuple[int, float]] = {}


def _check_generate_rate(user_id: str) -> bool:
    """Return True if the user is within the rate limit, False otherwise."""
    now = time.monotonic()

    # Evict expired entries to prevent unbounded memory growth
    expired = [
        k for k, (_, start) in _generate_rate.items() if now - start > _GENERATE_RATE_WINDOW * 2
    ]
    for k in expired:
        del _generate_rate[k]

    count, window_start = _generate_rate.get(user_id, (0, now))
    if now - window_start > _GENERATE_RATE_WINDOW:
        _generate_rate[user_id] = (1, now)
        return True
    if count >= _GENERATE_RATE_MAX:
        return False
    _generate_rate[user_id] = (count + 1, window_start)
    return True


# Cache for repo context fetched during spec generation (5 min TTL)
_repo_context_cache = TTLCache(ttl_seconds=300)


def _validate_file_path(file_path: str) -> bool:
    """Validate that a file path is safe (no traversal, must be .md or CANON.yaml)."""
    if ".." in file_path.split("/"):
        return False
    if file_path in ("CANON.yaml", "SPECWRIGHT.yaml"):
        return True
    return file_path.endswith(".md")


def _get_github_user(request: Request) -> dict | None:
    """Return GitHub user from session, or None."""
    return request.session.get("github_user")


def _user_client(github_user: dict) -> UserGitHubClient:
    """Create a UserGitHubClient from session data."""
    return UserGitHubClient(token=github_user["token"])


def _templates(request: Request):
    """Get Jinja2Templates from the routes module."""
    from .routes import templates

    return templates


def _get_user(request: Request) -> dict | None:
    return request.session.get("user") if hasattr(request, "session") else None


def _analytics_id(request: Request) -> str:
    """Return the PostHog distinct_id for the current session user."""
    user = _get_user(request)
    return user.get("sub", analytics.SERVER_ACTOR) if user else analytics.SERVER_ACTOR


async def _get_all_orgs(request: Request) -> list[str]:
    registry = getattr(request.app.state, "registry", None)
    if registry is not None:
        try:
            orgs = await registry.list_orgs()
            if orgs:
                return orgs
        except Exception:
            pass
    return [request.app.state.settings.web_org]


@editor_router.get("/repos", response_class=JSONResponse)
async def api_editor_repos(
    request: Request,
    org: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """JSON list of repos for the Vue SPA editor."""
    github_user = _get_github_user(request)
    if github_user is None:
        return JSONResponse(content={"error": "Not authenticated with GitHub"}, status_code=401)

    client = _user_client(github_user)
    try:
        repos = await client.list_user_repos()
        org_repos = [r for r in repos if r.get("owner", {}).get("login", "").lower() == org.lower()]
        return JSONResponse(content=org_repos)
    except Exception:
        logger.warning("Failed to list repos for editor", exc_info=True)
        return JSONResponse(content=[])
    finally:
        await client.close()


@editor_router.get("/{owner}/{repo}/{file_path:path}/json", response_class=JSONResponse)
async def api_editor_file(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    file_path: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """JSON file content for the Vue SPA editor."""
    github_user = _get_github_user(request)
    if github_user is None:
        return JSONResponse(content={"error": "Not authenticated with GitHub"}, status_code=401)

    if not _validate_file_path(file_path):
        return JSONResponse(content={"error": "Invalid file path"}, status_code=400)

    client = _user_client(github_user)
    try:
        content, sha = await client.get_file(owner, repo, file_path)
        return JSONResponse(content={"content": content, "sha": sha})
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 403:
            return JSONResponse(content={"error": "Permission denied"}, status_code=403)
        if status == 404:
            return JSONResponse(content={"error": "File not found"}, status_code=404)
        return JSONResponse(content={"error": f"GitHub API error ({status})"}, status_code=status)
    except Exception:
        return JSONResponse(content={"error": "File not found"}, status_code=404)
    finally:
        await client.close()


@editor_router.get("/", response_class=HTMLResponse)
async def editor_index(
    request: Request,
    org: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """List repos and specs available for editing."""
    if spa := await _serve_spa(request, org):
        return spa
    github_user = _get_github_user(request)
    if github_user is None:
        return RedirectResponse(url="/auth/github/login", status_code=302)

    client = _user_client(github_user)
    try:
        repos = await client.list_user_repos()
        # Filter to repos in this org
        org_repos = [r for r in repos if r.get("owner", {}).get("login", "").lower() == org.lower()]
    except Exception:
        logger.warning("Failed to list repos for editor", exc_info=True)
        org_repos = []
    finally:
        await client.close()

    tpl = _templates(request)
    orgs = await _get_all_orgs(request)
    return tpl.TemplateResponse(
        request,
        "editor.html",
        {
            "mode": "list",
            "repos": org_repos,
            "orgs": orgs,
            "current_org": org,
            "user": _get_user(request),
            "github_user": github_user,
        },
    )


@editor_router.get("/{owner}/{repo}/new", response_class=HTMLResponse)
async def editor_new(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """New spec from template."""
    if spa := await _serve_spa(request, org):
        return spa
    github_user = _get_github_user(request)
    if github_user is None:
        return RedirectResponse(url="/auth/github/login", status_code=302)

    user_name = github_user.get("name") or github_user.get("login", "")
    content = new_spec_template(owner=user_name)

    tpl = _templates(request)
    orgs = await _get_all_orgs(request)
    return tpl.TemplateResponse(
        request,
        "editor.html",
        {
            "mode": "new",
            "owner": owner,
            "repo": repo,
            "file_path": "",
            "content": content,
            "sha": "",
            "orgs": orgs,
            "current_org": org,
            "user": _get_user(request),
            "github_user": github_user,
        },
    )


@editor_router.get("/{owner}/{repo}/{file_path:path}", response_class=HTMLResponse)
async def editor_load(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    file_path: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """Load a spec file for editing."""
    if spa := await _serve_spa(request, org):
        return spa
    github_user = _get_github_user(request)
    if github_user is None:
        return RedirectResponse(url="/auth/github/login", status_code=302)

    if not _validate_file_path(file_path):
        return HTMLResponse(content="Invalid file path", status_code=400)

    client = _user_client(github_user)
    try:
        content, sha = await client.get_file(owner, repo, file_path)
    except Exception:
        return HTMLResponse(content="File not found", status_code=404)
    finally:
        await client.close()

    tpl = _templates(request)
    orgs = await _get_all_orgs(request)
    return tpl.TemplateResponse(
        request,
        "editor.html",
        {
            "mode": "edit",
            "owner": owner,
            "repo": repo,
            "file_path": file_path,
            "content": content,
            "sha": sha,
            "orgs": orgs,
            "current_org": org,
            "user": _get_user(request),
            "github_user": github_user,
        },
    )


@editor_router.post("/{owner}/{repo}/{file_path:path}/save", response_class=JSONResponse)
async def editor_save(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    file_path: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
):
    """Save spec via direct commit to default branch."""
    github_user = _get_github_user(request)
    if github_user is None:
        return JSONResponse(content={"error": "Not authenticated with GitHub"}, status_code=401)

    if not _validate_file_path(file_path):
        return JSONResponse(content={"error": "Invalid file path"}, status_code=400)

    body = await request.json()
    save_req = EditorSaveRequest(**body)

    message = save_req.message or f"docs: update {file_path}"

    client = _user_client(github_user)
    try:
        result = await client.create_or_update_file(
            owner, repo, file_path, save_req.content, message, save_req.sha
        )
        new_sha = result.get("content", {}).get("sha", "")

        session_user = _get_user(request)
        analytics.track(
            "spec_saved",
            distinct_id=session_user.get("sub", analytics.SERVER_ACTOR)
            if session_user
            else analytics.SERVER_ACTOR,
            properties={"method": "direct", "repo": f"{owner}/{repo}", "file_path": file_path},
            groups={"organization": org},
        )

        return JSONResponse(content={"ok": True, "sha": new_sha})
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 409:
            # Conflict — fetch the latest version so the frontend can show a diff
            try:
                server_content, server_sha = await client.get_file(owner, repo, file_path)
                return JSONResponse(
                    content={
                        "error": "conflict",
                        "server_content": server_content,
                        "server_sha": server_sha,
                    },
                    status_code=409,
                )
            except Exception:
                return JSONResponse(
                    content={"error": "conflict", "server_content": None, "server_sha": None},
                    status_code=409,
                )
        return JSONResponse(content={"error": str(exc)}, status_code=status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=500)
    finally:
        await client.close()


@editor_router.post("/{owner}/{repo}/{file_path:path}/save-pr", response_class=JSONResponse)
async def editor_save_pr(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    file_path: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
):
    """Save spec via new branch + PR."""
    github_user = _get_github_user(request)
    if github_user is None:
        return JSONResponse(content={"error": "Not authenticated with GitHub"}, status_code=401)

    if not _validate_file_path(file_path):
        return JSONResponse(content={"error": "Invalid file path"}, status_code=400)

    body = await request.json()
    save_req = EditorSavePRRequest(**body)

    branch_name = save_req.branch_name or f"canon/edit-{secrets.token_hex(4)}"
    pr_title = save_req.pr_title or f"docs: update {file_path}"
    pr_body = save_req.pr_body or "Spec update via Canon editor."
    message = save_req.message or pr_title

    client = _user_client(github_user)
    try:
        # Get default branch SHA
        repo_data = await client.get_repo(owner, repo)
        default_branch = repo_data.get("default_branch", "main")
        base_sha = await client.get_branch_sha(owner, repo, default_branch)

        # Create branch
        await client.create_branch(owner, repo, branch_name, base_sha)

        # Commit file to new branch
        await client.create_or_update_file(
            owner, repo, file_path, save_req.content, message, save_req.sha, branch=branch_name
        )

        # Create PR
        pr = await client.create_pull_request(
            owner, repo, pr_title, pr_body, branch_name, default_branch
        )

        session_user = _get_user(request)
        analytics.track(
            "spec_saved",
            distinct_id=session_user.get("sub", analytics.SERVER_ACTOR)
            if session_user
            else analytics.SERVER_ACTOR,
            properties={
                "method": "pr",
                "repo": f"{owner}/{repo}",
                "file_path": file_path,
                "pr_number": pr.get("number"),
            },
            groups={"organization": org},
        )

        return JSONResponse(
            content={
                "ok": True,
                "pr_number": pr.get("number"),
                "pr_url": pr.get("html_url", ""),
            }
        )
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=500)
    finally:
        await client.close()


@editor_router.post("/{owner}/{repo}/preview")
async def editor_preview(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """Render markdown preview — returns JSON or HTMX partial based on Accept header."""
    github_user = _get_github_user(request)
    if github_user is None:
        return JSONResponse(content={"error": "Not authenticated with GitHub"}, status_code=401)

    body = await request.json()
    content = body.get("content", "")

    try:
        result = parse_spec(content, ParseOptions(file_path="preview.md"))
        html = render_spec_html(result.document, repo_owner=owner, repo_name=repo)
    except Exception:
        html = "<p class='text-red-500'>Failed to parse spec content.</p>"

    # Return JSON for Vue SPA, HTML partial for legacy HTMX
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse(content={"html": html})

    tpl = _templates(request)
    return tpl.TemplateResponse(
        request,
        "partials/editor_preview.html",
        {"preview_html": html},
    )


# --- Regex for extracting prose (mirrors parser patterns) ---

_CHECKBOX_RE = re.compile(r"^(\s*)-\s*\[([ xX])\]\s+(.+)$")
_REALIZATION_RE = re.compile(
    r"<!--\s*(?:specwright|canon):realized-in:(?:PR#(\d+)|(audit))\s+file:([^\s]+?)(?::(\S+))?\s*-->"
)
_STATUS_RE = re.compile(r"<!--\s*(?:specwright|canon):system:(\S+)\s+status:(\S+)\s*-->")
_TICKET_RE = re.compile(r"<!--\s*(?:specwright|canon):ticket:(\w+):(\S+)\s*-->")
_AC_HEADING_RE = re.compile(r"^###\s+Acceptance\s+Criteria\s*$", re.IGNORECASE)


def _extract_prose(content: str) -> str:
    """Extract prose content from a section, stripping ACs, comments, and AC heading.

    Once the ``### Acceptance Criteria`` heading is encountered, all remaining
    lines are treated as part of the AC block and excluded from prose.  This
    prevents content after the checklist from being silently reordered on
    round-trip.
    """
    lines = content.split("\n")
    prose_lines: list[str] = []
    for line in lines:
        if _AC_HEADING_RE.match(line.strip()):
            # Everything from here to end of section is AC — stop collecting prose
            break
        # Skip canon/specwright system comments
        if _STATUS_RE.search(line) or _TICKET_RE.search(line):
            continue
        prose_lines.append(line)
    # Trim trailing blank lines
    while prose_lines and prose_lines[-1].strip() == "":
        prose_lines.pop()
    return "\n".join(prose_lines)


def _section_to_dict(section: SpecSection) -> dict:
    """Serialize a SpecSection to a dict for the editor frontend."""
    acs = []
    for ac in section.acceptance_criteria:
        ac_dict = {
            "text": ac.text,
            "checked": ac.checked,
            "realized_in": [
                {"pr_number": r.pr_number, "file_path": r.file_path, "lines": r.lines}
                for r in ac.realized_in
            ],
        }
        if ac.strength:
            ac_dict["strength"] = ac.strength
        acs.append(ac_dict)

    result = {
        "id": section.id,
        "section_number": section.section_number,
        "title": section.title,
        "depth": section.depth,
        "content": section.content,
        "prose_content": _extract_prose(section.content),
        "status": section.status.state,
        "acceptance_criteria": acs,
        "children": [_section_to_dict(c) for c in section.children],
    }
    if section.ticket_link:
        result["ticket_link"] = {
            "system": section.ticket_link.system,
            "ticket_id": section.ticket_link.ticket_id,
        }
    return result


@editor_router.post("/{owner}/{repo}/parse", response_class=JSONResponse)
async def editor_parse(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """Parse spec content and return structured sections as JSON."""
    github_user = _get_github_user(request)
    if github_user is None:
        return JSONResponse(content={"error": "Not authenticated with GitHub"}, status_code=401)

    try:
        body = await request.json()
        parse_req = EditorParseRequest(**body)
    except Exception:
        return JSONResponse(content={"error": "Invalid request body"}, status_code=400)

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, parse_spec, parse_req.content, ParseOptions(file_path="editor.md")
        )
        sections = [_section_to_dict(s) for s in result.document.sections]
        return JSONResponse(content={"ok": True, "sections": sections})
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=400)


@editor_router.get("/{owner}/{repo}/new/template", response_class=JSONResponse)
async def api_new_spec_template(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """Return a new spec template pre-filled with user info."""
    github_user = _get_github_user(request)
    user_name = ""
    if github_user:
        user_name = github_user.get("name") or github_user.get("login", "")

    content = new_spec_template(owner=user_name)
    return JSONResponse(content={"content": content})


@editor_router.post("/{owner}/{repo}/generate")
async def api_generate_spec(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
):
    """Stream AI-generated spec content via SSE."""
    github_user = _get_github_user(request)
    if github_user is None:
        return JSONResponse(content={"error": "Not authenticated with GitHub"}, status_code=401)

    # Rate limit per GitHub user
    login = github_user.get("login", "unknown")
    if not _check_generate_rate(login):
        return JSONResponse(
            content={"error": "Rate limit exceeded. Try again later."}, status_code=429
        )

    try:
        body = await request.json()
        description = body.get("description", "").strip()
    except Exception:
        return JSONResponse(content={"error": "Invalid request body"}, status_code=400)

    if not description:
        return JSONResponse(content={"error": "Description is required"}, status_code=400)

    # Build repo context (cached per owner/repo for 5 min)
    cache_key = f"gen:{owner}/{repo}"
    cached = _repo_context_cache.get(cache_key)
    if cached is not None:
        existing_specs, team, project_key = cached
    else:
        existing_specs: list[str] = []
        team = ""
        project_key = ""
        client = _user_client(github_user)
        try:
            try:
                from ..github.spec_utils import (
                    extract_directories,
                    matches_doc_patterns,
                )
                from ..github.spec_utils import (
                    load_repo_config as _load_repo_cfg,
                )

                repo_cfg = await _load_repo_cfg(client, owner, repo)
                doc_paths = repo_cfg.specs.doc_paths
                directories = extract_directories(doc_paths)
                import contextlib

                all_items: list[dict] = []
                for directory, _recursive in directories:
                    with contextlib.suppress(Exception):
                        all_items.extend(await client.list_directory(owner, repo, directory))
                existing_specs = [
                    item["name"]
                    for item in all_items
                    if isinstance(item, dict)
                    and item.get("name", "").endswith(".md")
                    and matches_doc_patterns(item.get("path", item.get("name", "")), doc_paths)
                ]
                team = repo_cfg.team or ""
                project_key = repo_cfg.project_key or ""
            except Exception:
                pass
            try:
                try:
                    config_content, _ = await client.get_file(owner, repo, "CANON.yaml")
                except Exception:
                    config_content, _ = await client.get_file(owner, repo, "SPECWRIGHT.yaml")
                config = yaml.safe_load(config_content)
                if isinstance(config, dict):
                    team = team or config.get("team", "")
                    project_key = project_key or config.get("project_key", "")
            except Exception:
                pass
            _repo_context_cache.set(cache_key, (existing_specs, team, project_key))
        finally:
            await client.close()

    user_name = github_user.get("name") or github_user.get("login", "")

    repo_ctx = RepoContext(
        owner=owner,
        repo=repo,
        existing_specs=existing_specs,
        team=team,
        project_key=project_key,
        user_name=user_name,
    )

    claude = _get_claude_client()

    distinct_id = _analytics_id(request)
    analytics.track(
        "ai_spec_generation_started",
        distinct_id=distinct_id,
        properties={
            "repo": f"{owner}/{repo}",
            "description_length": len(description),
        },
        groups={"organization": org},
    )

    async def event_stream():
        t0 = time.monotonic()
        try:
            async for chunk in generate_spec_stream(description, repo_ctx, claude):
                data = json.dumps({"chunk": chunk})
                yield f"data: {data}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            analytics.track(
                "ai_spec_generation_completed",
                distinct_id=distinct_id,
                properties={
                    "repo": f"{owner}/{repo}",
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "success": True,
                },
                groups={"organization": org},
            )
        except Exception as exc:
            logger.exception("Spec generation stream error")
            analytics.capture_exception(exc, distinct_id=distinct_id, groups={"organization": org})
            analytics.track(
                "ai_spec_generation_completed",
                distinct_id=distinct_id,
                properties={
                    "repo": f"{owner}/{repo}",
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "success": False,
                },
                groups={"organization": org},
            )
            yield f"data: {json.dumps({'error': 'Generation failed'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@editor_router.post("/{owner}/{repo}/ai-edit")
async def api_ai_edit(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_WRITE)),
):
    """Stream AI-assisted section editing via SSE."""
    github_user = _get_github_user(request)
    if github_user is None:
        return JSONResponse(content={"error": "Not authenticated with GitHub"}, status_code=401)

    # Rate limit per GitHub user (shares the same limiter as /generate)
    login = github_user.get("login", "unknown")
    if not _check_generate_rate(login):
        return JSONResponse(
            content={"error": "Rate limit exceeded. Try again later."}, status_code=429
        )

    try:
        body = await request.json()
        edit_req = AiEditRequest(**body)
    except Exception:
        return JSONResponse(content={"error": "Invalid request body"}, status_code=400)

    claude = _get_claude_client()

    distinct_id = _analytics_id(request)
    analytics.track(
        "ai_edit_started",
        distinct_id=distinct_id,
        properties={
            "repo": f"{owner}/{repo}",
            "action": edit_req.action,
        },
        groups={"organization": org},
    )

    async def event_stream():
        t0 = time.monotonic()
        try:
            if edit_req.action == "improve":
                stream = improve_section_stream(
                    edit_req.section_title,
                    edit_req.section_content,
                    edit_req.acceptance_criteria,
                    claude,
                )
            elif edit_req.action == "generate_acs":
                stream = generate_acs_stream(
                    edit_req.section_title,
                    edit_req.section_content,
                    claude,
                )
            else:
                stream = expand_section_stream(
                    edit_req.section_title,
                    edit_req.section_content,
                    claude,
                )

            async for chunk in stream:
                data = json.dumps({"chunk": chunk})
                yield f"data: {data}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            analytics.track(
                "ai_edit_completed",
                distinct_id=distinct_id,
                properties={
                    "repo": f"{owner}/{repo}",
                    "action": edit_req.action,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "success": True,
                },
                groups={"organization": org},
            )
        except Exception as exc:
            logger.exception("AI edit stream error")
            analytics.capture_exception(exc, distinct_id=distinct_id, groups={"organization": org})
            analytics.track(
                "ai_edit_completed",
                distinct_id=distinct_id,
                properties={
                    "repo": f"{owner}/{repo}",
                    "action": edit_req.action,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "success": False,
                },
                groups={"organization": org},
            )
            yield f"data: {json.dumps({'error': 'AI editing failed'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
