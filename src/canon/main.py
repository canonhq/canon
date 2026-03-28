"""FastAPI application — webhook routes, health checks, web UI."""

from __future__ import annotations

import json
import logging
import os
import stat
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import ClientDisconnect

from . import analytics, otel_logging
from .alerts.slack import SlackAlerter
from .auth.api_key_routes import api_key_router
from .auth.device_routes import device_router
from .auth.github_routes import github_auth_router
from .auth.middleware import AuthMiddleware
from .auth.refresh_routes import refresh_router
from .auth.routes import auth_router
from .billing.routes import router as billing_router
from .billing.routes import webhook_router as billing_webhook_router
from .db import (
    AgentStore,
    ErrorStore,
    InstallationRegistry,
    SessionStore,
    UserStore,
    close_pool,
    create_pool,
    ensure_schema,
)
from .github.client import GitHubClient, InstallationNotFound
from .github.verify import verify_signature
from .settings import Settings
from .web.analytics_routes import analytics_router
from .web.cache import TTLCache
from .web.editor_routes import editor_router
from .web.middleware import CacheControlMiddleware, RateLimitMiddleware, RequestLoggingMiddleware
from .web.profile_routes import profile_router
from .web.routes import app_router, spa_router
from .web.routes import router as web_router
from .web.ticket_routes import ticket_router
from .webhooks.router import router as webhooks_router

logger = logging.getLogger(__name__)

settings = Settings()

_client: GitHubClient | None = None


