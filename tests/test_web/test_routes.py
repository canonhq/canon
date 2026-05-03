"""Tests for web routes."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.main import app
from canon.web.cache import TTLCache
from canon.web.models import DocDetail, RepoSummary


def _mock_client() -> AsyncMock:
    client = AsyncMock()
    client.list_installation_repos = AsyncMock(return_value=[])
    client.list_directory = AsyncMock(return_value=[])
    client.get_file_content = AsyncMock(side_effect=Exception("not found"))
    client._get = AsyncMock(side_effect=Exception("not found"))
    return client


@pytest.fixture(autouse=True)
def _setup_app_state():
    """Set up app state for all route tests.

    Patches _get_spa_html to return None so routes fall through to Jinja2
    templates (which is what most tests assert against).  SPA-specific tests
    use their own fixture to re-enable the SPA shell.
    """
    from canon.settings import Settings

    app.state.settings = Settings(web_org="test-org")
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.github_client = _mock_client()
    with patch("canon.web.routes._get_spa_html", return_value=None):
        yield


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
    )


class TestLandingPage:
    async def test_fallback_to_jinja(self, client: AsyncClient):
        """When the SPA is not built, falls back to Jinja2 landing template."""
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "Documentation that keeps up." in resp.text

    async def test_spa_shell_served(self, client: AsyncClient):
        """When the SPA is built, serves the SPA shell with session data."""
        spa_html = "<html><head></head><body><div id='app'></div></body></html>"
        with patch("canon.web.routes._get_spa_html", return_value=spa_html):
            resp = await client.get("/")
        assert resp.status_code == 200
        assert "__CANON__" in resp.text
        assert "posthog_key" in resp.text


class TestStaticFiles:
    async def test_brand_css(self, client: AsyncClient):
        resp = await client.get("/static/brand.css")
        assert resp.status_code == 200
        assert "--color-primary" in resp.text
        assert "html.dark" in resp.text


class TestDashboard:
    async def test_returns_200(self, client: AsyncClient):
        resp = await client.get("/app")
        assert resp.status_code == 200
        assert "Canon" in resp.text

    async def test_shows_org_name(self, client: AsyncClient):
        resp = await client.get("/app")
        assert "test-org" in resp.text

    async def test_empty_dashboard_shows_empty_state(self, client: AsyncClient):
        """Dashboard with no repos shows the empty state message."""
        resp = await client.get("/app/test-org/")
        assert resp.status_code == 200
        assert "No repositories found" in resp.text
        assert "Install the Canon GitHub App" in resp.text

    async def test_redirect_uses_session_org_when_web_org_empty(self):
        """When web_org is empty, /app/ redirects using the session user's org."""
        from canon.settings import Settings

        app.state.settings = Settings(web_org="")
        client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        )
        # Simulate an authenticated session with org_login
        resp = await client.get(
            "/app/",
            cookies={"session": ""},  # no session cookie
        )
        # Without a session, org is empty so redirect goes to /app//
        assert resp.status_code == 302

        # Now test with a real session — we need to set one via the app
        from starlette.testclient import TestClient

        with TestClient(app) as sync_client:
            # Set session data directly
            sync_client.get("/app/")  # initialize session
            with patch("canon.web.routes._get_user", return_value={"org_login": "my-org"}):
                resp = sync_client.get("/app/", follow_redirects=False)
                assert resp.status_code == 302
                assert resp.headers["location"] == "/app/my-org/"


class TestRepoDetail:
    async def test_not_found_returns_404(self, client: AsyncClient):
        resp = await client.get("/app/test-org/repos/org/nonexistent")
        assert resp.status_code == 404

    async def test_found_returns_200(self, client: AsyncClient):
        # Pre-populate cache
        detail = RepoSummary(
            owner="org",
            repo="repo1",
            full_name="org/repo1",
            description="Test",
            default_branch="main",
            has_specs=False,
            spec_count=0,
            specs=[],
            config=None,
            docs=[],
        )
        app.state.cache.set("repo:org/repo1", detail)
        resp = await client.get("/app/test-org/repos/org/repo1")
        assert resp.status_code == 200
        assert "org/repo1" in resp.text

    async def test_empty_docs_shows_note(self, client: AsyncClient):
        """Repo with specs but no docs shows an informational note."""
        from canon.web.models import SpecSummary

        detail = RepoSummary(
            owner="org",
            repo="repo2",
            full_name="org/repo2",
            description="Has specs",
            default_branch="main",
            has_specs=True,
            spec_count=1,
            specs=[
                SpecSummary(
                    file_path="docs/specs/auth.md",
                    title="Auth Spec",
                    status="draft",
                    owner="eng",
                    team="platform",
                    tags=[],
                    total_sections=1,
                    done_sections=0,
                    total_ac=0,
                    done_ac=0,
                )
            ],
            config=None,
            docs=[],
        )
        app.state.cache.set("repo:org/repo2", detail)
        resp = await client.get("/app/test-org/repos/org/repo2")
        assert resp.status_code == 200
        assert "No additional docs indexed for this repository" in resp.text


