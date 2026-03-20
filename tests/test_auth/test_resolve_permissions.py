"""Tests for _resolve_permissions in auth/deps.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from canon.auth.deps import _resolve_permissions
from canon.auth.permissions import Permission


def _mock_request(*, auth0_orgs_enabled: bool, user_store=None) -> MagicMock:
    """Create a mock Request with the given auth0_orgs_enabled and user_store."""
    request = MagicMock()
    app_state = MagicMock()
    app_state.settings.auth0_orgs_enabled = auth0_orgs_enabled
    app_state.user_store = user_store
    request.app.state = app_state
    return request


class TestAuth0OrgsEnabled:
    """Branch 1: auth0_orgs_enabled=True => permissions from JWT claims."""

    async def test_permissions_from_claims(self):
        request = _mock_request(auth0_orgs_enabled=True)
        claims = {"permissions": ["specs:read", "specs:write"]}
        result = await _resolve_permissions(request, claims, "sub1")
        assert result == frozenset({Permission.SPECS_READ, Permission.SPECS_WRITE})

    async def test_all_permissions_from_claims(self):
        request = _mock_request(auth0_orgs_enabled=True)
        claims = {"permissions": ["specs:read", "specs:write", "specs:admin", "org:manage"]}
        result = await _resolve_permissions(request, claims, "sub1")
        assert result == frozenset(Permission)

    async def test_empty_permissions_from_claims(self):
        request = _mock_request(auth0_orgs_enabled=True)
        claims = {"permissions": []}
        result = await _resolve_permissions(request, claims, "sub1")
        assert result == frozenset()

    async def test_invalid_permissions_filtered_out(self):
        request = _mock_request(auth0_orgs_enabled=True)
        claims = {"permissions": ["specs:read", "invalid:perm", "bogus"]}
        result = await _resolve_permissions(request, claims, "sub1")
        assert result == frozenset({Permission.SPECS_READ})

    async def test_no_permissions_key_in_claims(self):
        request = _mock_request(auth0_orgs_enabled=True)
        claims = {}
        result = await _resolve_permissions(request, claims, "sub1")
        assert result == frozenset()


class TestDbRoleLookup:
    """Branch 2: auth0_orgs_enabled=False with user_store => DB role lookup."""

    async def test_admin_gets_all_permissions(self):
        user_store = AsyncMock()
        user_store.get_user_by_sub = AsyncMock(return_value={"role": "admin"})
        request = _mock_request(auth0_orgs_enabled=False, user_store=user_store)
        result = await _resolve_permissions(request, {}, "sub1")
        assert result == frozenset(Permission)
        assert len(result) == 4

    async def test_editor_gets_read_write(self):
        user_store = AsyncMock()
        user_store.get_user_by_sub = AsyncMock(return_value={"role": "editor"})
        request = _mock_request(auth0_orgs_enabled=False, user_store=user_store)
        result = await _resolve_permissions(request, {}, "sub1")
        assert result == frozenset({Permission.SPECS_READ, Permission.SPECS_WRITE})

    async def test_viewer_gets_read_only(self):
        user_store = AsyncMock()
        user_store.get_user_by_sub = AsyncMock(return_value={"role": "viewer"})
        request = _mock_request(auth0_orgs_enabled=False, user_store=user_store)
        result = await _resolve_permissions(request, {}, "sub1")
        assert result == frozenset({Permission.SPECS_READ})

    async def test_missing_role_defaults_to_viewer(self):
        """When user_record has no 'role' key, defaults to viewer (least privilege)."""
        user_store = AsyncMock()
        user_store.get_user_by_sub = AsyncMock(
            return_value={"id": 1, "oidc_sub": "sub1", "email": "a@b.c"}
        )
        request = _mock_request(auth0_orgs_enabled=False, user_store=user_store)
        result = await _resolve_permissions(request, {}, "sub1")
        assert result == frozenset({Permission.SPECS_READ})

    async def test_invalid_role_string_falls_back_to_viewer(self):
        """An unrecognized role string falls back to viewer (least privilege)."""
        user_store = AsyncMock()
        user_store.get_user_by_sub = AsyncMock(return_value={"role": "superuser"})
        request = _mock_request(auth0_orgs_enabled=False, user_store=user_store)
        result = await _resolve_permissions(request, {}, "sub1")
        assert result == frozenset({Permission.SPECS_READ})

    async def test_user_not_found_falls_back_to_read_only(self):
        """When user is not found in DB, falls back to read-only."""
        user_store = AsyncMock()
        user_store.get_user_by_sub = AsyncMock(return_value=None)
        request = _mock_request(auth0_orgs_enabled=False, user_store=user_store)
        result = await _resolve_permissions(request, {}, "sub1")
        assert result == frozenset({Permission.SPECS_READ})


class TestFallback:
    """Branch 3: DB failure or missing user_store => read-only fallback."""

    async def test_db_network_error_raises_503(self):
        """Network/DB errors raise HTTPException rather than silently downgrading."""
        user_store = AsyncMock()
        user_store.get_user_by_sub = AsyncMock(side_effect=OSError("DB connection lost"))
        request = _mock_request(auth0_orgs_enabled=False, user_store=user_store)
        with pytest.raises(HTTPException) as exc_info:
            await _resolve_permissions(request, {}, "sub1")
        assert exc_info.value.status_code == 503

    async def test_db_timeout_raises_503(self):
        """Timeout errors also raise 503."""
        user_store = AsyncMock()
        user_store.get_user_by_sub = AsyncMock(side_effect=TimeoutError())
        request = _mock_request(auth0_orgs_enabled=False, user_store=user_store)
        with pytest.raises(HTTPException) as exc_info:
            await _resolve_permissions(request, {}, "sub1")
        assert exc_info.value.status_code == 503

    async def test_no_user_store_returns_read_only(self):
        request = _mock_request(auth0_orgs_enabled=False, user_store=None)
        result = await _resolve_permissions(request, {}, "sub1")
        assert result == frozenset({Permission.SPECS_READ})
        assert Permission.SPECS_WRITE not in result

    async def test_empty_sub_returns_read_only(self):
        """When sub is empty, user_store lookup is skipped, returns read-only."""
        user_store = AsyncMock()
        request = _mock_request(auth0_orgs_enabled=False, user_store=user_store)
        result = await _resolve_permissions(request, {}, "")
        assert result == frozenset({Permission.SPECS_READ})
        # user_store should not have been called
        user_store.get_user_by_sub.assert_not_awaited()
