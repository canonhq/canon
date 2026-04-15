"""FastAPI routes for the Spec Explorer web app."""

from __future__ import annotations

import json
import logging
import re
from html import escape as html_escape
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from canon import analytics

from ..auth.deps import require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import Permission
from ..settings import Settings as _Settings
from .models import SearchApiResponse
from .services import (
    get_coverage,
    get_doc_detail,
    get_facet_counts,
    get_indexing_overview,
    get_org_overview,
    get_repo_detail,
    get_spec_detail,
    get_tasks,
    search_specs,
)

logger = logging.getLogger(__name__)

router = APIRouter()
app_router = APIRouter(prefix="/app")


def _find_templates_dir() -> str:
    """Locate the templates directory in dev (source tree) or Docker (/app)."""
    # Dev: src/canon/web/routes.py → 4 parents up → project root
    source_relative = Path(__file__).resolve().parent.parent.parent.parent / "templates"
    if source_relative.is_dir():
        return str(source_relative)
    # Docker: WORKDIR /app, templates copied to /app/templates/
    docker_path = Path("/app/templates")
    if docker_path.is_dir():
        return str(docker_path)
    raise RuntimeError(f"Templates directory not found at {source_relative} or {docker_path}")


templates = Jinja2Templates(directory=_find_templates_dir())

# Expose PostHog config to all templates via Jinja2 globals.
# NOTE: This instantiates Settings a second time (main.py has its own via
# app.state.settings).  Two Pydantic-Settings parses from the same env vars
# are identical; a single-instance refactor is tracked but not blocking.
_posthog_settings = _Settings()
templates.env.globals["posthog_key"] = _posthog_settings.posthog_key
templates.env.globals["posthog_host"] = _posthog_settings.posthog_host
del _posthog_settings  # avoid keeping a second Settings alive


def _get_client(request: Request):
    return request.app.state.github_client


def _get_cache(request: Request):
    return request.app.state.cache


def _get_org(request: Request) -> str:
    if request.app.state.settings.web_org:
        return request.app.state.settings.web_org
    # Fall back to the authenticated user's org from the session.
    # This handles multi-tenant deployments where web_org is not set
    # (each user resolves to their own org instead of a global default).
    user = _get_user(request)
    if user:
        org_login = user.get("org_login", "")
        if org_login:
            return org_login
        logger.warning(
            "No org resolved for authenticated user: web_org not configured "
            "and session has no org_login"
        )
    else:
        logger.debug("No org resolved: web_org not configured and no session org_login")
    return ""


def _get_user(request: Request) -> dict | None:
    """Return session user dict, or None if no session / not logged in."""
    return request.session.get("user") if hasattr(request, "session") else None


async def _get_user_orgs(request: Request, user: CurrentUser | None = None) -> list[str]:
    """Get org logins visible to the current user.

    When Auth0 Organizations mode is enabled, returns only the orgs the
    user belongs to (cached in session during login callback) so users
    from Org A cannot discover Org B's name in the dropdown.

    When auth is disabled, returns all orgs from the registry (no access
    control needed).
    """
    # Resolve org_login from CurrentUser or fall back to session
    org_login = ""
    session_user = None
    if user:
        org_login = user.org_login
    else:
        session_user = request.session.get("user") if hasattr(request, "session") else None
        if session_user:
            org_login = session_user.get("org_login", "")

    # Multi-tenant: use session-cached org memberships from Auth0
    settings = request.app.state.settings
    if settings.auth0_orgs_enabled:
        if session_user is None:
            session_user = request.session.get("user") if hasattr(request, "session") else None
        if session_user:
            memberships = session_user.get("org_memberships", [])
            if memberships:
                if org_login and org_login in memberships:
                    return [org_login] + [o for o in memberships if o != org_login]
                return memberships
        # Fallback: only current org (no leakage). Return empty for
        # unauthenticated sessions to avoid exposing web_org name.
        if org_login:
            return [org_login]
        return []

    # When auth is disabled (dev/self-hosted), show all orgs from registry.
    if not settings.auth_enabled:
        registry = getattr(request.app.state, "registry", None)
        if registry is not None:
            try:
                orgs = await registry.list_orgs()
                if orgs:
                    if org_login and org_login in orgs:
                        orgs = [org_login] + [o for o in orgs if o != org_login]
                    return orgs
            except Exception:
                logger.warning("Failed to list orgs from registry", exc_info=True)
        return [_get_org(request)]

    # Auth enabled: only return the user's verified org (never all orgs).
    if org_login:
        return [org_login]
    return []


