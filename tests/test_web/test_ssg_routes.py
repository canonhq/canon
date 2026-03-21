"""Tests for SSG prerendering and marketing route serving.

Covers:
- _get_spa_html route-specific file lookup (SSG)
- _serve_public_spa OG tag and canonical URL injection
- Public marketing routes (pricing, changelog)
- Waitlist signup endpoint
- End-to-end integration: real SSG files → route handler → meta injection → response
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.main import app
from canon.web.cache import TTLCache
from canon.web.routes import _get_spa_html as _real_get_spa_html

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _setup_app_state():
    """Set up app state, patching _get_spa_html to None by default."""
    from canon.settings import Settings

    app.state.settings = Settings(web_org="test-org")
    app.state.cache = TTLCache(ttl_seconds=60)
    with patch("canon.web.routes._get_spa_html", return_value=None):
        yield


@pytest.fixture
def client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
    )


SPA_HTML = "<html><head></head><body><div id='app'></div></body></html>"
PRICING_HTML = "<html><head></head><body><div id='app'>Pricing content</div></body></html>"
CHANGELOG_HTML = "<html><head></head><body><div id='app'>Changelog content</div></body></html>"


# ---------------------------------------------------------------------------
# _get_spa_html unit tests
# ---------------------------------------------------------------------------


def _reset_spa_cache():
    """Reset the module-level SPA cache so each test starts clean."""
    import canon.web.routes as mod

    mod._spa_checked = False
    mod._spa_path = None
    mod._spa_index_html = None
    mod._spa_mtime = 0
    mod._ssg_cache.clear()


class TestGetSpaHtml:
    """Unit tests for _get_spa_html route-specific file lookup.

    These tests call the real _get_spa_html, overriding the autouse fixture
    that patches it to None for the route-level integration tests.
    """

    @pytest.fixture(autouse=True)
    def _unpatch_get_spa_html(self):
        """Override the module-level autouse fixture by re-patching with the real function."""
        from canon.settings import Settings

        app.state.settings = Settings(web_org="test-org")
        app.state.cache = TTLCache(ttl_seconds=60)
        _reset_spa_cache()
        with patch("canon.web.routes._get_spa_html", wraps=_real_get_spa_html):
            yield
        _reset_spa_cache()

    def test_returns_none_when_no_spa_built(self):
        """Returns None when the SPA index.html doesn't exist."""
        import canon.web.routes as mod

        with patch.object(mod, "_find_spa_index", return_value=None):
            result = mod._get_spa_html()
        assert result is None

    def test_returns_main_index_for_root_route(self, tmp_path: Path):
        """For route='/', returns the main index.html."""
        import canon.web.routes as mod

        index = tmp_path / "index.html"
        index.write_text(SPA_HTML)

        with patch.object(mod, "_find_spa_index", return_value=index):
            result = mod._get_spa_html(route="/")
        assert result == SPA_HTML

    def test_returns_route_specific_html_file(self, tmp_path: Path):
        """For route='/pricing', returns pricing.html if it exists."""
        import canon.web.routes as mod

        index = tmp_path / "index.html"
        index.write_text(SPA_HTML)
        pricing = tmp_path / "pricing.html"
        pricing.write_text(PRICING_HTML)

        with patch.object(mod, "_find_spa_index", return_value=index):
            result = mod._get_spa_html(route="/pricing")
        assert result == PRICING_HTML

    def test_returns_route_specific_index_html(self, tmp_path: Path):
        """For route='/docs', returns docs/index.html if it exists."""
        import canon.web.routes as mod

        index = tmp_path / "index.html"
        index.write_text(SPA_HTML)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        docs_index = docs_dir / "index.html"
        docs_index.write_text("<html><head></head><body>Docs</body></html>")

        with patch.object(mod, "_find_spa_index", return_value=index):
            result = mod._get_spa_html(route="/docs")
        assert "Docs" in result

    def test_prefers_flat_html_over_directory_index(self, tmp_path: Path):
        """pricing.html is preferred over pricing/index.html."""
        import canon.web.routes as mod

        index = tmp_path / "index.html"
        index.write_text(SPA_HTML)
        flat = tmp_path / "pricing.html"
        flat.write_text("flat version")
        dir_path = tmp_path / "pricing"
        dir_path.mkdir()
        (dir_path / "index.html").write_text("directory version")

        with patch.object(mod, "_find_spa_index", return_value=index):
            result = mod._get_spa_html(route="/pricing")
        assert result == "flat version"

    def test_falls_back_to_main_index_when_no_route_file(self, tmp_path: Path):
        """Falls back to main index.html when no route-specific file exists."""
        import canon.web.routes as mod

        index = tmp_path / "index.html"
        index.write_text(SPA_HTML)

        with patch.object(mod, "_find_spa_index", return_value=index):
            result = mod._get_spa_html(route="/nonexistent")
        assert result == SPA_HTML

    def test_path_traversal_returns_fallback(self, tmp_path: Path):
        """Route with path traversal sequences falls back to main index."""
        import canon.web.routes as mod

        index = tmp_path / "index.html"
        index.write_text(SPA_HTML)
        # Create a file outside the SPA directory that should NOT be reachable
        secret = tmp_path.parent / "secret.html"
        secret.write_text("SECRET DATA")

        with patch.object(mod, "_find_spa_index", return_value=index):
            result = mod._get_spa_html(route="/../secret")
        # Should fall back to main index, never serve the secret file
        assert "SECRET DATA" not in (result or "")
        assert result == SPA_HTML

        # Clean up
        secret.unlink(missing_ok=True)

    def test_mtime_cache_invalidation(self, tmp_path: Path):
        """Re-reads the file when mtime changes."""
        import canon.web.routes as mod

        index = tmp_path / "index.html"
        index.write_text("version 1")

        with patch.object(mod, "_find_spa_index", return_value=index):
            result1 = mod._get_spa_html(route="/")
            assert result1 == "version 1"

            # Modify file
            index.write_text("version 2")
            # Force mtime to be different (filesystem resolution)
            os.utime(index, (index.stat().st_mtime + 1, index.stat().st_mtime + 1))

            result2 = mod._get_spa_html(route="/")
            assert result2 == "version 2"

    def test_ssg_route_mtime_cache_invalidation(self, tmp_path: Path):
        """Route-specific SSG files are re-read when their mtime changes."""
        import canon.web.routes as mod

        index = tmp_path / "index.html"
        index.write_text(SPA_HTML)
        pricing = tmp_path / "pricing.html"
        pricing.write_text("pricing v1")

        with patch.object(mod, "_find_spa_index", return_value=index):
            result1 = mod._get_spa_html(route="/pricing")
            assert result1 == "pricing v1"

            # Modify the route-specific file
            pricing.write_text("pricing v2")
            os.utime(pricing, (pricing.stat().st_mtime + 1, pricing.stat().st_mtime + 1))

            result2 = mod._get_spa_html(route="/pricing")
            assert result2 == "pricing v2"

    def test_ssg_cache_fifo_eviction(self, tmp_path: Path):
        """SSG cache evicts oldest entry when full."""
        import canon.web.routes as mod

        index = tmp_path / "index.html"
        index.write_text(SPA_HTML)

        # Create more route files than _SSG_CACHE_MAX
        original_max = mod._SSG_CACHE_MAX
        mod._SSG_CACHE_MAX = 2
        try:
            for name in ["a", "b", "c"]:
                (tmp_path / f"{name}.html").write_text(f"content-{name}")

            with patch.object(mod, "_find_spa_index", return_value=index):
                mod._get_spa_html(route="/a")
                mod._get_spa_html(route="/b")
                assert len(mod._ssg_cache) == 2

                # Adding a third should evict the first
                mod._get_spa_html(route="/c")
                assert len(mod._ssg_cache) == 2

                # Verify "a" was evicted (its cache key is gone)
                a_key = str((tmp_path / "a.html").resolve())
                assert a_key not in mod._ssg_cache
        finally:
            mod._SSG_CACHE_MAX = original_max


