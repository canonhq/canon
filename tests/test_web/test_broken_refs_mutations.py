"""FastAPI TestClient tests for the broken-refs mutating endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from canon.main import app
from canon.web.cache import TTLCache

ORG = "test-org"


def _broken_row(ticket_ref: str = "o/r#1", system: str = "github") -> dict:
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


class TestDismiss:
    async def test_404_when_row_missing(self, client_factory):
        ref_store = AsyncMock()
        ref_store.get = AsyncMock(return_value=None)
        ref_store.dismiss = AsyncMock()
        client = client_factory(ref_store=ref_store)
        r = await client.post(
            f"/app/{ORG}/api/broken-refs/dismiss",
            json={"system": "github", "ticket_ref": "o/r#1"},
        )
        assert r.status_code == 404
        ref_store.dismiss.assert_not_called()

    async def test_happy_path(self, client_factory):
        ref_store = AsyncMock()
        ref_store.get = AsyncMock(return_value=_broken_row())
        ref_store.dismiss = AsyncMock()
        client = client_factory(ref_store=ref_store)
        r = await client.post(
            f"/app/{ORG}/api/broken-refs/dismiss",
            json={"system": "github", "ticket_ref": "o/r#1"},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        ref_store.dismiss.assert_awaited_once()

    async def test_503_when_no_ref_store(self, client_factory):
        client = client_factory(ref_store=None)
        r = await client.post(
            f"/app/{ORG}/api/broken-refs/dismiss",
            json={"system": "github", "ticket_ref": "o/r#1"},
        )
        assert r.status_code == 503


class TestRecheck:
    async def test_404_when_row_missing(self, client_factory):
        ref_store = AsyncMock()
        ref_store.get = AsyncMock(return_value=None)
        ref_store.force_recheck = AsyncMock()
        client = client_factory(ref_store=ref_store)
        r = await client.post(
            f"/app/{ORG}/api/broken-refs/recheck",
            json={"system": "github", "ticket_ref": "o/r#1"},
        )
        assert r.status_code == 404

    async def test_happy_path(self, client_factory):
        ref_store = AsyncMock()
        ref_store.get = AsyncMock(return_value=_broken_row())
        ref_store.force_recheck = AsyncMock()
        client = client_factory(ref_store=ref_store)
        r = await client.post(
            f"/app/{ORG}/api/broken-refs/recheck",
            json={"system": "github", "ticket_ref": "o/r#1"},
        )
        assert r.status_code == 200
        ref_store.force_recheck.assert_awaited_once()


class TestRemoveTicketRef:
    async def test_404_when_section_missing(self, client_factory, monkeypatch):
        from canon.web import routes
        from canon.web.services import SectionNotFoundError

        monkeypatch.setattr(
            routes,
            "remove_ticket_ref",
            AsyncMock(side_effect=SectionNotFoundError("nope")),
        )
        client = client_factory()
        r = await client.post(
            f"/app/{ORG}/api/specs/o/r/docs%2Fspecs%2Ftest.md/sections/9999/remove-ticket-ref",
        )
        assert r.status_code == 404

    async def test_410_when_section_already_updated(self, client_factory, monkeypatch):
        from canon.web import routes
        from canon.web.services import SectionAlreadyUpdatedError

        monkeypatch.setattr(
            routes,
            "remove_ticket_ref",
            AsyncMock(side_effect=SectionAlreadyUpdatedError("stale")),
        )
        client = client_factory()
        r = await client.post(
            f"/app/{ORG}/api/specs/o/r/docs%2Fspecs%2Ftest.md/sections/1/remove-ticket-ref",
        )
        assert r.status_code == 410

    async def test_409_when_existing_pr(self, client_factory, monkeypatch):
        from canon.web import routes
        from canon.web.services import RemoveTicketRefResult

        monkeypatch.setattr(
            routes,
            "remove_ticket_ref",
            AsyncMock(
                return_value=RemoveTicketRefResult(
                    pr_number=7,
                    pr_url="https://github.com/o/r/pull/7",
                    already_existed=True,
                )
            ),
        )
        client = client_factory()
        r = await client.post(
            f"/app/{ORG}/api/specs/o/r/docs%2Fspecs%2Ftest.md/sections/1/remove-ticket-ref",
        )
        assert r.status_code == 409
        assert r.json() == {"pr_number": 7, "pr_url": "https://github.com/o/r/pull/7"}

    async def test_200_happy_path(self, client_factory, monkeypatch):
        from canon.web import routes
        from canon.web.services import RemoveTicketRefResult

        monkeypatch.setattr(
            routes,
            "remove_ticket_ref",
            AsyncMock(
                return_value=RemoveTicketRefResult(
                    pr_number=42,
                    pr_url="https://github.com/o/r/pull/42",
                    already_existed=False,
                )
            ),
        )
        client = client_factory()
        r = await client.post(
            f"/app/{ORG}/api/specs/o/r/docs%2Fspecs%2Ftest.md/sections/1/remove-ticket-ref",
        )
        assert r.status_code == 200
        assert r.json() == {"pr_number": 42, "pr_url": "https://github.com/o/r/pull/42"}

    async def test_auto_dismisses_on_success(self, client_factory, monkeypatch):
        """When remove_ticket_ref succeeds and returns a populated
        ticket_ref, the route auto-dismisses the matching row so the
        dashboard count drops immediately."""
        from canon.web import routes
        from canon.web.services import RemoveTicketRefResult

        monkeypatch.setattr(
            routes,
            "remove_ticket_ref",
            AsyncMock(
                return_value=RemoveTicketRefResult(
                    pr_number=42,
                    pr_url="https://github.com/o/r/pull/42",
                    already_existed=False,
                    system="github",
                    ticket_ref="o/r#1",
                )
            ),
        )
        ref_store = AsyncMock()
        ref_store.dismiss = AsyncMock()
        client = client_factory(ref_store=ref_store)

        r = await client.post(
            f"/app/{ORG}/api/specs/o/r/docs%2Fspecs%2Ftest.md/sections/1/remove-ticket-ref",
        )
        assert r.status_code == 200
        ref_store.dismiss.assert_awaited_once()
        # Verify dismiss was called with the matching system + ticket_ref
        dismiss_kwargs = ref_store.dismiss.await_args.kwargs
        assert dismiss_kwargs["system"] == "github"
        assert dismiss_kwargs["ticket_ref"] == "o/r#1"
        assert dismiss_kwargs["installation_id"] == 1

    async def test_auto_dismisses_when_already_existed(self, client_factory, monkeypatch):
        """409 path also auto-dismisses — user has acknowledged the ref by
        finding (or opening) a remove-PR; surfacing it on the next
        dashboard load is just noise."""
        from canon.web import routes
        from canon.web.services import RemoveTicketRefResult

        monkeypatch.setattr(
            routes,
            "remove_ticket_ref",
            AsyncMock(
                return_value=RemoveTicketRefResult(
                    pr_number=7,
                    pr_url="https://github.com/o/r/pull/7",
                    already_existed=True,
                    system="github",
                    ticket_ref="o/r#1",
                )
            ),
        )
        ref_store = AsyncMock()
        ref_store.dismiss = AsyncMock()
        client = client_factory(ref_store=ref_store)

        r = await client.post(
            f"/app/{ORG}/api/specs/o/r/docs%2Fspecs%2Ftest.md/sections/1/remove-ticket-ref",
        )
        assert r.status_code == 409
        ref_store.dismiss.assert_awaited_once()

    async def test_auto_dismiss_failure_does_not_break_response(self, client_factory, monkeypatch):
        """If the auto-dismiss call raises, the route still returns the PR
        metadata — the PR was already created, the user shouldn't see an
        error just because the bookkeeping write failed."""
        from canon.web import routes
        from canon.web.services import RemoveTicketRefResult

        monkeypatch.setattr(
            routes,
            "remove_ticket_ref",
            AsyncMock(
                return_value=RemoveTicketRefResult(
                    pr_number=42,
                    pr_url="https://github.com/o/r/pull/42",
                    already_existed=False,
                    system="github",
                    ticket_ref="o/r#1",
                )
            ),
        )
        ref_store = AsyncMock()
        ref_store.dismiss = AsyncMock(side_effect=RuntimeError("db down"))
        client = client_factory(ref_store=ref_store)

        r = await client.post(
            f"/app/{ORG}/api/specs/o/r/docs%2Fspecs%2Ftest.md/sections/1/remove-ticket-ref",
        )
        assert r.status_code == 200
        assert r.json() == {"pr_number": 42, "pr_url": "https://github.com/o/r/pull/42"}