async def _get_client_for_org(request: Request, org: str):
    """Get a GitHubClient scoped to the given org's installation.

    Returns a client whose token is fetched lazily on first API call.
    If the installation turns out to be stale (404), the app-level
    ``InstallationNotFound`` handler marks it as removed.
    """
    registry = getattr(request.app.state, "registry", None)
    base_client = _get_client(request)

    if registry is not None:
        try:
            installation = await registry.get_installation_by_org(org)
            if installation is not None:
                inst_id = str(installation.installation_id)
                if inst_id != base_client.installation_id:
                    return base_client.for_installation(inst_id)
        except Exception:
            logger.warning(
                "Failed to resolve installation for org %s, using default",
                org,
                exc_info=True,
            )

    return base_client


# --- Public routes (no prefix) ---


def _serve_public_spa(request: Request, *, title: str, description: str) -> HTMLResponse | None:
    """Serve the SPA shell for public (unauthenticated) marketing pages.

    Injects OG meta tags, canonical URLs, and a ``window.__CANON__`` script
    block with a session containing null user/auth fields plus PostHog and
    environment config. For SSG-prerendered routes, serves the route-specific
    HTML with full page content already present.
    Returns None if the SPA is not built (caller should provide a fallback).
    """
    html = _get_spa_html(route=str(request.url.path))
    if html is None:
        return None

    settings = request.app.state.settings
    session_data = json.dumps(
        {
            "user": None,
            "org": "",
            "orgs": [],
            "permissions": [],
            "github_user": None,
            "posthog_key": settings.posthog_key,
            "posthog_host": settings.posthog_host,
            "auth_enabled": settings.auth_enabled,
            "auth_mode": settings.auth_mode or "auth0",
            "environment": settings.environment,
        }
    )
    safe_data = session_data.replace("<", r"\u003c").replace(">", r"\u003e").replace("&", r"\u0026")

    esc_title = html_escape(title, quote=True)
    esc_desc = html_escape(description, quote=True)
    esc_path = html_escape(str(request.url.path), quote=True)
    base_url = str(request.base_url).rstrip("/")
    og_tags = (
        f"<title>{esc_title}</title>\n"
        f'<meta name="description" content="{esc_desc}">\n'
        f'<link rel="canonical" href="{base_url}{esc_path}">\n'
        '<meta property="og:type" content="website">\n'
        f'<meta property="og:title" content="{esc_title}">\n'
        f'<meta property="og:description" content="{esc_desc}">\n'
        f'<meta property="og:url" content="{base_url}{esc_path}">\n'
        f'<meta property="og:image" content="{base_url}/static/og-image.png">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{esc_title}">\n'
        f'<meta name="twitter:description" content="{esc_desc}">\n'
        f'<meta name="twitter:image" content="{base_url}/static/og-image.png">\n'
    )
    # Strip any existing <title> from SSG-prerendered HTML to avoid duplicates
    html = re.sub(r"<title>[^<]*</title>\s*", "", html)
    injection = f"{og_tags}<script>window.__CANON__ = {safe_data};</script>"
    html = html.replace("</head>", f"{injection}\n</head>")
    return HTMLResponse(content=html)


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Marketing landing page — served via Vue SPA with minimal session data."""
    resp = _serve_public_spa(
        request,
        title="Canon \u2014 Spec-driven development, automated.",
        description="AI agents verify code against specs, sync tickets bidirectionally, and keep docs accurate. Self-hosted, open source.",
    )
    if resp is not None:
        return resp
    return templates.TemplateResponse(request, "landing.html")


@router.get("/changelog", response_class=HTMLResponse)
async def public_changelog(request: Request):
    """Public changelog."""
    resp = _serve_public_spa(
        request,
        title="Changelog \u2014 Canon",
        description="What's new in Canon.",
    )
    if resp is not None:
        return resp
    return HTMLResponse(content="SPA not built", status_code=503)


@router.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    """Dedicated pricing page."""
    resp = _serve_public_spa(
        request,
        title="Pricing \u2014 Canon",
        description="Self-hosted free forever. Managed cloud from $9/user/month with a 14-day Pro trial.",
    )
    if resp is not None:
        return resp
    return HTMLResponse(content="SPA not built", status_code=503)


@router.post("/api/waitlist", response_class=JSONResponse)
async def waitlist_signup(request: Request):
    """Capture waitlist email signup (fires PostHog event, no DB needed)."""
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return JSONResponse(content={"error": "Invalid request body"}, status_code=400)

    email = body.get("email", "").strip()
    if not email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return JSONResponse(content={"error": "Valid email required"}, status_code=400)

    analytics.track(
        "waitlist_signup",
        distinct_id=email,
        properties={"email": email, "source": "landing_page"},
    )
    logger.info("Waitlist signup recorded")
    return JSONResponse(content={"ok": True}, status_code=201)


# --- Admin routes (registered BEFORE org routes to prevent /{org} matching "admin") ---


@app_router.get("/admin/indexing", response_class=HTMLResponse)
async def admin_indexing(
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_ADMIN)),
):
    """Admin page showing indexing status across all installations."""
    if spa := await _serve_spa(request):
        return spa
    registry = getattr(request.app.state, "registry", None)
    indexer = getattr(request.app.state, "indexer", None)
    overview = await get_indexing_overview(registry, indexer)
    orgs = await _get_user_orgs(request, user)

    return templates.TemplateResponse(
        request,
        "admin/indexing.html",
        {
            "indexing": overview,
            "orgs": orgs,
            "user": _get_user(request),
        },
    )


@app_router.post("/admin/reindex/{installation_id}", response_class=HTMLResponse)
async def admin_reindex(
    request: Request,
    installation_id: int,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_ADMIN)),
):
    """Trigger a re-index for a specific installation."""
    registry = getattr(request.app.state, "registry", None)
    indexer = getattr(request.app.state, "indexer", None)
    search_index = getattr(request.app.state, "search_index", None)
    embed_client = getattr(request.app.state, "embed_client", None)

    if registry is None or indexer is None or search_index is None:
        return HTMLResponse(content="Indexing infrastructure not available", status_code=503)

    installation = await registry.get_installation_by_id(installation_id)
    if installation is None:
        return HTMLResponse(content="Installation not found", status_code=404)

    base_client = _get_client(request)
    client = base_client.for_installation(str(installation_id))

    indexer.schedule_org_index(
        installation_id=installation_id,
        org_login=installation.org_login,
        client=client,
        search_index=search_index,
        embed_client=embed_client,
        registry=registry,
    )

    return RedirectResponse(url="/app/admin/indexing", status_code=303)


# --- App root redirect ---


@app_router.get("/", response_class=HTMLResponse)
async def dashboard_redirect(request: Request):
    """Redirect /app/ to /app/{default_org}/ or /app/no-org if unaffiliated."""
    settings = request.app.state.settings
    if settings.auth_enabled:
        user = _get_user(request)
        if not user:
            return RedirectResponse(url="/auth/login", status_code=302)
        if not user.get("org_login"):
            pending = (
                request.session.get("pending_org_choices") if hasattr(request, "session") else None
            )
            if pending:
                return RedirectResponse(url="/app/choose-org", status_code=302)
            # Fallback: use org_memberships (set by callback from provider)
            # when org_login wasn't resolved from JWT or GitHub membership.
            memberships = user.get("org_memberships", [])
            if memberships:
                chosen = memberships[0]
                # Persist to session so the auth middleware's org isolation
                # check passes on the subsequent request.
                user["org_login"] = chosen
                logger.info(
                    "dashboard_redirect: org resolved from org_memberships fallback (org=%s)",
                    chosen,
                )
                return RedirectResponse(url=f"/app/{chosen}/", status_code=302)
            return RedirectResponse(url="/app/no-org", status_code=302)
    org = _get_org(request)
    return RedirectResponse(url=f"/app/{org}/", status_code=302)


# --- Setup callback (GitHub App post-install redirect) ---


@app_router.get("/setup/complete")
async def setup_complete(request: Request, installation_id: int = 0):
    """Handle redirect from GitHub after app installation.

    GitHub sends the user here with ?installation_id=X after they install
    the app. We look up which org that installation belongs to and redirect
    to their welcome page.
    """
    if installation_id:
        registry = getattr(request.app.state, "registry", None)
        if registry:
            # The webhook may have already registered the installation
            installation = await registry.get_installation_by_id(installation_id)
            if installation and installation.org_login:
                return RedirectResponse(
                    url=f"/app/{installation.org_login}/welcome",
                    status_code=302,
                )

    # Fallback: webhook hasn't arrived yet or no installation_id
    org = _get_org(request)
    return RedirectResponse(url=f"/app/{org}/welcome", status_code=302)


# --- No-org onboarding routes ---


@app_router.get("/no-org", response_class=HTMLResponse)
async def no_org_page(request: Request):
    """Landing page for authenticated users with no verified org membership."""
    if spa := await _serve_spa(request, "no-org"):
        return spa
    settings = request.app.state.settings
    github_app_url = settings.github_app_url if hasattr(settings, "github_app_url") else ""
    return HTMLResponse(
        content=f"""<!DOCTYPE html>