def _get_client() -> GitHubClient:
    global _client
    if _client is None:
        _client = GitHubClient(
            app_id=settings.gh_app_id,
            private_key=settings.gh_private_key,
            installation_id=settings.gh_installation_id,
        )
    return _client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # Startup
    app.state.settings = settings
    app.state.cache = TTLCache(ttl_seconds=settings.cache_ttl_seconds)

    # Analytics — super properties provide environment context on every event
    import importlib.metadata
    import socket

    try:
        app_version = importlib.metadata.version("canonhq")
    except importlib.metadata.PackageNotFoundError:
        app_version = "dev"

    analytics.init(
        settings.posthog_key,
        settings.posthog_host,
        super_properties={
            "service": "canon",
            "environment": settings.environment,
            "version": app_version,
            "hostname": socket.gethostname(),
        },
    )

    # PostHog query client (analytics dashboard read queries)
    from .analytics_query import PostHogQueryClient

    app.state.posthog_query_client = PostHogQueryClient(
        api_key=settings.posthog_personal_api_key,
        project_id=settings.posthog_project_id,
        host=settings.posthog_host,
    )
    _qc = app.state.posthog_query_client
    logger.info(
        "PostHog query client configured=%s (project_id=%s)",
        _qc.configured,
        settings.posthog_project_id or "(empty)",
    )

    # SRE Slack alerter
    app.state.slack_alerter = SlackAlerter(
        webhook_url=settings.slack_alerts_webhook_url,
    )
    if app.state.slack_alerter.enabled:
        logger.info("Slack alerts enabled (channel configured)")

    # OTel logs to PostHog (opt-in)
    if settings.posthog_logs_enabled:
        otel_logging.init(
            settings.posthog_key,
            min_level=settings.posthog_logs_min_level,
            posthog_host=settings.posthog_host,
        )

    # OIDC provider (optional — selects Auth0Provider or GenericOIDCProvider)
    app.state.oidc_provider = None
    if settings.auth_enabled:
        from .auth.providers import create_provider

        try:
            provider = create_provider(settings)
        except ValueError as exc:
            logger.error("OIDC provider initialization failed: %s", exc)
            raise
        app.state.oidc_provider = provider
        if provider is not None:
            logger.info(
                "OIDC provider configured (type=%s)",
                type(provider).__name__,
            )

    # Authlib OAuth client (used by routes for CSRF-safe redirect flow)
    if settings.auth_enabled:
        from .auth.oauth import configure_oauth

        configure_oauth(settings)
        if settings.auth0_enabled:
            logger.info("Auth0 configured (domain=%s)", settings.auth0_domain)
        else:
            logger.info("Generic OIDC configured (issuer=%s)", settings.oidc_issuer)

    # GitHub OAuth for web editor (optional)
    app.state.github_oauth_client = None
    if settings.github_oauth_enabled:
        from .auth.github_oauth import GitHubOAuthClient

        app.state.github_oauth_client = GitHubOAuthClient(
            client_id=settings.github_oauth_client_id,
            client_secret=settings.github_oauth_client_secret,
        )
        logger.info("GitHub OAuth configured for web editor")

    # Identity store for Slack→GitHub mapping
    from .slack.identity_store import IdentityStore

    app.state.identity_store = IdentityStore(db_pool=getattr(app.state, "db_pool", None))

    app.state.github_client = _get_client()

    # Log unconfigured webhook integrations (endpoints fail-closed with 503)
    for name in ("jira_webhook_secret", "linear_webhook_secret", "asana_webhook_secret"):
        if not getattr(settings, name):
            logger.info(
                "Webhook secret %s is not set — /webhooks/%s endpoint will return 503",
                name,
                name.replace("_webhook_secret", ""),
            )

    # Shared async HTTP client (kept for backward compatibility; provider uses its own)
    import httpx as _httpx

    app.state.auth_http = _httpx.AsyncClient(timeout=30)
    # Legacy alias — some external code may still reference auth0_http
    app.state.auth0_http = app.state.auth_http

    # Optional DB pool
    app.state.db_pool = None
    app.state.registry = None
    app.state.agent_store = None
    app.state.user_store = None
    app.state.session_store = None
    app.state.stripe_client = None
    app.state.billing_service = None
    if settings.database_url:
        try:
            pool = await create_pool(settings.database_url)
            await ensure_schema(pool, settings.database_url)
            app.state.db_pool = pool
            app.state.registry = InstallationRegistry(pool)
            app.state.agent_store = AgentStore(pool)
            app.state.error_store = ErrorStore(pool)
            app.state.user_store = UserStore(pool)
            app.state.session_store = SessionStore(pool)
            logger.info("Database pool initialised")

            # Billing (optional — requires Stripe keys + DB)
            if settings.stripe_enabled:
                from .billing.service import BillingService
                from .billing.stripe_client import StripeClient

                app.state.stripe_client = StripeClient(settings)
                app.state.billing_service = BillingService(
                    pool=pool,
                    stripe_client=app.state.stripe_client,
                    byok_encryption_key=settings.byok_encryption_key,
                )
                logger.info("Billing service initialised")
        except Exception:
            logger.warning("Failed to connect to database — continuing without DB", exc_info=True)

    # Embedding client (optional — works without GCP credentials)
    from .search.embed import EmbeddingClient
    from .search.index import SearchIndex

    embed_client = EmbeddingClient(
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        service_account_key=settings.gcp_service_account_key,
    )
    app.state.embed_client = embed_client
    if embed_client.is_available:
        logger.info("Embedding client initialised")

    # Search index (requires DB pool)
    app.state.search_index = None
    if app.state.db_pool is not None:
        app.state.search_index = SearchIndex(app.state.db_pool)
        logger.info("Search index initialised")

    # Background indexer
    from .search.background import BackgroundIndexer

    app.state.indexer = BackgroundIndexer()

    # MCP server (optional — works without mcp package)
    mcp_server = None
    try:
        from .mcp.auth import McpAuthMiddleware
        from .mcp.deps import McpDeps
        from .mcp.server import create_mcp_server

        mcp_deps = McpDeps(
            search_index=app.state.search_index,
            embed_client=app.state.embed_client,
            github_client=app.state.github_client,
            cache=app.state.cache,
            settings=settings,
            agent_store=getattr(app.state, "agent_store", None),
        )
        mcp_server = create_mcp_server(mcp_deps)
        app.state.mcp_server = mcp_server

        mcp_app = mcp_server.streamable_http_app()
        if settings.mcp_api_key or app.state.user_store:
            mcp_app.add_middleware(
                McpAuthMiddleware,
                api_key=settings.mcp_api_key,
                user_store=app.state.user_store,
            )
        app.mount("/mcp", mcp_app)
        logger.info("MCP server mounted at /mcp")
    except ImportError:
        logger.info("MCP package not installed — skipping MCP server")
    except Exception:
        logger.warning("Failed to initialise MCP server", exc_info=True)

    # Slack bot (optional — interactive Slack app)
    app.state.slack_bot = None
    app.state.notification_dispatcher = None
    if settings.slack_bot_enabled:
        from .slack import create_slack_app

        slack_bot = create_slack_app(settings)
        if slack_bot is not None:
            app.state.slack_bot = slack_bot
            if not slack_bot.socket_mode:
                # HTTP mode: add as a FastAPI route
                @app.post("/slack/events")
                async def slack_events(req: Request):
                    return await slack_bot.handler.handle(req)

                logger.info("Slack bot mounted at /slack/events (HTTP mode)")
            else:
                # Socket mode: start async handler
                from slack_bolt.adapter.socket_mode.async_handler import (
                    AsyncSocketModeHandler,
                )

                app.state.slack_socket_handler = AsyncSocketModeHandler(
                    slack_bot.app, settings.slack_app_token
                )
                import asyncio

                app.state.slack_socket_task = asyncio.create_task(
                    app.state.slack_socket_handler.start_async()
                )
                logger.info("Slack bot started (Socket Mode)")

        # Wire notification dispatcher (requires bot client)
        if app.state.slack_bot is not None:
            from .slack.notifications import NotificationConfig, NotificationDispatcher

            notif_config = NotificationConfig()
            dispatcher = NotificationDispatcher(
                client=app.state.slack_bot.app.client,
                default_channel="#canon-specs",
                sre_channel="",
                config=notif_config,
                quiet_start=None,
                quiet_end=None,
            )
            app.state.notification_dispatcher = dispatcher
            logger.info("Notification dispatcher initialised")
    else:
        logger.info("Slack bot not configured — /slack/events will return 503")

    if mcp_server is not None:
        async with mcp_server.session_manager.run():
            yield
    else:
        yield

    # Shutdown
    # Shutdown Slack socket mode if active
    slack_task = getattr(app.state, "slack_socket_task", None)
    if slack_task is not None:
        slack_task.cancel()
        import asyncio

        await asyncio.gather(slack_task, return_exceptions=True)
    slack_socket = getattr(app.state, "slack_socket_handler", None)
    if slack_socket is not None:
        await slack_socket.close_async()
    phq = getattr(app.state, "posthog_query_client", None)
    if phq is not None:
        await phq.aclose()
    if hasattr(app.state, "slack_alerter"):
        await app.state.slack_alerter.close()
    otel_logging.shutdown()
    analytics.shutdown()
    if app.state.db_pool is not None:
        await close_pool(app.state.db_pool)
    if _client is not None:
        await _client.close()
    auth_http = getattr(app.state, "auth_http", None)
    if auth_http is not None:
        await auth_http.aclose()
    # Close the OIDC provider's HTTP client (avoids connection pool leak)
    oidc_provider = getattr(app.state, "oidc_provider", None)
    if oidc_provider:
        await oidc_provider.aclose()