# ---------------------------------------------------------------------------
# Public route integration tests
# ---------------------------------------------------------------------------


class TestLandingPageSsg:
    """Landing page with SSG-prerendered HTML."""

    async def test_injects_og_tags(self, client: AsyncClient):
        """OG tags are injected into the SPA shell."""
        with patch("canon.web.routes._get_spa_html", return_value=SPA_HTML):
            resp = await client.get("/")
        assert resp.status_code == 200
        assert '<meta property="og:title"' in resp.text
        assert '<meta name="description"' in resp.text
        assert "Spec-driven development" in resp.text

    async def test_injects_canonical_url(self, client: AsyncClient):
        """Canonical URL is injected for the landing page."""
        with patch("canon.web.routes._get_spa_html", return_value=SPA_HTML):
            resp = await client.get("/")
        assert resp.status_code == 200
        assert '<link rel="canonical" href="http://test/">' in resp.text

    async def test_injects_session_data(self, client: AsyncClient):
        """Session data with PostHog config is injected."""
        with patch("canon.web.routes._get_spa_html", return_value=SPA_HTML):
            resp = await client.get("/")
        assert "__CANON__" in resp.text
        assert '"user": null' in resp.text

    async def test_injects_twitter_card(self, client: AsyncClient):
        """Twitter card meta tags are injected."""
        with patch("canon.web.routes._get_spa_html", return_value=SPA_HTML):
            resp = await client.get("/")
        assert '<meta name="twitter:card" content="summary_large_image">' in resp.text