<html><head><title>Canon — Get Started</title></head>
<body style="font-family:system-ui;max-width:600px;margin:80px auto;padding:0 20px">
<h1>Welcome to Canon</h1>
<p>You're signed in, but you don't belong to any organization with Canon installed.</p>
<h3>Next steps:</h3>
<ul>
<li><strong>Install Canon</strong> on your GitHub organization:
    <a href="{github_app_url or "https://github.com/apps/canonhq"}">Install GitHub App</a></li>
<li><strong>Ask an admin</strong> of an existing Canon org to invite you</li>
</ul>
<p><a href="/auth/logout">Sign out</a></p>
</body></html>""",
        status_code=200,
    )


@app_router.get("/choose-org", response_class=JSONResponse)
async def choose_org_page(request: Request):
    """Return available orgs for authenticated users with multiple matches."""
    if spa := await _serve_spa(request, "choose-org"):
        return spa
    pending = request.session.get("pending_org_choices", []) if hasattr(request, "session") else []
    if not pending:
        return RedirectResponse(url="/app/no-org", status_code=302)
    return JSONResponse(content={"orgs": pending})


@app_router.post("/choose-org", response_class=RedirectResponse)
async def choose_org_submit(request: Request):
    """Accept an org selection from the org picker."""
    pending = request.session.get("pending_org_choices", []) if hasattr(request, "session") else []
    if not pending:
        return RedirectResponse(url="/app/no-org", status_code=302)

    form = await request.form()
    chosen = str(form.get("org", ""))

    if chosen not in pending:
        return RedirectResponse(url="/app/choose-org", status_code=302)

    # Set the chosen org in the session
    session_user = request.session.get("user")
    if session_user:
        session_user["org_login"] = chosen
        request.session["user"] = session_user
        logger.info("User %s selected org %s", session_user.get("sub", "unknown"), chosen)
    request.session.pop("pending_org_choices", None)

    return RedirectResponse(url=f"/app/{chosen}/", status_code=302)


# --- Org-scoped routes ---


@app_router.get("/{org}/welcome", response_class=HTMLResponse)
async def org_welcome(request: Request, org: str):
    """First-run onboarding page with setup checklist."""
    if spa := await _serve_spa(request, org):
        return spa
    session_user = _get_user(request)
    parts = (session_user.get("name") or "").split() if session_user else []
    user_name = parts[0] if parts else ""

    registry = getattr(request.app.state, "registry", None)
    app_installed = False
    has_specs = False

    if registry:
        try:
            installation = await registry.get_installation_by_org(org)
            if installation:
                app_installed = True
                client = await _get_client_for_org(request, org)
                cache = _get_cache(request)
                search_index = getattr(request.app.state, "search_index", None)
                overview = await get_org_overview(client, org, cache, search_index=search_index)
                has_specs = overview.total_specs > 0
        except Exception:
            logger.debug("Failed to load welcome page state for org %s", org, exc_info=True)

    install_url = "https://github.com/apps/canon-hq/installations/new"
    orgs = await _get_user_orgs(request)

    return templates.TemplateResponse(
        request,
        "welcome.html",
        {
            "user_name": user_name,
            "app_installed": app_installed,
            "has_specs": has_specs,
            "install_url": install_url,
            "orgs": orgs,
            "current_org": org,
            "user": session_user,
        },
    )


@app_router.get("/{org}/", response_class=HTMLResponse)
async def org_dashboard(request: Request, org: str):
    """Org dashboard — all repos and specs."""
    if spa := await _serve_spa(request, org):
        return spa
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    search_index = getattr(request.app.state, "search_index", None)
    overview = await get_org_overview(client, org, cache, search_index=search_index)
    facets = await get_facet_counts(client, org, cache, search_index=search_index)
    orgs = await _get_user_orgs(request)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "overview": overview,
            "facets": facets,
            "orgs": orgs,
            "current_org": org,
            "user": _get_user(request),
        },
    )


@app_router.get("/{org}/repos/{owner}/{repo}", response_class=HTMLResponse)
async def org_repo_detail(request: Request, org: str, owner: str, repo: str):
    """Single repo view with specs and config."""
    if spa := await _serve_spa(request, org):
        return spa
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    search_index = getattr(request.app.state, "search_index", None)
    detail = await get_repo_detail(client, owner, repo, cache, search_index=search_index)
    if detail is None:
        return HTMLResponse(content="Repository not found", status_code=404)
    orgs = await _get_user_orgs(request)
    return templates.TemplateResponse(
        request,
        "repo.html",
        {
            "repo": detail,
            "orgs": orgs,
            "current_org": org,
            "user": _get_user(request),
        },
    )


@app_router.get("/{org}/specs/{owner}/{repo}/{file_path:path}", response_class=HTMLResponse)
async def org_spec_detail(request: Request, org: str, owner: str, repo: str, file_path: str):
    """Full spec detail with rendered content."""
    if spa := await _serve_spa(request, org):
        return spa
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    detail = await get_spec_detail(client, owner, repo, file_path, cache)
    if detail is None:
        return HTMLResponse(content="Spec not found", status_code=404)
    orgs = await _get_user_orgs(request)
    return templates.TemplateResponse(
        request,
        "spec.html",
        {
            "spec": detail,
            "orgs": orgs,
            "current_org": org,
            "user": _get_user(request),
        },
    )


@app_router.get("/{org}/docs/{owner}/{repo}/{file_path:path}", response_class=HTMLResponse)
async def org_doc_detail(request: Request, org: str, owner: str, repo: str, file_path: str):
    """Full doc detail with rendered markdown."""
    if spa := await _serve_spa(request, org):
        return spa
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    detail = await get_doc_detail(client, owner, repo, file_path, cache)
    if detail is None:
        return HTMLResponse(content="Document not found", status_code=404)
    orgs = await _get_user_orgs(request)
    return templates.TemplateResponse(
        request,
        "doc.html",
        {
            "doc": detail,
            "orgs": orgs,
            "current_org": org,
            "user": _get_user(request),
        },
    )


@app_router.get("/{org}/api/search", response_class=JSONResponse)
async def api_search(
    request: Request,
    org: str,
    q: str = "",
    team: str = "",
    status: str = "",
    tag: str = "",
    repo: str = "",
    limit: int = 20,
    offset: int = 0,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """JSON search API for autocomplete and programmatic access."""
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    search_index = getattr(request.app.state, "search_index", None)
    embed_client = getattr(request.app.state, "embed_client", None)

    results = await search_specs(
        client,
        org,
        cache,
        query=q,
        team=team,
        status=status,
        tag=tag,
        repo=repo,
        search_index=search_index,
        embed_client=embed_client,
    )

    facets = await get_facet_counts(
        client,
        org,
        cache,
        search_index=search_index,
        repo=repo,
    )

    total = len(results)
    paginated = results[offset : offset + limit]

    if q:
        user = _get_user(request)
        analytics.track(
            "search_performed",
            distinct_id=user.get("sub", analytics.SERVER_ACTOR) if user else analytics.SERVER_ACTOR,
            properties={
                "results_count": total,
                "org": org,
                "has_filters": bool(team or status or tag or repo),
                # Raw query intentionally omitted — users may search for
                # confidential project names or employee names. Result count
                # + filter presence is sufficient for product analytics.
            },
            groups={"organization": org},
        )

    response = SearchApiResponse(results=paginated, total=total, facets=facets)
    return JSONResponse(content=response.model_dump())


@app_router.get("/{org}/api/coverage", response_class=JSONResponse)
async def api_coverage(
    request: Request,
    org: str,
    repo: str = "",
    team: str = "",
    days: int = 30,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """JSON coverage API — aggregate metrics and trend data."""
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    agent_store = getattr(request.app.state, "agent_store", None)

    result = await get_coverage(
        client,
        org,
        cache,
        repo=repo,
        team=team,
        days=days,
        agent_store=agent_store,
    )
    return JSONResponse(content=result.model_dump())


def _build_session_dict(
    user: dict | None,
    org: str,
    orgs: list[str],
    github_user: dict | None,
    settings: _Settings,
) -> dict:
    """Build the session data dict shared by api_session and _serve_spa."""
    # Use permissions from the session (set during login from JWT claims or DB role).
    # Fall back to basic permissions for anonymous/unauthenticated users.
    permissions: list[str] = list(user.get("permissions", [])) if user else []

    # Ensure baseline permissions: all users get specs:read, GitHub-connected
    # users get specs:write (preserves pre-existing behavior for sessions that
    # may not have these permissions stored).
    if user and "specs:read" not in permissions:
        permissions.append("specs:read")
    if user and github_user and "specs:write" not in permissions:
        permissions.append("specs:write")

    # web_admin_logins is an escape hatch that supplements session permissions
    # (e.g. grant specs:admin to specific GitHub logins without DB/JWT changes).
    if user and github_user:
        login = github_user.get("login", "")
        admin_logins = {
            s.strip().lower() for s in settings.web_admin_logins.split(",") if s.strip()
        }
        if login and login.lower() in admin_logins and "specs:admin" not in permissions:
            permissions.append("specs:admin")

    return {
        "user": user,
        "org": org,
        "orgs": orgs,
        "permissions": permissions,
        "github_user": {
            "login": github_user.get("login", ""),
            "name": github_user.get("name", ""),
        }
        if github_user
        else None,
        "posthog_key": settings.posthog_key,
        "posthog_host": settings.posthog_host,
        "auth_enabled": settings.auth_enabled,
        "auth_mode": settings.auth_mode or "auth0",
        "environment": settings.environment,
    }


@app_router.get("/{org}/api/session", response_class=JSONResponse)
async def api_session(request: Request, org: str):
    """JSON session data for the Vue SPA.

    Note: posthog_key and posthog_host are intentionally included without
    auth — PostHog project API keys are designed to be public (write-only,
    no read access to analytics data).
    """
    user = _get_user(request)
    settings = request.app.state.settings
    if not user and settings.auth_enabled:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    orgs = await _get_user_orgs(request)
    github_user = request.session.get("github_user") if hasattr(request, "session") else None

    # Validate the route org against the user's orgs to prevent
    # deep-links from injecting a wrong org into the session dict
    resolved_org = org if org in orgs else (orgs[0] if orgs else settings.web_org)

    return JSONResponse(
        content=_build_session_dict(user, resolved_org, orgs, github_user, settings)
    )


@app_router.get("/{org}/api/dashboard", response_class=JSONResponse)
async def api_dashboard(
    request: Request,
    org: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """JSON org dashboard data for the Vue SPA."""
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    search_index = getattr(request.app.state, "search_index", None)
    overview = await get_org_overview(client, org, cache, search_index=search_index)
    return JSONResponse(content=overview.model_dump())


@app_router.get("/{org}/api/tasks", response_class=JSONResponse)
async def api_tasks(
    request: Request,
    org: str,
    status: str | None = None,
    repo: str | None = None,
    expand: str | None = None,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """JSON tasks data — actionable work items from all specs."""
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    search_index = getattr(request.app.state, "search_index", None)
    result = await get_tasks(
        client,
        org,
        cache,
        status=status,
        repo_filter=repo,
        search_index=search_index,
        expand=expand,
    )
    return JSONResponse(content=result.model_dump())


@app_router.get("/{org}/api/repos/{owner}/{repo}", response_class=JSONResponse)
async def api_repo_detail(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """JSON repo detail for the Vue SPA."""
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    search_index = getattr(request.app.state, "search_index", None)
    detail = await get_repo_detail(client, owner, repo, cache, search_index=search_index)
    if detail is None:
        return JSONResponse(content={"error": "Repository not found"}, status_code=404)
    return JSONResponse(content=detail.model_dump())


@app_router.get("/{org}/api/specs/{owner}/{repo}/{file_path:path}", response_class=JSONResponse)
async def api_spec_detail(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    file_path: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """JSON spec detail for the Vue SPA."""
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    detail = await get_spec_detail(client, owner, repo, file_path, cache)
    if detail is None:
        return JSONResponse(content={"error": "Spec not found"}, status_code=404)
    return JSONResponse(content=detail.model_dump())


@app_router.get("/{org}/api/docs/{owner}/{repo}/{file_path:path}", response_class=JSONResponse)
async def api_doc_detail(
    request: Request,
    org: str,
    owner: str,
    repo: str,
    file_path: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """JSON doc detail for the Vue SPA."""
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    detail = await get_doc_detail(client, owner, repo, file_path, cache)
    if detail is None:
        return JSONResponse(content={"error": "Document not found"}, status_code=404)
    return JSONResponse(content=detail.model_dump())


@app_router.get("/{org}/api/welcome", response_class=JSONResponse)
async def api_welcome(
    request: Request,
    org: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
):
    """JSON welcome/onboarding data for the Vue SPA."""
    session_user = _get_user(request)
    parts = (session_user.get("name") or "").split() if session_user else []
    user_name = parts[0] if parts else ""

    registry = getattr(request.app.state, "registry", None)
    app_installed = False
    has_specs = False

    if registry:
        try:
            installation = await registry.get_installation_by_org(org)
            if installation:
                app_installed = True
                client = await _get_client_for_org(request, org)
                cache = _get_cache(request)
                search_index = getattr(request.app.state, "search_index", None)
                overview = await get_org_overview(client, org, cache, search_index=search_index)
                has_specs = overview.total_specs > 0
        except Exception:
            logger.debug("Failed to load welcome state for org %s", org, exc_info=True)

    return JSONResponse(
        content={
            "user_name": user_name,
            "app_installed": app_installed,
            "has_specs": has_specs,
            "install_url": "https://github.com/apps/canon-hq/installations/new",
        }
    )


@app_router.get("/admin/api/indexing", response_class=JSONResponse)
async def api_admin_indexing(
    request: Request,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_ADMIN)),
):
    """JSON indexing overview for the Vue SPA admin page."""
    registry = getattr(request.app.state, "registry", None)
    indexer = getattr(request.app.state, "indexer", None)
    overview = await get_indexing_overview(registry, indexer)
    return JSONResponse(content=overview)


@app_router.post("/admin/api/reindex/{installation_id}", response_class=JSONResponse)
async def api_admin_reindex(
    request: Request,
    installation_id: int,
    user: CurrentUser = Depends(require_permission(Permission.SPECS_ADMIN)),
):
    """Trigger re-index via JSON API for the Vue SPA."""
    registry = getattr(request.app.state, "registry", None)
    indexer = getattr(request.app.state, "indexer", None)
    search_index = getattr(request.app.state, "search_index", None)
    embed_client = getattr(request.app.state, "embed_client", None)

    if registry is None or indexer is None or search_index is None:
        return JSONResponse(
            content={"error": "Indexing infrastructure not available"}, status_code=503
        )

    installation = await registry.get_installation_by_id(installation_id)
    if installation is None:
        return JSONResponse(content={"error": "Installation not found"}, status_code=404)

    base_client = _get_client(request)
    client = base_client.for_installation(str(installation_id))

    indexer.schedule_org_index(
        installation_id=installation_id,
        org_login=installation.org_login,
        client=client,
        search_index=search_index,
        embed_client=embed_client,
        registry=registry,
    )

    return JSONResponse(content={"ok": True})


@app_router.get("/{org}/search", response_class=HTMLResponse)
async def org_search(
    request: Request,
    org: str,
    q: str = "",
    team: str = "",
    status: str = "",
    tag: str = "",
    repo: str = "",
    review_status: str = "",
):
    """Search specs — returns HTMX partial or full page."""
    if spa := await _serve_spa(request, org):
        return spa
    client = await _get_client_for_org(request, org)
    cache = _get_cache(request)
    search_index = getattr(request.app.state, "search_index", None)
    embed_client = getattr(request.app.state, "embed_client", None)
    results = await search_specs(
        client,
        org,
        cache,
        query=q,
        team=team,
        status=status,
        tag=tag,
        repo=repo,
        review_status=review_status,
        search_index=search_index,
        embed_client=embed_client,
    )

    return templates.TemplateResponse(
        request,
        "partials/search_results.html",
        {
            "results": results,
            "query": q,
            "current_org": org,
            "user": _get_user(request),
        },
    )


# --- SPA support ---


def _find_spa_index() -> Path | None:
    """Locate the Vue SPA index.html in static/app/."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "static" / "app" / "index.html",
        Path("/app/static/app/index.html"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


# Cache the SPA index path and HTML.
# In production the file never changes between deploys (restart picks up new
# content).  In development, we re-read when the file's mtime changes so
# `npm run build` is picked up without restarting uvicorn.
_spa_path: Path | None = None
_spa_index_html: str | None = None
_spa_mtime: float = 0
_spa_checked: bool = False
_ssg_cache: dict[str, tuple[float, str]] = {}
_SSG_CACHE_MAX = 20


def _get_spa_html(route: str = "/") -> str | None:
    """Get SPA HTML with mtime-based cache invalidation.

    For prerendered routes (SSG), looks for route-specific HTML files first
    (e.g. static/app/pricing.html or static/app/pricing/index.html for
    /pricing), falling back to the main index.html. The flat file form
    takes priority over the directory form.
    """
    global _spa_checked, _spa_path, _spa_index_html, _spa_mtime
    if not _spa_checked:
        _spa_checked = True
        _spa_path = _find_spa_index()
    if _spa_path is None:
        return None

    # Try route-specific prerendered HTML (e.g. /pricing -> pricing.html or pricing/index.html)
    if route and route != "/":
        route_segment = route.strip("/")
        base_dir = _spa_path.parent.resolve()
        for candidate in [
            _spa_path.parent / f"{route_segment}.html",
            _spa_path.parent / route_segment / "index.html",
        ]:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(base_dir):
                logger.warning("SSG path traversal blocked: %s", candidate)
                continue
            if resolved.is_file():
                try:
                    mtime = resolved.stat().st_mtime
                    cache_key = str(resolved)
                    cached = _ssg_cache.get(cache_key)
                    if cached and cached[0] == mtime:
                        return cached[1]
                    content = resolved.read_text()
                    if len(_ssg_cache) >= _SSG_CACHE_MAX:
                        _ssg_cache.pop(next(iter(_ssg_cache)))
                    _ssg_cache[cache_key] = (mtime, content)
                    return content
                except OSError:
                    logger.warning(
                        "SSG file exists but could not be read: %s", resolved, exc_info=True
                    )

    # Fall back to main index.html (with mtime cache)
    try:
        mtime = _spa_path.stat().st_mtime
    except OSError:
        logger.warning(
            "SPA index.html stat failed, serving cached version: %s", _spa_path, exc_info=True
        )
        return _spa_index_html
    if mtime != _spa_mtime:
        try:
            content = _spa_path.read_text()
        except OSError:
            logger.warning("SPA index.html read failed: %s", _spa_path, exc_info=True)
            return _spa_index_html
        _spa_mtime = mtime
        _spa_index_html = content
    return _spa_index_html


async def _serve_spa(request: Request, org: str | None = None) -> HTMLResponse | None:
    """Serve the Vue SPA shell with injected session data.

    Args:
        request: The incoming request.
        org: The org from the route parameter.  When provided and valid
            (i.e. the user is a member), this org is used in the session
            dict so deep-links to ``/app/other-org/`` resolve correctly.

    Returns an HTMLResponse if the SPA is built, or None to fall back to
    Jinja2 templates.
    """
    html = _get_spa_html()
    if html is None:
        return None

    # Inject session data (reuse shared helper)
    user = _get_user(request)
    orgs = await _get_user_orgs(request)
    github_user = request.session.get("github_user") if hasattr(request, "session") else None
    settings = request.app.state.settings

    # Use the requested org if the user is a member, otherwise default
    resolved_org = org if (org and org in orgs) else (orgs[0] if orgs else settings.web_org)

    session_data = json.dumps(_build_session_dict(user, resolved_org, orgs, github_user, settings))

    # Escape for safe embedding in <script> — prevent </script> breakout
    safe_data = session_data.replace("<", r"\u003c").replace(">", r"\u003e").replace("&", r"\u0026")

    # Inject before </head> so it's available before Vue mounts
    injection = f"<script>window.__CANON__ = {safe_data};</script>"
    html = html.replace("</head>", f"{injection}\n</head>")

    return HTMLResponse(content=html)


# SPA catch-all for routes with no Jinja2 equivalent (e.g. /app/{org}/editor/*)
spa_router = APIRouter(prefix="/app")


@spa_router.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_catchall(request: Request, full_path: str):
    """Catch-all for SPA routes that don't match any other /app/* route."""
    # Extract org from the path (first segment of /app/{org}/...)
    org = full_path.split("/")[0] if full_path else None
    response = await _serve_spa(request, org)
    if response is not None:
        return response
    return HTMLResponse(content="SPA not built. Run: cd frontend && npm run build", status_code=503)