app = FastAPI(title="Canon", docs_url=None, redoc_url=None, lifespan=lifespan)

# 503 fallback when Slack bot is not configured
if not settings.slack_bot_enabled:

    @app.post("/slack/events")
    async def slack_events_unavailable() -> Response:
        return Response(
            content="Slack bot not configured",
            status_code=503,
        )


def _error_template(request: Request, template: str, status_code: int) -> Response:
    """Render a branded error page if the client accepts HTML."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        from .web.routes import templates

        return templates.TemplateResponse(request, template, status_code=status_code)
    return Response(
        content=json.dumps(
            {"error": "Not found" if status_code == 404 else "Internal server error"}
        ),
        status_code=status_code,
        media_type="application/json",
    )


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Render branded error pages for HTTP errors (404, etc.)."""
    if exc.status_code == 404:
        return _error_template(request, "errors/404.html", 404)
    # Non-404 errors (401, 403, 422) are API-style — always return JSON
    # regardless of Accept header, matching FastAPI's default behavior.
    return Response(
        content=json.dumps({"detail": exc.detail}),
        status_code=exc.status_code,
        media_type="application/json",
    )


@app.exception_handler(InstallationNotFound)
async def _installation_not_found_handler(request: Request, exc: InstallationNotFound) -> Response:
    """Handle stale GitHub installations by marking them as removed.

    When a route tries to use an installation that GitHub no longer
    recognises (404 on token exchange), we mark it as removed in the DB
    so subsequent requests won't retry the same stale ID.
    """
    registry = getattr(request.app.state, "registry", None)
    marked = False
    if registry is not None:
        try:
            await registry.mark_removed(exc.installation_id)
            marked = True
        except Exception:
            logger.warning(
                "Failed to mark stale installation %s as removed",
                exc.installation_id,
                exc_info=True,
            )
    logger.warning(
        "Installation %s is stale (404)%s: %s %s",
        exc.installation_id,
        " — marked as removed" if marked else "",
        request.method,
        request.url.path,
    )
    return Response(
        content=json.dumps({"error": "GitHub App installation not found — please reinstall"}),
        status_code=502,
        media_type="application/json",
    )


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception) -> Response:
    """Capture unhandled exceptions in PostHog for non-streaming routes.

    Coverage split:
    - This handler covers non-streaming request/response routes.
    - SSE streaming routes (generate, ai-edit) catch exceptions inside
      their own ``event_stream()`` generators since errors occur after
      headers are sent and bypass ExceptionMiddleware.
    - ``enable_exception_autocapture`` on the SDK hooks ``sys.excepthook``
      for truly unhandled exceptions (background threads, lifespan errors)
      which never reach this handler — no double-reporting risk.
    """
    # ClientDisconnect is benign — the caller hung up before we read the body.
    # Log at debug to avoid polluting error logs with transient network issues.
    # Uses 499 (nginx convention for client-closed-request, non-standard).
    if isinstance(exc, ClientDisconnect):
        logger.debug("Client disconnected during %s %s", request.method, request.url.path)
        return Response(content="Client disconnected", status_code=499)

    # Try to attribute the exception to the authenticated user if possible.
    distinct_id = analytics.SERVER_ACTOR
    try:
        session = getattr(request, "session", None)
        if session:
            user = session.get("user")
            if user:
                distinct_id = user.get("sub", distinct_id)
    except Exception:
        pass  # Session may not be attached; fall back to SERVER_ACTOR
    analytics.capture_exception(
        exc,
        distinct_id=distinct_id,
        properties={"path": request.url.path, "method": request.method},
    )
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return _error_template(request, "errors/500.html", 500)