class TestSpecDetail:
    async def test_not_found_returns_404(self, client: AsyncClient):
        resp = await client.get("/app/test-org/specs/org/repo/docs/specs/nope.md")
        assert resp.status_code == 404


class TestSearch:
    async def test_returns_200(self, client: AsyncClient):
        resp = await client.get("/app/test-org/search?q=test")
        assert resp.status_code == 200

    async def test_htmx_partial(self, client: AsyncClient):
        resp = await client.get("/app/test-org/search?q=test", headers={"hx-request": "true"})
        assert resp.status_code == 200

    async def test_empty_search_shows_tips(self, client: AsyncClient):
        """Search with no results shows helpful tips."""
        resp = await client.get("/app/test-org/search?q=zzz_nonexistent_zzz")
        assert resp.status_code == 200
        assert "No specs found matching" in resp.text
        assert "Try a broader search term" in resp.text
        assert "Check spelling" in resp.text
        assert "Back to dashboard" in resp.text


class TestApiSearch:
    async def test_returns_json(self, client: AsyncClient):
        resp = await client.get("/app/test-org/api/search?q=test")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total" in data
        assert "facets" in data

    async def test_facets_structure(self, client: AsyncClient):
        resp = await client.get("/app/test-org/api/search")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data["facets"]
        assert "repo" in data["facets"]

    async def test_pagination(self, client: AsyncClient):
        resp = await client.get("/app/test-org/api/search?limit=5&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["results"], list)
        assert isinstance(data["total"], int)

    async def test_empty_results(self, client: AsyncClient):
        resp = await client.get("/app/test-org/api/search?q=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total"] == 0


class TestApiCoverage:
    async def test_returns_json(self, client: AsyncClient):
        resp = await client.get("/app/test-org/api/coverage")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "trend" in data
        assert "breakdown_by_repo" in data
        assert "breakdown_by_team" in data

    async def test_summary_fields(self, client: AsyncClient):
        resp = await client.get("/app/test-org/api/coverage")
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert "total_specs" in summary
        assert "total_sections" in summary
        assert "section_coverage_pct" in summary
        assert "health_score" in summary

    async def test_filter_by_repo(self, client: AsyncClient):
        resp = await client.get("/app/test-org/api/coverage?repo=org/repo")
        assert resp.status_code == 200

    async def test_filter_by_days(self, client: AsyncClient):
        resp = await client.get("/app/test-org/api/coverage?days=90")
        assert resp.status_code == 200


class TestHealthEndpoints:
    async def test_healthz(self, client: AsyncClient):
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_readyz_no_db(self, client: AsyncClient):
        """readyz returns 200 when no DB pool is configured."""
        app.state.db_pool = None
        resp = await client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_readyz_healthy_db(self, client: AsyncClient):
        """readyz returns 200 when DB pool is healthy."""
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_pool = MagicMock()

        @asynccontextmanager
        async def _acquire():
            yield mock_conn

        mock_pool.acquire = _acquire
        app.state.db_pool = mock_pool

        resp = await client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_readyz_unhealthy_db(self, client: AsyncClient):
        """readyz returns 503 when DB pool is unhealthy."""
        mock_pool = MagicMock()

        @asynccontextmanager
        async def _acquire():
            raise Exception("connection refused")
            yield  # pragma: no cover

        mock_pool.acquire = _acquire
        app.state.db_pool = mock_pool

        resp = await client.get("/readyz")
        assert resp.status_code == 503
        assert resp.json()["status"] == "error"

    async def test_readyz_omits_opensearch_when_disabled(self, client: AsyncClient):
        """A disabled OpenSearch client must not surface the field at all —
        the field's presence indicates the backend is configured."""
        app.state.db_pool = None
        opensearch = MagicMock()
        opensearch.is_enabled = False
        opensearch.ping = AsyncMock(return_value=False)
        app.state.opensearch_client = opensearch

        resp = await client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert "opensearch" not in body
        opensearch.ping.assert_not_called()
        app.state.opensearch_client = None

    async def test_readyz_reports_opensearch_ok_when_reachable(self, client: AsyncClient):
        """Enabled + ping=True → 200 with `opensearch: ok`."""
        app.state.db_pool = None
        opensearch = MagicMock()
        opensearch.is_enabled = True
        opensearch.ping = AsyncMock(return_value=True)
        app.state.opensearch_client = opensearch

        resp = await client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["opensearch"] == "ok"
        assert body["status"] == "ok"
        app.state.opensearch_client = None

    async def test_readyz_returns_200_with_unreachable_field_when_opensearch_down(
        self, client: AsyncClient
    ):
        """OpenSearch reachability is informational on /readyz, never 503.
        Search is a partial dependency — failing readiness on an OS blip
        would simultaneously remove every pod from the Service endpoint
        slice (shared cluster) and DoS webhooks/auth/billing/agent paths
        that don't depend on OpenSearch at all. Operators alert on the
        `opensearch` field via PostHog or Prometheus instead."""
        app.state.db_pool = None
        opensearch = MagicMock()
        opensearch.is_enabled = True
        opensearch.ping = AsyncMock(return_value=False)
        app.state.opensearch_client = opensearch

        resp = await client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["opensearch"] == "unreachable"
        app.state.opensearch_client = None


class TestGlobalExceptionHandler:
    """Unit tests for _global_exception_handler.

    Tested as a direct function call rather than via TestClient because
    BaseHTTPMiddleware + ExceptionMiddleware interaction makes integration
    testing finicky — the handler does fire in production for non-streaming
    routes, but AsyncClient propagates exceptions through middleware in tests.
    """

    async def test_returns_json_500_for_api_requests(self):
        from canon.main import _global_exception_handler

        request = MagicMock()
        request.url.path = "/api/test"
        request.method = "GET"
        request.headers = {"accept": "application/json"}
        request.session = {}

        exc = RuntimeError("boom")
        with patch("canon.main.analytics") as mock_analytics:
            resp = await _global_exception_handler(request, exc)

        assert resp.status_code == 500
        assert b"Internal server error" in resp.body
        mock_analytics.capture_exception.assert_called_once()
        call_args = mock_analytics.capture_exception.call_args
        assert call_args[0][0] is exc

    async def test_returns_html_500_for_browser_requests(self):
        from canon.main import _global_exception_handler

        request = MagicMock()
        request.url.path = "/app/org/specs"
        request.method = "GET"
        request.headers = {"accept": "text/html"}
        request.session = {}

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.body = b"Something went wrong"

        with (
            patch("canon.main.analytics"),
            patch("canon.web.routes.templates.TemplateResponse", return_value=mock_resp),
        ):
            resp = await _global_exception_handler(request, RuntimeError("boom"))

        assert resp.status_code == 500

    async def test_attributes_exception_to_authenticated_user(self):
        from canon.main import _global_exception_handler

        request = MagicMock()
        request.url.path = "/app/org/specs"
        request.method = "GET"
        request.headers = {"accept": "application/json"}
        request.session = {"user": {"sub": "auth0|user123"}}

        with patch("canon.main.analytics") as mock_analytics:
            await _global_exception_handler(request, RuntimeError("boom"))

        call_kwargs = mock_analytics.capture_exception.call_args[1]
        assert call_kwargs["distinct_id"] == "auth0|user123"


class TestWelcomePage:
    async def test_returns_200(self, client: AsyncClient):
        resp = await client.get("/app/test-org/welcome")
        assert resp.status_code == 200
        assert "Welcome" in resp.text
        assert "Setup checklist" in resp.text

    async def test_shows_install_button_when_no_registry(self, client: AsyncClient):
        old_registry = getattr(app.state, "registry", None)
        app.state.registry = None
        try:
            resp = await client.get("/app/test-org/welcome")
            assert resp.status_code == 200
            assert "Install on GitHub" in resp.text
        finally:
            app.state.registry = old_registry

    async def test_no_name_does_not_crash(self, client: AsyncClient):
        """Welcome page handles user with empty/missing name gracefully."""
        resp = await client.get("/app/test-org/welcome")
        assert resp.status_code == 200
        # With no session user name, should just say "Welcome" without a name
        assert "Welcome" in resp.text

    async def test_all_steps_complete(self, client: AsyncClient):
        """When app is installed and specs exist, all checklist steps show complete."""
        mock_registry = AsyncMock()
        mock_registry.get_installation_by_org = AsyncMock(return_value={"id": 1})
        old_registry = getattr(app.state, "registry", None)
        app.state.registry = mock_registry

        mock_overview = MagicMock()
        mock_overview.total_specs = 5

        try:
            with patch("canon.web.routes.get_org_overview", return_value=mock_overview):
                resp = await client.get("/app/test-org/welcome")
            assert resp.status_code == 200
            # Install button should NOT appear when app is installed
            assert "Install on GitHub" not in resp.text
            # Example specs link should NOT appear when specs exist
            assert "View example specs" not in resp.text
        finally:
            app.state.registry = old_registry

    async def test_skip_link(self, client: AsyncClient):
        resp = await client.get("/app/test-org/welcome")
        assert resp.status_code == 200
        assert "Skip to Dashboard" in resp.text
        assert "/app/test-org/" in resp.text


class TestDocDetail:
    async def test_not_found_returns_404(self, client: AsyncClient):
        resp = await client.get("/app/test-org/docs/org/repo/docs/guide.md")
        assert resp.status_code == 404

    async def test_found_returns_200(self, client: AsyncClient):
        detail = DocDetail(
            path="docs/guide.md",
            title="My Guide",
            rendered_html="<div>content</div>",
            repo_owner="org",
            repo_name="repo1",
            github_url="https://github.com/org/repo1/blob/main/docs/guide.md",
            doc_type="doc",
        )
        app.state.cache.set("doc:org/repo1/docs/guide.md", detail)
        resp = await client.get("/app/test-org/docs/org/repo1/docs/guide.md")
        assert resp.status_code == 200
        assert "My Guide" in resp.text
