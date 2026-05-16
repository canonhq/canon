"""FastAPI application — webhook routes, health checks, web UI."""

from __future__ import annotations

import importlib.util
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

# Cloud-only modules — optional in FOSS builds.
# Use find_spec instead of try/except ImportError so transitive dependency
# failures (broken installs, renamed symbols) propagate naturally.
if importlib.util.find_spec("canon.admin") is not None:
    from .admin.audit import AuditStore
    from .admin.routes import router as admin_router
    from .admin.store import AdminStore
else:
    logging.getLogger(__name__).info(
        "Admin module not available — skipping admin routes (FOSS build)"
    )
    AuditStore = None  # type: ignore[assignment, misc]
    admin_router = None  # type: ignore[assignment]
    AdminStore = None  # type: ignore[assignment, misc]

if importlib.util.find_spec("canon.alerts.slack") is not None:
    from .alerts.slack import SlackAlerter
else:
    logging.getLogger(__name__).info(
        "SlackAlerter not available — Slack alerts disabled (FOSS build)"
    )
    SlackAlerter = None  # type: ignore[assignment, misc]

if importlib.util.find_spec("canon.billing.routes") is not None:
    from .billing.routes import router as billing_router
    from .billing.routes import webhook_router as billing_webhook_router
else:
    logging.getLogger(__name__).info("Billing routes not available — skipping billing (FOSS build)")
    billing_router = None  # type: ignore[assignment]
    billing_webhook_router = None  # type: ignore[assignment]

from .auth.api_key_routes import api_key_router
from .auth.device_routes import device_router
from .auth.github_routes import github_auth_router
from .auth.middleware import AuthMiddleware
from .auth.oauth_integrations import oauth_integration_router
from .auth.refresh_routes import refresh_router
from .auth.routes import auth_router
from .db import (
    AgentStore,
    ErrorStore,
    InstallationRegistry,
    IntegrationStore,
    SessionStore,
    UserConnectionStore,
    UserStore,
    close_pool,
    create_pool,
    ensure_schema,
)
from .github.client import GitHubClient, InstallationNotFound
from .github.verify import verify_signature
from .settings import Settings
from .web.analytics_routes import analytics_router
from .web.api_v1_actions import api_v1_actions_router
from .web.cache import TTLCache
from .web.editor_routes import editor_router
from .web.integration_routes import integration_router
from .web.middleware import (
    CacheControlMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityBlockMiddleware,
)
from .web.profile_routes import profile_router
from .web.review_routes import router as review_router
from .web.routes import app_router, spa_router
from .web.routes import router as web_router
from .web.sync_routes import sync_router
from .web.ticket_routes import ticket_router
from .webhooks.router import router as webhooks_router

logger = logging.getLogger(__name__)

settings = Settings()