# Production middleware (add_middleware is last-added = outermost)
app.add_middleware(CacheControlMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware, path_prefix="/api/search")

# Session + auth middleware (no-op when auth is not configured)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.auth0_client_secret or settings.oidc_client_secret or "dev-not-secret",
)

# Auth routes
app.include_router(auth_router)
app.include_router(device_router)
app.include_router(refresh_router)
app.include_router(github_auth_router)
app.include_router(api_key_router)

# Mount static files — check source tree first, then Docker workdir
_static_dir = Path(__file__).resolve().parent.parent.parent / "static"
if not _static_dir.is_dir():
    _static_dir = Path("/app/static")
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# Mount VitePress docs site at /docs — check source tree first, then Docker workdir
# Subclass StaticFiles to support clean URLs (e.g. /reference/cli → /reference/cli.html)
class CleanURLStaticFiles(StaticFiles):
    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        full_path, stat_result = super().lookup_path(path)
        if stat_result is not None:
            return full_path, stat_result
        # Try appending .html for clean URL support
        if not path.endswith("/"):
            full_path, stat_result = super().lookup_path(path + ".html")
            if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
                return full_path, stat_result
        return "", None


_docs_dist = Path(__file__).resolve().parent.parent.parent / "docs-site" / ".vitepress" / "dist"
if not _docs_dist.is_dir():
    _docs_dist = Path("/app/docs-site/.vitepress/dist")
