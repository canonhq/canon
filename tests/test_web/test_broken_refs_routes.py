"""FastAPI TestClient tests for the broken-refs read endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.main import app
from canon.web.cache import TTLCache

ORG = "test-org"


def _broken_row(ticket_ref: str, system: str = "github") -> dict:
    return {
        "installation_id": 1,
        "system": system,
        "ticket_ref": ticket_ref,
        "status": "broken",
        "consecutive_failures": 3,
        "last_error_kind": "not_found",
        "last_error_message": "not found",
        "first_failure_at": datetime.now(UTC),
        "last_check_at": datetime.now(UTC),
        "last_recheck_at": None,
        "dismissed_at": None,
        "dismissed_by": None,
    }


def _mock_github_client(installation_id: str = "1") -> AsyncMock:
    """Build a GitHub client mock with a controllable installation_id.

    The production endpoints call ``int(client.installation_id)``, so the
    attribute must be a real string (not a MagicMock auto-attr).
    """
    client = AsyncMock()
    client.installation_id = installation_id
    client.list_installation_repos = AsyncMock(return_value=[])
    client.list_directory = AsyncMock(return_value=[])
    client.get_file_content = AsyncMock(side_effect=Exception("not found"))
    client._get = AsyncMock(side_effect=Exception("not found"))
    return client


@pytest.fixture(autouse=True)
def _setup_app_state():
    """Set up app state for broken-refs route tests.

    Auth is disabled by default (no OIDC/Auth0 config), so all requests
    get ANONYMOUS_USER with full permissions — no auth mocking needed.
    """
    from canon.settings import Settings

    app.state.settings = Settings(web_org=ORG)
    app.state.cache = TTLCache(ttl_seconds=60)
    app.state.github_client = _mock_github_client()
    app.state.registry = None
    # ref_store starts unset; individual tests / the client_factory set it.
    if hasattr(app.state, "ref_store"):
        delattr(app.state, "ref_store")
    if hasattr(app.state, "content_cache_store"):
        delattr(app.state, "content_cache_store")
    if hasattr(app.state, "search_backend"):
        delattr(app.state, "search_backend")
    if hasattr(app.state, "search_index"):
        delattr(app.state, "search_index")
    with patch("canon.web.routes._get_spa_html", return_value=None):
        yield


@pytest.fixture
def ref_store_with_rows():
    store = AsyncMock()
    store.list_broken = AsyncMock(
        return_value=[
            _broken_row("o/r1#1"),
            _broken_row("o/r1#2"),
            _broken_row("o/r2#3"),
            _broken_row("PROJ-1", system="jira"),
        ]
    )
    return store


@pytest.fixture
def empty_ref_store():
    store = AsyncMock()
    store.list_broken = AsyncMock(return_value=[])
    return store


@pytest.fixture
def client_factory():
    """Build an httpx AsyncClient with optional ref_store wiring.

    Pass ``ref_store=None`` to test the "no ref_store" fallback paths,
    or pass a configured AsyncMock to exercise the populated paths.
    """

    def _factory(*, ref_store: object | None = None) -> AsyncClient:
        if ref_store is not None:
            app.state.ref_store = ref_store
        elif hasattr(app.state, "ref_store"):
            delattr(app.state, "ref_store")
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        )

    return _factory


class TestBrokenRefsList:
    async def test_returns_empty_when_no_ref_store(self, client_factory):
        client = client_factory(ref_store=None)
        r = await client.get(f"/app/{ORG}/api/broken-refs")
        assert r.status_code == 200
        assert r.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}

    async def test_returns_rows(self, client_factory, ref_store_with_rows):
        client = client_factory(ref_store=ref_store_with_rows)
        r = await client.get(f"/app/{ORG}/api/broken-refs?limit=10")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 4
        assert len(body["items"]) == 4
        assert body["limit"] == 10

    async def test_filters_by_system(self, client_factory, ref_store_with_rows):
        client = client_factory(ref_store=ref_store_with_rows)
        r = await client.get(f"/app/{ORG}/api/broken-refs?system=github")
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["system"] == "github"
        assert r.json()["total"] == 3  # 3 github rows

    async def test_filters_by_repo(self, client_factory, ref_store_with_rows):
        client = client_factory(ref_store=ref_store_with_rows)
        r = await client.get(f"/app/{ORG}/api/broken-refs?repo=o/r1")
        assert r.status_code == 200
        assert r.json()["total"] == 2  # both o/r1#... rows
        for item in r.json()["items"]:
            assert item["ticket_ref"].startswith("o/r1#")

    async def test_returns_empty_with_empty_ref_store(self, client_factory, empty_ref_store):
        client = client_factory(ref_store=empty_ref_store)
        r = await client.get(f"/app/{ORG}/api/broken-refs")
        assert r.status_code == 200
        assert r.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}

    async def test_status_dismissed_surfaces_dismissed_rows(self, client_factory):
        """When the caller asks for status=dismissed, rows return with dismissed=True."""
        ref_store = AsyncMock()

        # Note: list_broken's status arg drives which rows the store
        # returns. Tests stub that contract: when called with
        # status='dismissed', the store returns dismissed rows.
        async def _list(installation_id, status="broken"):
            if status == "dismissed":
                return [
                    {
                        "installation_id": 1,
                        "system": "github",
                        "ticket_ref": "o/r#9",
                        "status": "dismissed",
                        "consecutive_failures": 3,
                        "last_error_kind": "not_found",
                        "last_error_message": "not found",
                        "first_failure_at": datetime.now(UTC),
                        "last_check_at": datetime.now(UTC),
                        "last_recheck_at": None,
                        "dismissed_at": datetime.now(UTC),
                        "dismissed_by": "auth0|admin",
                    }
                ]
            return []

        ref_store.list_broken = AsyncMock(side_effect=_list)
        client = client_factory(ref_store=ref_store)
        r = await client.get(f"/app/{ORG}/api/broken-refs?status=dismissed")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["dismissed"] is True
        assert body["items"][0]["dismissed_by"] == "auth0|admin"


class TestBrokenRefsCount:
    async def test_returns_zero_when_no_ref_store(self, client_factory):
        client = client_factory(ref_store=None)
        r = await client.get(f"/app/{ORG}/api/broken-refs/count")
        assert r.status_code == 200
        assert r.json() == {"count": 0}

    async def test_returns_count(self, client_factory, ref_store_with_rows):
        client = client_factory(ref_store=ref_store_with_rows)
        r = await client.get(f"/app/{ORG}/api/broken-refs/count")
        assert r.status_code == 200
        assert r.json() == {"count": 4}


class TestDashboardAugmentation:
    async def test_dashboard_includes_total_broken_refs(self, client_factory, ref_store_with_rows):
        client = client_factory(ref_store=ref_store_with_rows)
        r = await client.get(f"/app/{ORG}/api/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert "total_broken_refs" in body
        assert isinstance(body["total_broken_refs"], int)
