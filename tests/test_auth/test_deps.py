"""Tests for auth dependencies (get_current_user, require_permission)."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from canon.auth.deps import _session_to_current_user, get_current_user, require_permission
from canon.auth.models import ANONYMOUS_USER
from canon.auth.permissions import Permission
from canon.settings import Settings


class _FakeHeaders(dict):
    """A real dict so .get() works as expected."""


class _FakeState:
    """A real object for request.state — getattr returns None for unset attrs."""


def _mock_request(
    *,
    session: dict | None = None,
    auth_header: str = "",
    settings: Settings | None = None,
    user_store=None,
) -> MagicMock:
    """Create a mock Request with the given properties."""
    request = MagicMock()
    request.session = session or {}
    headers = _FakeHeaders()
    if auth_header:
        headers["Authorization"] = auth_header
    request.headers = headers

    # Use a real object for request.state so getattr(..., None) works correctly
    request.state = _FakeState()

    app_state = MagicMock()
    app_state.settings = settings or Settings()
    app_state.user_store = user_store
    app_state.registry = None
    request.app.state = app_state
    return request


class TestSessionToCurrentUser:
    def test_basic_session(self):
        session = {
            "sub": "auth0|123",
            "email": "test@example.com",
            "name": "Test",
            "picture": "pic.jpg",
            "org_id": "org_abc",
            "org_login": "my-org",
            "permissions": ["specs:read", "specs:write"],
        }
        user = _session_to_current_user(session)
        assert user.sub == "auth0|123"
        assert user.email == "test@example.com"
        assert user.org_id == "org_abc"
        assert user.org_login == "my-org"
        assert user.auth_method == "session"
        assert user.has_permission(Permission.SPECS_READ)
        assert user.has_permission(Permission.SPECS_WRITE)
        assert not user.has_permission(Permission.SPECS_ADMIN)

    def test_session_without_permissions_defaults_to_read_only(self):
        session = {"sub": "auth0|123", "email": "test@example.com"}
        user = _session_to_current_user(session)
        assert user.has_permission(Permission.SPECS_READ)
        assert not user.has_permission(Permission.SPECS_WRITE)
        assert not user.has_permission(Permission.SPECS_ADMIN)

    def test_session_with_invalid_permissions_ignored(self):
        session = {"sub": "auth0|123", "permissions": ["specs:read", "invalid:perm"]}
        user = _session_to_current_user(session)
        assert user.has_permission(Permission.SPECS_READ)
        assert len(user.permissions) == 1


class TestGetCurrentUser:
    async def test_anonymous_when_auth_disabled(self):
        request = _mock_request(settings=Settings())
        user = await get_current_user(request)
        assert user == ANONYMOUS_USER
        assert user.is_anonymous

    async def test_session_user(self):
        settings = Settings(
            auth0_domain="test.auth0.com",
            auth0_client_id="cid",
            auth0_client_secret="secret",
        )
        session = {
            "user": {
                "sub": "auth0|123",
                "email": "test@example.com",
                "name": "Test",
                "picture": "",
                "permissions": ["specs:read"],
            }
        }
        request = _mock_request(session=session, settings=settings)
        user = await get_current_user(request)
        assert user.auth_method == "session"
        assert user.sub == "auth0|123"

    async def test_raises_401_when_auth_enabled_no_session(self):
        settings = Settings(
            auth0_domain="test.auth0.com",
            auth0_client_id="cid",
            auth0_client_secret="secret",
        )
        request = _mock_request(settings=settings)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
        assert exc_info.value.status_code == 401

    async def test_api_key_auth(self):
        mock_user_store = AsyncMock()
        mock_user_store.get_api_key_by_hash = AsyncMock(
            return_value={
                "user_sub": "auth0|456",
                "user_email": "api@example.com",
                "user_name": "API User",
                "org_login": "my-org",
                "scopes": ["specs:read", "specs:write"],
                "revoked_at": None,
                "expires_at": None,
            }
        )

        request = _mock_request(
            auth_header="Bearer sw_testkey123",
            user_store=mock_user_store,
        )
        user = await get_current_user(request)
        assert user.auth_method == "api_key"
        assert user.sub == "auth0|456"
        assert user.has_permission(Permission.SPECS_READ)
        assert user.has_permission(Permission.SPECS_WRITE)

    async def test_revoked_api_key_raises_401(self):
        from datetime import datetime

        mock_user_store = AsyncMock()
        mock_user_store.get_api_key_by_hash = AsyncMock(
            return_value={
                "revoked_at": datetime.now(UTC),
                "expires_at": None,
                "scopes": [],
            }
        )
        request = _mock_request(
            auth_header="Bearer sw_revokedkey",
            user_store=mock_user_store,
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail

    async def test_invalid_api_key_raises_401(self):
        mock_user_store = AsyncMock()
        mock_user_store.get_api_key_by_hash = AsyncMock(return_value=None)
        request = _mock_request(
            auth_header="Bearer sw_badkey",
            user_store=mock_user_store,
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
        assert exc_info.value.status_code == 401

    async def test_expired_api_key_raises_401(self):
        from datetime import datetime, timedelta

        mock_user_store = AsyncMock()
        mock_user_store.get_api_key_by_hash = AsyncMock(
            return_value={
                "revoked_at": None,
                "expires_at": datetime.now(UTC) - timedelta(days=1),
                "scopes": ["specs:read"],
            }
        )
        request = _mock_request(
            auth_header="Bearer sw_expiredkey",
            user_store=mock_user_store,
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail

    async def test_no_user_store_for_api_key_raises_401(self):
        request = _mock_request(auth_header="Bearer sw_nostore")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
        assert exc_info.value.status_code == 401


class TestRequirePermission:
    async def test_passes_with_correct_permission(self):
        dep = require_permission(Permission.SPECS_READ)
        from canon.auth.models import CurrentUser

        user = CurrentUser(
            sub="u1",
            permissions=frozenset({Permission.SPECS_READ}),
            auth_method="session",
        )
        mock_request = MagicMock()
        with patch("canon.auth.deps.get_current_user", return_value=user):
            result = await dep(request=mock_request)
        assert result == user

    async def test_raises_403_without_permission(self):
        dep = require_permission(Permission.SPECS_ADMIN)
        from canon.auth.models import CurrentUser

        user = CurrentUser(
            sub="u1",
            permissions=frozenset({Permission.SPECS_READ}),
            auth_method="session",
        )
        mock_request = MagicMock()
        with (
            pytest.raises(HTTPException) as exc_info,
            patch("canon.auth.deps.get_current_user", return_value=user),
        ):
            await dep(request=mock_request)
        assert exc_info.value.status_code == 403