if _docs_dist.is_dir():
    app.mount("/docs", CleanURLStaticFiles(directory=str(_docs_dist), html=True), name="docs")

# Webhook routes for real-time reverse sync from ticket systems
app.include_router(webhooks_router)

# Billing routes
app.include_router(billing_router)
app.include_router(billing_webhook_router)

# Mount web UI routes
app.include_router(web_router)
app.include_router(app_router)
app.include_router(analytics_router)
app.include_router(editor_router)
app.include_router(profile_router)
app.include_router(ticket_router)
# SPA catch-all must be last — serves Vue app for unmatched /app/* routes
app.include_router(spa_router)


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request) -> Response:
    """Readiness probe — checks DB health when pool is configured."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
        except Exception as exc:
            analytics.track(
                "health_check_failed",
                properties={"check_type": "readiness", "error_message": str(exc)},
            )
            return Response(
                content=json.dumps({"status": "error", "detail": "database unhealthy"}),
                status_code=503,
                media_type="application/json",
            )
    return Response(
        content=json.dumps({"status": "ok"}),
        status_code=200,
        media_type="application/json",
    )


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    """Receive and process GitHub webhook events."""
    body = await request.body()

    # Verify signature
    signature = request.headers.get("x-hub-signature-256", "") or request.headers.get(
        "x-hub-signature", ""
    )
    if not verify_signature(body, signature, settings.gh_webhook_secret):
        return Response(content="Invalid signature", status_code=401)

    event = request.headers.get("x-github-event", "")
    delivery = request.headers.get("x-github-delivery", "")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(content="Invalid JSON", status_code=400)

    action = payload.get("action", "")
    repo_name = (payload.get("repository") or {}).get("full_name", "?")
    logger.info(
        "webhook: event=%s%s repo=%s delivery=%s",
        event,
        f".{action}" if action else "",
        repo_name,
        delivery,
    )

    analytics.track(
        "webhook_received",
        properties={
            "event_type": event,
            "action": action,
            "repo": repo_name,
            "delivery_id": delivery,
        },
        groups={"organization": repo_name.split("/")[0]} if "/" in repo_name else None,
    )

    # Resolve client: use installation_id from payload if available, else default
    installation_id = (
        str((payload.get("installation") or {}).get("id", "")) or settings.gh_installation_id
    )
    base_client = _get_client()
    if installation_id and installation_id != base_client.installation_id:
        client = base_client.for_installation(installation_id)
    else:
        client = base_client

    try:
        await _route_event(client, event, action, payload)
    except InstallationNotFound:
        raise  # Let the app-level handler mark the installation as removed
    except Exception:
        logger.exception("Error handling webhook event=%s action=%s", event, action)

    return Response(content="OK", status_code=200)


async def _route_event(client: GitHubClient, event: str, action: str, payload: dict) -> None:
    """Route a webhook event to the appropriate handler."""
    if event == "push":
        from .github.handlers.on_push import on_push

        await on_push(client, payload)

    elif event == "pull_request":
        if action == "closed" and payload.get("pull_request", {}).get("merged"):
            from .github.handlers.on_pull_request_merged import on_pull_request_merged

            await on_pull_request_merged(client, payload)
        elif action in ("opened", "synchronize", "reopened"):
            from .github.handlers.on_pull_request import on_pull_request

            await on_pull_request(client, payload)

    elif event == "issue_comment":
        if action == "created":
            from .github.handlers.on_issue_comment import on_issue_comment

            await on_issue_comment(client, payload)

    elif event == "issues":
        from .github.handlers.on_issues import on_issues

        await on_issues(client, payload)

    elif event == "installation":
        from .github.handlers.on_installation import on_installation

        await on_installation(client, payload)

    elif event == "installation_repositories":
        from .github.handlers.on_installation_repos import on_installation_repositories

        await on_installation_repositories(client, payload)