# Configure root logger so canon's own logger.info() messages reach stdout.
# Without this, Python's default WARNING root level silently drops every
# startup diagnostic ("DB pool initialised", "Slack bot mounted at...",
# "Slack bot not configured — /slack/events will return 503") — which is
# exactly how a config-drift bug stayed invisible in production for weeks
# (see PR #701). The LOG_LEVEL env var is wired into Settings already; this
# is the missing line that actually applies it.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Tame noisy 3rd-party libraries that default to DEBUG/INFO themselves.
for _noisy in ("httpx", "httpcore", "asyncpg", "urllib3", "slack_bolt"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

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

    # SRE Slack alerter (cloud-only)
    app.state.slack_alerter = None
    if SlackAlerter is not None:
        app.state.slack_alerter = SlackAlerter(
            webhook_url=settings.slack_alerts_webhook_url,
        )
        if app.state.slack_alerter.enabled:
            logger.info("Slack alerts enabled (channel configured)")
        elif settings.environment == "production":
            # Symmetric counterpart to the success log above. SRE alerts going
            # silently offline in production is the worst-case observability
            # failure (no way to alert that alerts are broken), so warn loudly
            # and let it show up in any log search.
            logger.warning(
                "SlackAlerter disabled — SLACK_ALERTS_WEBHOOK_URL is empty in "
                "production. SRE alerting is offline."
            )

    # OTel logs + tracing to PostHog (opt-in)
    if settings.posthog_logs_enabled:
        otel_logging.init(
            settings.posthog_key,
            min_level=settings.posthog_logs_min_level,
            posthog_host=settings.posthog_host,
        )
        otel_logging.instrument_fastapi(app)

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
    from .slack import SLACK_AVAILABLE, IdentityStore

    if SLACK_AVAILABLE and IdentityStore is not None:
        app.state.identity_store = IdentityStore(db_pool=getattr(app.state, "db_pool", None))
    else:
        app.state.identity_store = None

    app.state.github_client = _get_client()

    # CANON.yaml config — loaded once at startup for workspace-level features
    # (e.g. slack.work_context.enabled flag read by the smarter-bot mentions handler).
    # Slack handlers run at workspace level, not per-repo, so we load the local
    # repo's CANON.yaml as the baseline.  If none exists, CanonConfig() gives
    # safe defaults (all feature flags off).
    from .config.parse import CanonConfig as _CanonConfig
    from .config.parse import parse_canon_yaml as _parse_canon_yaml

    _canon_yaml_path = Path(__file__).resolve().parents[2] / "CANON.yaml"
    if _canon_yaml_path.is_file():
        try:
            app.state.canon_config = _parse_canon_yaml(_canon_yaml_path.read_text()).config
            logger.info("CANON.yaml loaded from %s", _canon_yaml_path)
        except Exception:
            logger.warning("Failed to parse CANON.yaml — using defaults", exc_info=True)
            app.state.canon_config = _CanonConfig()
    else:
        app.state.canon_config = _CanonConfig()
        logger.debug("No CANON.yaml found at %s — using default CanonConfig", _canon_yaml_path)

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
    app.state.session_evidence_store = None
    app.state.connection_store = None
    app.state.integration_store = None
    app.state.stripe_client = None
    app.state.billing_service = None
    app.state.admin_store = None
    app.state.audit_store = None
    app.state.pr_review_store = None
    if settings.database_url:
        try:
            pool = await create_pool(settings.database_url)
            await ensure_schema(pool, settings.database_url)
            app.state.db_pool = pool
            app.state.registry = InstallationRegistry(pool)
            app.state.agent_store = AgentStore(pool)
            app.state.error_store = ErrorStore(pool)
            from .db.session_evidence_store import SessionEvidenceStore

            app.state.session_evidence_store = SessionEvidenceStore(pool)
            app.state.user_store = UserStore(pool)
            app.state.session_store = SessionStore(pool)
            encryption_key = settings.byok_encryption_key
            if encryption_key:
                app.state.connection_store = UserConnectionStore(pool, encryption_key)
                app.state.integration_store = IntegrationStore(pool, encryption_key)
            if AdminStore is not None:
                app.state.admin_store = AdminStore(
                    pool,
                    provider=app.state.oidc_provider,
                    cache=app.state.cache,
                )
            from .db.pr_review_store import PRReviewStore

            app.state.pr_review_store = PRReviewStore(pool)
            if AuditStore is not None:
                app.state.audit_store = AuditStore(pool)
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
    app.state.content_cache_store = None
    app.state.ref_store = None
    if app.state.db_pool is not None:
        app.state.search_index = SearchIndex(app.state.db_pool)
        logger.info("Search index initialised")

        # Content cache store (requires DB pool + feature flag)
        if settings.content_cache_enabled:
            from .db.content_cache_store import ContentCacheStore

            app.state.content_cache_store = ContentCacheStore(app.state.db_pool)
            logger.info("Content cache store initialised")

        # Broken-ref tracking — independent of content_cache_enabled. The
        # store is cheap (no per-request work) and the broken-ref display
        # depends only on cron-written rows.
        from .db.ticket_ref_status_store import TicketRefStatusStore

        app.state.ref_store = TicketRefStatusStore(app.state.db_pool)
        logger.info("Ticket ref status store initialised")

    # OpenSearch client (optional — feature-flagged)
    from .search.backend import build_backend
    from .search.opensearch_client import build_client_from_settings

    app.state.opensearch_client = build_client_from_settings(settings)
    if app.state.opensearch_client.is_enabled:
        try:
            await app.state.opensearch_client.ensure_indexes()
            logger.info("OpenSearch client initialised")
        except Exception:
            logger.warning("OpenSearch index bootstrap failed", exc_info=True)

    app.state.search_backend = build_backend(
        search_index=app.state.search_index,
        opensearch_client=app.state.opensearch_client,
        opensearch_enabled=settings.opensearch_enabled,
    )
    if app.state.search_backend is not None:
        logger.info(
            "Search backend: %s",
            type(app.state.search_backend).__name__,
        )
    elif settings.opensearch_enabled:
        # Misconfig surface: flag is on but the backend couldn't be built
        # (most likely opensearch-py import failure or client init error
        # already logged above). Reads will silently fall back to the raw
        # SearchIndex via _get_search_backend; surface this so operators
        # don't see "OpenSearch enabled" in config and Postgres-shaped
        # metrics in the dashboard.
        logger.warning(
            "OPENSEARCH_ENABLED=true but search backend is None — "
            "reads will fall back to Postgres SearchIndex"
        )

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
            search_backend=getattr(app.state, "search_backend", None),
            embed_client=app.state.embed_client,
            github_client=app.state.github_client,
            cache=app.state.cache,
            settings=settings,
            agent_store=getattr(app.state, "agent_store", None),
            session_evidence_store=getattr(app.state, "session_evidence_store", None),
            content_cache_store=getattr(app.state, "content_cache_store", None),
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
            from .slack import NotificationConfig, NotificationDispatcher

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

        # slack_identity_store — per-workspace Slack→GitHub identity mapping.
        # Re-instantiated here (after db_pool is available) so it persists across
        # restarts.  The earlier app.state.identity_store is a legacy alias kept
        # for backward-compat; slack_identity_store is what mentions.py reads.
        from .slack import SLACK_AVAILABLE as _SLACK_AVAILABLE
        from .slack import IdentityStore as _IdentityStore

        if _SLACK_AVAILABLE and _IdentityStore is not None:
            app.state.slack_identity_store = _IdentityStore(db_pool=app.state.db_pool)
            logger.info("Slack identity store initialised (db=%s)", app.state.db_pool is not None)
        else:
            app.state.slack_identity_store = None

        # slack_spec_loader — loads and caches spec data from the configured repo.
        # Requires GITHUB_OWNER + GITHUB_REPO to be set.  If either is absent the
        # loader is left as None and _get_spec_loader() in mentions.py no-ops safely.
        #
        # IMPORTANT: we obtain the loader via commands._get_spec_loader() (the factory
        # that manages the module-level _loaders cache) rather than constructing a new
        # SpecLoader directly.  This ensures app.state.slack_spec_loader is the *same*
        # object stored in commands._loaders[(owner, repo)], so that a single call to
        # invalidate_spec_cache() in the push handler invalidates both paths at once.
        from .slack import SLACK_AVAILABLE as _SLACK_AVAIL2
        from .slack import SpecLoader as _SpecLoader

        if (
            _SLACK_AVAIL2
            and _SpecLoader is not None
            and settings.github_owner
            and settings.github_repo
        ):
            try:
                from canon_slack.commands import _get_spec_loader as _commands_get_loader

                app.state.slack_spec_loader = _commands_get_loader(
                    app.state.github_client,
                    settings.github_owner,
                    settings.github_repo,
                )
            except Exception:
                # Fallback: construct directly if the commands import fails (e.g. in
                # FOSS builds that ship canon_slack but not the full extension path).
                logger.warning(
                    "Failed to obtain shared SpecLoader from commands._get_spec_loader "
                    "— creating a standalone instance (cache invalidation may diverge)",
                    exc_info=True,
                )
                app.state.slack_spec_loader = _SpecLoader(
                    github_client=app.state.github_client,
                    owner=settings.github_owner,
                    repo=settings.github_repo,
                )
            logger.info(
                "Slack spec loader initialised (repo=%s/%s)",
                settings.github_owner,
                settings.github_repo,
            )
        else:
            app.state.slack_spec_loader = None
            if _SLACK_AVAIL2 and _SpecLoader is not None:
                logger.info("Slack spec loader not initialised — GITHUB_OWNER/GITHUB_REPO not set")
    else:
        app.state.slack_identity_store = None
        app.state.slack_spec_loader = None
        msg = (
            "Slack bot not configured — SLACK_BOT_TOKEN or SLACK_SIGNING_SECRET "
            "is empty; /slack/events would return 503 and notification dispatcher "
            "would silently no-op"
        )
        if settings.environment == "production":
            # In production a missing slack token is a config-drift bug
            # (Doppler sync failure, Helm chart misconfig, expired token,
            # missing envFrom mount — see PR #701). Fail fast so the pod
            # CrashLoopBackoff surfaces the problem to operators rather than
            # silently 503-ing every Slack request indefinitely. Self-hosted
            # / FOSS / dev environments keep the soft fall-through.
            raise RuntimeError(msg + " (refusing to start in production)")
        logger.warning(msg)
        try:
            analytics.track(
                "slack_bot_disabled_at_startup",
                properties={
                    "has_bot_token": bool(settings.slack_bot_token),
                    "has_signing_secret": bool(settings.slack_signing_secret),
                    "environment": settings.environment,
                },
            )
        except Exception:
            logger.debug("Failed to track slack_bot_disabled_at_startup", exc_info=True)

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
    slack_alerter = getattr(app.state, "slack_alerter", None)
    if slack_alerter is not None:
        await slack_alerter.close()
    otel_logging.shutdown()
    analytics.shutdown()
    opensearch_client = getattr(app.state, "opensearch_client", None)
    if opensearch_client is not None:
        await opensearch_client.close()
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
app.add_middleware(SecurityBlockMiddleware)

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
app.include_router(oauth_integration_router)
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

# Billing routes (cloud-only)
if billing_router is not None:
    app.include_router(billing_router)
if billing_webhook_router is not None:
    app.include_router(billing_webhook_router)

# Mount web UI routes
app.include_router(web_router)
app.include_router(app_router)
app.include_router(analytics_router)
app.include_router(editor_router)
app.include_router(profile_router)
app.include_router(integration_router)

# Mount public v1 API routes consumed by GitHub Actions
app.include_router(api_v1_actions_router)
app.include_router(ticket_router)
app.include_router(sync_router)
app.include_router(review_router)
# Admin API router must come before the SPA catch-all (cloud-only)
if admin_router is not None:
    app.include_router(admin_router)
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
    # Check content cache freshness
    content_cache_store = getattr(request.app.state, "content_cache_store", None)
    stale_repos = []
    if content_cache_store is not None:
        try:
            stale_repos = await content_cache_store.get_stale_repos(max_age_hours=2)
        except Exception:
            logger.debug("Failed to check content cache staleness", exc_info=True)

    # Check OpenSearch reachability when enabled
    opensearch_client = getattr(request.app.state, "opensearch_client", None)
    opensearch_status = None
    if opensearch_client is not None and opensearch_client.is_enabled:
        opensearch_status = "ok" if await opensearch_client.ping() else "unreachable"

    result = {"status": "ok"}
    if stale_repos:
        result["content_cache_stale_repos"] = len(stale_repos)
    if opensearch_status is not None:
        result["opensearch"] = opensearch_status

    # OpenSearch reachability is informational only — never 503. Search
    # is a partial dependency (Postgres remains source of truth and
    # serves the read fallback), so failing readiness on an OpenSearch
    # blip would take every pod out of the Service endpoint slice
    # simultaneously and DoS unrelated paths (webhooks, auth, billing,
    # agent runs). Operators should alert on the `opensearch` field via
    # PostHog / Prometheus instead.
    return Response(
        content=json.dumps(result),
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