class TestPricingRoute:
    async def test_spa_served(self, client: AsyncClient):
        """Pricing page serves SPA shell with pricing-specific meta."""
        with patch("canon.web.routes._get_spa_html", return_value=SPA_HTML):
            resp = await client.get("/pricing")
        assert resp.status_code == 200
        assert "Pricing" in resp.text
        assert '<link rel="canonical" href="http://test/pricing">' in resp.text

    async def test_fallback_503_without_spa(self, client: AsyncClient):
        """Without SPA, pricing returns 503."""
        resp = await client.get("/pricing")
        assert resp.status_code == 503


class TestChangelogRoute:
    async def test_spa_served(self, client: AsyncClient):
        """Changelog page serves SPA shell with changelog-specific meta."""
        with patch("canon.web.routes._get_spa_html", return_value=SPA_HTML):
            resp = await client.get("/changelog")
        assert resp.status_code == 200
        assert "Changelog" in resp.text
        assert '<link rel="canonical" href="http://test/changelog">' in resp.text

    async def test_fallback_503_without_spa(self, client: AsyncClient):
        """Without SPA, changelog returns 503."""
        resp = await client.get("/changelog")
        assert resp.status_code == 503


class TestWaitlistEndpoint:
    """Waitlist signup POST endpoint."""

    async def test_valid_email_returns_201(self, client: AsyncClient):
        """Valid email returns 201 and fires analytics event."""
        with patch("canon.web.routes.analytics") as mock_analytics:
            resp = await client.post("/api/waitlist", json={"email": "test@example.com"})
        assert resp.status_code == 201
        assert resp.json() == {"ok": True}
        mock_analytics.track.assert_called_once()
        call_kwargs = mock_analytics.track.call_args
        assert call_kwargs[0][0] == "waitlist_signup"
        assert call_kwargs[1]["distinct_id"] == "test@example.com"

    async def test_invalid_email_returns_400(self, client: AsyncClient):
        """Invalid email is rejected."""
        resp = await client.post("/api/waitlist", json={"email": "not-an-email"})
        assert resp.status_code == 400
        assert "email" in resp.json().get("error", "").lower()

    async def test_empty_email_returns_400(self, client: AsyncClient):
        """Empty email string is rejected."""
        resp = await client.post("/api/waitlist", json={"email": ""})
        assert resp.status_code == 400

    async def test_missing_email_returns_400(self, client: AsyncClient):
        """Missing email field is rejected."""
        resp = await client.post("/api/waitlist", json={})
        assert resp.status_code == 400

    async def test_invalid_json_returns_400(self, client: AsyncClient):
        """Non-JSON body is rejected."""
        resp = await client.post(
            "/api/waitlist",
            content="not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400


class TestPublicSpaMetaTags:
    """Verify meta tag injection across all public routes."""

    @pytest.mark.parametrize(
        "path,expected_title",
        [
            ("/", "Canon"),
            ("/pricing", "Pricing"),
            ("/changelog", "Changelog"),
        ],
    )
    async def test_title_injected(self, client: AsyncClient, path: str, expected_title: str):
        """Each public route injects a route-specific title."""
        with patch("canon.web.routes._get_spa_html", return_value=SPA_HTML):
            resp = await client.get(path)
        assert resp.status_code == 200
        assert f"<title>{expected_title}" in resp.text

    @pytest.mark.parametrize("path", ["/", "/pricing", "/changelog"])
    async def test_og_image_injected(self, client: AsyncClient, path: str):
        """All public routes include the OG image meta tag."""
        with patch("canon.web.routes._get_spa_html", return_value=SPA_HTML):
            resp = await client.get(path)
        assert "og-image.png" in resp.text

    @pytest.mark.parametrize("path", ["/", "/pricing", "/changelog"])
    async def test_canonical_url_matches_path(self, client: AsyncClient, path: str):
        """Canonical URL matches the requested path."""
        with patch("canon.web.routes._get_spa_html", return_value=SPA_HTML):
            resp = await client.get(path)
        expected = f'<link rel="canonical" href="http://test{path}">'
        assert expected in resp.text


# ---------------------------------------------------------------------------
# End-to-end integration tests (real SSG files, no _get_spa_html mock)
# ---------------------------------------------------------------------------

REALISTIC_INDEX = (
    "<html><head><title>Canon</title></head><body>"
    "<div id='app'><h1>Canon — Spec-driven development</h1></div>"
    "</body></html>"
)
REALISTIC_PRICING = (
    "<html><head><title>Canon</title></head><body>"
    "<div id='app'><h1>Pricing — Canon</h1><p>Self-hosted free forever.</p></div>"
    "</body></html>"
)
REALISTIC_CHANGELOG = (
    "<html><head><title>Canon</title></head><body>"
    "<div id='app'><h1>Changelog — Canon</h1><ul><li>v1.25</li></ul></div>"
    "</body></html>"
)


class TestSsgIntegration:
    """End-to-end tests: real SSG files on disk → FastAPI route → meta injection → HTTP response.

    These use a real temp directory mimicking the vite-ssg output structure
    and exercise the full pipeline without mocking _get_spa_html.
    """

    @pytest.fixture(autouse=True)
    def _setup_ssg_dir(self, tmp_path: Path):
        """Create a realistic SSG output directory and wire it into _get_spa_html."""
        from canon.settings import Settings

        app.state.settings = Settings(web_org="test-org")
        app.state.cache = TTLCache(ttl_seconds=60)

        # Build SSG output structure matching vite-ssg output
        (tmp_path / "index.html").write_text(REALISTIC_INDEX)
        (tmp_path / "pricing.html").write_text(REALISTIC_PRICING)
        (tmp_path / "changelog.html").write_text(REALISTIC_CHANGELOG)

        _reset_spa_cache()
        with (
            patch(
                "canon.web.routes._get_spa_html",
                side_effect=_real_get_spa_html,
            ),
            patch(
                "canon.web.routes._find_spa_index",
                return_value=tmp_path / "index.html",
            ),
        ):
            yield
        _reset_spa_cache()

    @pytest.fixture
    def client(self):
        return AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
        )

    async def test_landing_serves_index_with_meta(self, client: AsyncClient):
        """GET / reads real index.html and injects OG tags + session data."""
        resp = await client.get("/")
        assert resp.status_code == 200
        # Original SSG content preserved
        assert "Spec-driven development" in resp.text
        # Meta tags injected
        assert "<title>Canon" in resp.text
        assert '<meta property="og:title"' in resp.text
        assert '<link rel="canonical" href="http://test/">' in resp.text
        # Session data injected
        assert "__CANON__" in resp.text
        assert '"user": null' in resp.text

    async def test_pricing_serves_route_specific_file(self, client: AsyncClient):
        """GET /pricing reads pricing.html (not index.html) and injects pricing meta."""
        resp = await client.get("/pricing")
        assert resp.status_code == 200
        # Route-specific SSG content
        assert "Self-hosted free forever" in resp.text
        # Pricing-specific meta
        assert "<title>Pricing" in resp.text
        assert '<link rel="canonical" href="http://test/pricing">' in resp.text
        # Should NOT contain landing page content
        assert "Spec-driven development" not in resp.text

    async def test_changelog_serves_route_specific_file(self, client: AsyncClient):
        """GET /changelog reads changelog.html and injects changelog meta."""
        resp = await client.get("/changelog")
        assert resp.status_code == 200
        assert "v1.25" in resp.text
        assert "<title>Changelog" in resp.text
        assert '<link rel="canonical" href="http://test/changelog">' in resp.text

    async def test_no_duplicate_title_tags(self, client: AsyncClient):
        """SSG HTML with existing <title> gets it replaced, not duplicated."""
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.text.count("<title>") == 1

    async def test_session_data_structure(self, client: AsyncClient):
        """Session data contains required PostHog and auth fields."""
        resp = await client.get("/")
        assert resp.status_code == 200
        # Verify session data structure (embedded as JSON in script tag)
        text = resp.text
        assert '"posthog_key"' in text
        assert '"posthog_host"' in text
        assert '"auth_enabled"' in text
        assert '"auth_mode"' in text
        assert '"environment"' in text
        assert '"permissions": []' in text

    async def test_script_tag_escaping(self, client: AsyncClient):
        """Session data is properly escaped to prevent script injection."""
        resp = await client.get("/")
        # The session data should use unicode escapes for < > &
        # so a </script> in data can't break out
        assert "window.__CANON__" in resp.text
        # Raw < and > should NOT appear inside the script data value
        # (they get escaped to \u003c and \u003e)
        import re

        script_match = re.search(r"window\.__CANON__\s*=\s*(\{.*?\});", resp.text)
        assert script_match is not None
        script_data = script_match.group(1)
        assert "<" not in script_data
        assert ">" not in script_data

    async def test_html_content_type(self, client: AsyncClient):
        """Responses have text/html content type."""
        resp = await client.get("/")
        assert "text/html" in resp.headers["content-type"]

    async def test_og_image_uses_base_url(self, client: AsyncClient):
        """OG image URL is absolute, using the request's base URL."""
        resp = await client.get("/pricing")
        assert '<meta property="og:image" content="http://test/static/og-image.png">' in resp.text

    async def test_twitter_card_on_all_routes(self, client: AsyncClient):
        """Twitter card meta tags present on all marketing routes."""
        for path in ["/", "/pricing", "/changelog"]:
            resp = await client.get(path)
            assert '<meta name="twitter:card" content="summary_large_image">' in resp.text
